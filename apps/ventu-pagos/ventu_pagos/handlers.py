"""Lógica de pagos: helpers puros + handlers de eventos de transacción de Saleor.

Flujo (Transactions API de Saleor, Webpay Plus captura simultánea):

  TRANSACTION_INITIALIZE_SESSION   → valida canal/moneda → webpay.create()
                                     → persiste webpay_tx → CHARGE_ACTION_REQUIRED + url
  (cliente paga; vuelve al storefront que llama transactionProcess)
  TRANSACTION_PROCESS_SESSION      → commit_and_report(token) → CHARGE_SUCCESS/FAILURE (sync)
  TRANSACTION_CHARGE_REQUESTED     → captura simultánea: éxito con lo ya cobrado
  TRANSACTION_REFUND_REQUESTED     → webpay.refund()
  TRANSACTION_CANCELATION_REQUESTED→ webpay.refund() (anulación)

Regla de oro: un pago está aprobado solo si el commit de ESTE servidor devuelve
response_code == 0 y status == AUTHORIZED.
"""

from __future__ import annotations

import datetime as dt
import logging
import re
import secrets

from . import config, models, saleor_client, store, webpay_client

logger = logging.getLogger("ventu.pagos.handlers")

# Eventos síncronos de pago que maneja la app.
HANDLED_EVENTS = {
    "payment_gateway_initialize_session",
    "transaction_initialize_session",
    "transaction_process_session",
    "transaction_charge_requested",
    "transaction_refund_requested",
    "transaction_cancelation_requested",
}


# ───────────────────────────── helpers puros ─────────────────────────────

def to_amount(saleor_amount) -> int:
    """CLP es entero: Webpay no acepta decimales. Redondea al peso."""
    return int(round(float(saleor_amount)))


# Charset permitido por Webpay para buy_order: letras, números y |_=&%.,~:/?[+!@()>-
_BUY_ORDER_OK = re.compile(r"[^A-Za-z0-9_=&%.,~:/?\[+!@()>-]")


def new_buy_order() -> str:
    """buy_order único por intento: VR + fecha/hora + aleatorio. ≤ 26 chars."""
    stamp = dt.datetime.now(dt.timezone.utc).strftime("%y%m%d%H%M%S")  # 12
    rand = secrets.token_hex(3).upper()  # 6
    bo = f"VR{stamp}{rand}"  # 2+12+6 = 20
    return _BUY_ORDER_OK.sub("", bo)[:26]


def webpay_session_id(reference: str) -> str:
    """session_id de Webpay: máx 61 chars, saneado."""
    clean = re.sub(r"[^A-Za-z0-9_-]", "", str(reference))
    return clean[:61] or "ventu-session"


def commit_authorized(commit_response: dict) -> bool:
    """La regla de oro: AUTHORIZED + response_code == 0."""
    try:
        rc = int(commit_response.get("response_code", -1))
    except (TypeError, ValueError):
        rc = -1
    return commit_response.get("status") == "AUTHORIZED" and rc == 0


def commit_result(commit_response: dict) -> str:
    """Mapea la respuesta de commit de Webpay al `result` de Saleor."""
    return "CHARGE_SUCCESS" if commit_authorized(commit_response) else "CHARGE_FAILURE"


def refund_result(refund_response: dict) -> str:
    """Webpay refund: type NULLIFIED/REVERSED con response_code 0 (o ausente) ⇒ éxito."""
    rc = refund_response.get("response_code")
    ok = (rc is None) or (int(rc) == 0)
    type_ok = refund_response.get("type") in ("REVERSED", "NULLIFIED", None)
    return "REFUND_SUCCESS" if (ok and type_ok) else "REFUND_FAILURE"


def payment_metadata(commit_response: dict) -> dict[str, str]:
    """Metadata a guardar en la orden tras un commit aprobado."""
    card = commit_response.get("card_detail") or {}
    meta = {
        "ventu.pago.metodo": "webpay",
        "ventu.pago.authorization_code": commit_response.get("authorization_code"),
        "ventu.pago.payment_type_code": commit_response.get("payment_type_code"),
        "ventu.pago.installments": commit_response.get("installments_number"),
        "ventu.pago.card_last4": card.get("card_number"),
    }
    return {k: str(v) for k, v in meta.items() if v is not None}


# ───────────────────── builders de respuesta a Saleor ─────────────────────

def gateway_initialize_response() -> dict:
    return {"data": {"gateway": "ventu.webpay", "environment": config.WEBPAY_ENV}}


def action_required_response(*, psp_reference: str, amount, webpay_url: str, token: str) -> dict:
    return {
        "pspReference": psp_reference,
        "result": "CHARGE_ACTION_REQUIRED",
        "amount": amount,
        "data": {"webpayUrl": webpay_url, "token": token},
    }


def result_response(*, result: str, psp_reference: str, amount=None, message: str | None = None) -> dict:
    out: dict = {"result": result, "pspReference": psp_reference}
    if amount is not None:
        out["amount"] = amount
    if message:
        out["message"] = message[:512]
    return out


