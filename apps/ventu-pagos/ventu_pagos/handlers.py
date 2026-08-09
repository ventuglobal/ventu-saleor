"""Lógica de pagos: helpers puros + dispatch de eventos de transacción de Saleor.

Los *helpers puros* (buy_order, monto, mapeo Webpay→resultado Saleor) son
testeables sin red. Los *handlers* de webhook dependen del payload de Saleor
(que varía por versión) y llaman al cliente Webpay; su forma queda cableada y el
mapeo de campos se afina contra un payload real cuando el stack esté arriba.

Flujo (Transaction API de Saleor):
  TRANSACTION_INITIALIZE_SESSION  → crea tx Webpay → result ACTION_REQUIRED + url
  (retorno de Webpay a /webpay/return) → commit → marca la tx AUTHORIZED/CHARGED
  TRANSACTION_CHARGE_REQUESTED    → captura (si auth/capture en dos pasos)
  TRANSACTION_REFUND_REQUESTED    → refund
  TRANSACTION_CANCELATION_REQUESTED → void/anulación
"""

from __future__ import annotations

import re
from typing import Any

from . import config, webpay_client

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


def webpay_buy_order(reference: str) -> str:
    """buy_order de Webpay: máx 26 chars, alfanumérico (+ _ -). Deriva del id de
    transacción de Saleor, saneado y truncado."""
    clean = re.sub(r"[^A-Za-z0-9_-]", "", str(reference))
    return clean[:26] or "ventu"


def webpay_session_id(reference: str) -> str:
    """session_id de Webpay: máx 61 chars."""
    clean = re.sub(r"[^A-Za-z0-9_-]", "", str(reference))
    return clean[:61] or "ventu-session"


def commit_result(commit_response: dict) -> str:
    """Mapea la respuesta de commit de Webpay al `result` que espera Saleor.

    Webpay: status == 'AUTHORIZED' y response_code == 0 ⇒ éxito.
    """
    ok = (
        (commit_response.get("status") == "AUTHORIZED")
        and (int(commit_response.get("response_code", -1)) == 0)
    )
    return "CHARGE_SUCCESS" if ok else "CHARGE_FAILURE"


def refund_result(refund_response: dict) -> str:
    # Webpay refund: type NULLIFIED/REVERSED con response_code 0 ⇒ éxito.
    ok = int(refund_response.get("response_code", -1)) == 0
    return "REFUND_SUCCESS" if ok else "REFUND_FAILURE"


# ───────────────────── builders de respuesta a Saleor ─────────────────────

def gateway_initialize_response() -> dict:
    """Respuesta de PAYMENT_GATEWAY_INITIALIZE_SESSION: config para el storefront."""
    return {"data": {"gateway": "ventu.webpay", "environment": config.WEBPAY_ENV}}


def action_required_response(*, psp_reference: str, amount, webpay_url: str, token: str) -> dict:
    """Respuesta de TRANSACTION_INITIALIZE_SESSION: redirigir al portal de Webpay."""
    return {
        "pspReference": psp_reference,
        "result": "CHARGE_ACTION_REQUIRED",
        "amount": amount,
        "data": {"webpayUrl": webpay_url, "token": token},
    }


def result_response(*, result: str, psp_reference: str, amount=None) -> dict:
    out: dict[str, Any] = {"result": result, "pspReference": psp_reference}
    if amount is not None:
        out["amount"] = amount
    return out


# ─────────────────────────── handlers de evento ───────────────────────────

def handle_transaction_initialize(payload: dict) -> dict:
    """Crea la transacción en Webpay y pide redirección."""
    tx = payload.get("transaction") or {}
    action = payload.get("action") or {}
    reference = tx.get("id") or payload.get("idempotencyKey") or "ventu"
    amount = action.get("amount") or (tx.get("authorizedAmount") or {}).get("amount") or 0

    created = webpay_client.create(
        buy_order=webpay_buy_order(reference),
        session_id=webpay_session_id(reference),
        amount=to_amount(amount),
        return_url=config.RETURN_URL,
    )
    return action_required_response(
        psp_reference=str(reference),
        amount=amount,
        webpay_url=created.get("url", ""),
        token=created.get("token", ""),
    )


def handle_refund(payload: dict) -> dict:
    tx = payload.get("transaction") or {}
    action = payload.get("action") or {}
    token = (tx.get("pspReference") or "")
    amount = action.get("amount") or 0
    resp = webpay_client.refund(token, to_amount(amount))
    return result_response(result=refund_result(resp), psp_reference=token, amount=amount)