# ───────────────────── extracción de payload (subscription) ─────────────────────

def _source_object(payload: dict) -> dict:
    return payload.get("sourceObject") or {}


def _channel_slug(payload: dict) -> str | None:
    return (_source_object(payload).get("channel") or {}).get("slug")


def _action_amount(payload: dict) -> float:
    action = payload.get("action") or {}
    return action.get("amount") or 0


def _action_currency(payload: dict) -> str | None:
    return (payload.get("action") or {}).get("currency")


def _transaction_id(payload: dict) -> str | None:
    return (payload.get("transaction") or {}).get("id")


def _token_from_data(payload: dict) -> str:
    data = payload.get("data") or {}
    return str(data.get("token_ws") or data.get("tokenWs") or "")


# ─────────────────────────── handlers de evento ───────────────────────────

def handle_transaction_initialize(payload: dict) -> dict:
    """Valida canal/moneda, crea la tx en Webpay, persiste y pide redirección."""
    channel = _channel_slug(payload)
    psp_pending = _transaction_id(payload) or "ventu"
    if channel is not None and channel not in config.WEBPAY_CHANNELS:
        logger.warning("initialize rechazado: canal '%s' no habilitado para Webpay", channel)
        return result_response(
            result="CHARGE_FAILURE",
            psp_reference=psp_pending,
            message=f"Webpay no disponible para el canal {channel}",
        )
    currency = _action_currency(payload)
    if currency is not None and currency != config.WEBPAY_CURRENCY:
        return result_response(
            result="CHARGE_FAILURE",
            psp_reference=psp_pending,
            message=f"Webpay solo opera en {config.WEBPAY_CURRENCY}",
        )

    saleor_tx_id = _transaction_id(payload)
    amount = to_amount(_action_amount(payload))
    buy_order = new_buy_order()
    session_id = webpay_session_id(saleor_tx_id or buy_order)

    created = webpay_client.create(
        buy_order=buy_order,
        session_id=session_id,
        amount=amount,
        return_url=config.RETURN_URL,
    )
    token = created.get("token", "")
    store.create_tx(
        token=token,
        buy_order=buy_order,
        session_id=session_id,
        amount=amount,
        saleor_transaction_id=saleor_tx_id,
        checkout_id=_source_object(payload).get("id"),
        channel_slug=channel,
    )
    # pspReference = token Webpay: así los eventos posteriores (refund) lo ubican.
    return action_required_response(
        psp_reference=token or str(saleor_tx_id),
        amount=amount,
        webpay_url=created.get("url", ""),
        token=token,
    )


def commit_and_report(
    token: str,
    *,
    saleor_transaction_id: str | None = None,
    report_to_saleor: bool = False,
) -> dict:
    """Confirma la tx en Webpay de forma **idempotente** y cierra `webpay_tx`.

    - Si la tx ya tiene resultado → lo devuelve sin segundo commit.
    - Verifica que amount y buy_order del commit coincidan con lo guardado; si no,
      anula el cobro (refund total) y marca fallida.
    - `report_to_saleor=True` (reconciliador/fallback) reporta vía
      transactionEventReport; en el camino sync el propio response lo hace.

    Devuelve {result, amount, pspReference, message}.
    """
    if not token:
        return {"result": "CHARGE_FAILURE", "pspReference": "", "message": "sin token_ws"}

    tx = store.get_tx(token)
    stx_id = saleor_transaction_id or (tx.saleor_transaction_id if tx else None)

    # Idempotencia: resultado ya conocido.
    if tx is not None and tx.is_closed:
        return {
            "result": tx.result,
            "amount": tx.amount,
            "pspReference": token,
            "message": "resultado previo (idempotente)",
        }

    try:
        commit_resp = webpay_client.commit(token)
    except webpay_client.WebpayError as exc:
        # Resultado desconocido: intentar status para recuperarse.
        logger.warning("commit falló (%s); consultando status", exc)
        try:
            commit_resp = webpay_client.status(token)
        except webpay_client.WebpayError as exc2:
            logger.error("status tampoco respondió para token=%s: %s", token, exc2)
            return {"result": "CHARGE_FAILURE", "pspReference": token, "message": str(exc)[:200]}

    authorized = commit_authorized(commit_resp)
    result = "CHARGE_SUCCESS" if authorized else "CHARGE_FAILURE"
    amount_committed = to_amount(commit_resp.get("amount", tx.amount if tx else 0))
    message = None

    # Verificación de integridad: monto y buy_order deben cuadrar con lo guardado.
    if authorized and tx is not None:
        mismatch = (amount_committed != tx.amount) or (
            commit_resp.get("buy_order") not in (None, tx.buy_order)
        )
        if mismatch:
            logger.error(
                "DISCREPANCIA token=%s: commit amount=%s/buy_order=%s vs guardado amount=%s/buy_order=%s"
                " → anulando",
                token, amount_committed, commit_resp.get("buy_order"), tx.amount, tx.buy_order,
            )
            try:
                webpay_client.refund(token, amount_committed)
            except webpay_client.WebpayError as exc:
                logger.error("no se pudo anular el cobro discrepante token=%s: %s", token, exc)
            authorized = False
            result = "CHARGE_FAILURE"
            message = "monto/orden no coinciden; cobro anulado"

    status = models.STATUS_AUTHORIZED if authorized else models.STATUS_FAILED
    store.close_tx(token, status=status, result=result, commit_response=commit_resp)

    # Metadata de la orden (best-effort, no bloquea el resultado).
    if authorized and stx_id:
        try:
            saleor_client.update_metadata(object_id=stx_id, items=payment_metadata(commit_resp))
        except Exception as exc:  # noqa: BLE001
            logger.warning("no se pudo escribir metadata: %s", exc)

    # Reporte asíncrono (solo cuando no hay response sync que lo lleve).
    if report_to_saleor and stx_id:
        try:
            saleor_client.report_transaction_event(
                transaction_id=stx_id,
                event_type=result,
                amount=amount_committed,
                psp_reference=token,
                message=message,
            )
            store.mark_reported(token)
        except Exception as exc:  # noqa: BLE001
            logger.warning("transactionEventReport falló: %s", exc)

    return {
        "result": result,
        "amount": amount_committed,
        "pspReference": token,
        "message": message,
    }


def handle_transaction_process(payload: dict) -> dict:
    """Camino feliz: recibe token_ws vía data y confirma el cobro (respuesta sync)."""
    token = _token_from_data(payload)
    saleor_tx_id = _transaction_id(payload)
    if not token:
        # El cliente anuló o venció el formulario: sin commit.
        return result_response(
            result="CHARGE_FAILURE",
            psp_reference=str(saleor_tx_id or ""),
            message="pago no completado en Webpay",
        )
    outcome = commit_and_report(token, saleor_transaction_id=saleor_tx_id)
    return result_response(
        result=outcome["result"],
        psp_reference=outcome["pspReference"] or str(saleor_tx_id or ""),
        amount=outcome.get("amount"),
        message=outcome.get("message"),
    )


def handle_charge_requested(payload: dict) -> dict:
    """Captura simultánea: el cobro ya ocurrió en el commit. Confirmar éxito."""
    token = (payload.get("transaction") or {}).get("pspReference") or ""
    amount = _action_amount(payload)
    return result_response(result="CHARGE_SUCCESS", psp_reference=token, amount=amount)


def _refund_or_cancel(payload: dict, *, cancel: bool) -> dict:
    tx = payload.get("transaction") or {}
    token = tx.get("pspReference") or ""
    amount = to_amount(_action_amount(payload))
    ok_result = "CANCEL_SUCCESS" if cancel else "REFUND_SUCCESS"
    fail_result = "CANCEL_FAILURE" if cancel else "REFUND_FAILURE"
    try:
        resp = webpay_client.refund(token, amount)
    except webpay_client.WebpayError as exc:
        logger.warning("refund/cancel falló token=%s: %s", token, exc)
        return result_response(result=fail_result, psp_reference=token, amount=amount,
                               message=str(exc)[:200])
    result = ok_result if refund_result(resp) == "REFUND_SUCCESS" else fail_result
    if result in ("REFUND_SUCCESS", "CANCEL_SUCCESS"):
        store.close_tx(token, status=models.STATUS_REFUNDED, result=result, commit_response=resp)
    return result_response(result=result, psp_reference=token, amount=amount)


def handle_refund(payload: dict) -> dict:
    return _refund_or_cancel(payload, cancel=False)


def handle_cancelation(payload: dict) -> dict:
    return _refund_or_cancel(payload, cancel=True)


# ─────────────────────────────── reconciliador ───────────────────────────────

def reconcile() -> dict:
    """Cierra transacciones INITIALIZED viejas consultando su status en Webpay.

    Para el cron de Railway. Si una quedó AUTHORIZED sin cierre (navegador cerrado),
    reporta el éxito a Saleor y alerta; si no, la cierra como fallida.
    """
    pendientes = store.pending_older_than(config.RECONCILE_AFTER_MIN)
    cerradas, autorizadas_huerfanas = 0, 0
    for tx in pendientes:
        try:
            st = webpay_client.status(tx.token)
        except webpay_client.WebpayError as exc:
            logger.warning("reconcile: status falló token=%s: %s", tx.token, exc)
            continue
        if commit_authorized(st):
            autorizadas_huerfanas += 1
            logger.error(
                "ALERTA reconcile: token=%s quedó AUTHORIZED sin cierre (posible cobro sin orden)",
                tx.token,
            )
            commit_and_report(tx.token, saleor_transaction_id=tx.saleor_transaction_id,
                              report_to_saleor=True)
        else:
            store.close_tx(tx.token, status=models.STATUS_FAILED, result="CHARGE_FAILURE",
                           commit_response=st)
        cerradas += 1
    return {
        "revisadas": len(pendientes),
        "cerradas": cerradas,
        "autorizadas_sin_cierre": autorizadas_huerfanas,
    }
