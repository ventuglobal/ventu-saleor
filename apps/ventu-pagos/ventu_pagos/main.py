"""App Ventu Pagos — payment app (Webpay/Transbank) de Ventu 2.0.

Su propia Saleor App por el permiso especial `HANDLE_PAYMENTS` (Saleor la trata
como payment gateway) y por aislamiento de seguridad. Modo: Inyecta (webhooks
síncronos de transacción, camino crítico del checkout).

Endpoints:
  - GET  /health            → liveness + ambiente Webpay
  - GET  /manifest          → manifest de payment app (HANDLE_PAYMENTS + webhooks)
  - POST /register          → recibe y persiste el auth_token al instalar
  - POST /webhooks/saleor   → eventos síncronos de pago (dispatch)
  - POST /webpay/return     → retorno de Webpay (fallback/testing; GET y POST)
  - POST /tasks/reconcile   → reconciliador (cron de Railway)
"""

from __future__ import annotations

import logging

from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.responses import JSONResponse, RedirectResponse

from . import config, db, handlers, saleor_signature, store

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("ventu.pagos")

app = FastAPI(title="Ventu Pagos", version="0.2.0")


# Subscription que fija la forma (camelCase) del payload de cada evento sync.
_WEBHOOK_SUBSCRIPTION = """
subscription {
  event {
    ... on TransactionInitializeSession {
      action { amount currency actionType }
      data
      transaction { id pspReference }
      sourceObject {
        __typename
        ... on Checkout { id channel { slug currencyCode } }
        ... on Order { id channel { slug currencyCode } }
      }
    }
    ... on TransactionProcessSession {
      action { amount currency actionType }
      data
      transaction { id pspReference }
      sourceObject {
        __typename
        ... on Checkout { id channel { slug } }
        ... on Order { id channel { slug } }
      }
    }
    ... on TransactionChargeRequested {
      action { amount currency }
      transaction { id pspReference }
    }
    ... on TransactionRefundRequested {
      action { amount currency }
      transaction { id pspReference }
    }
    ... on TransactionCancelationRequested {
      action { amount currency }
      transaction { id pspReference }
    }
    ... on PaymentGatewayInitializeSession {
      sourceObject {
        __typename
        ... on Checkout { channel { slug } }
        ... on Order { channel { slug } }
      }
    }
  }
}
"""


@app.on_event("startup")
def _startup() -> None:
    db.init_db()
    logger.info("Ventu Pagos iniciada (env=%s)", config.WEBPAY_ENV)


@app.get("/health")
async def health() -> dict:
    return {"status": "ok", "env": config.WEBPAY_ENV}


@app.get("/manifest")
async def manifest(request: Request) -> dict:
    base = str(request.base_url).rstrip("/")
    events = [
        "PAYMENT_GATEWAY_INITIALIZE_SESSION",
        "TRANSACTION_INITIALIZE_SESSION",
        "TRANSACTION_PROCESS_SESSION",
        "TRANSACTION_CHARGE_REQUESTED",
        "TRANSACTION_REFUND_REQUESTED",
        "TRANSACTION_CANCELATION_REQUESTED",
    ]
    return {
        "id": "cl.ventu.pagos",
        "version": app.version,
        "name": "Ventu Pagos (Webpay)",
        "about": "Pasarela Webpay/Transbank para Ventu sobre Saleor.",
        "permissions": ["HANDLE_PAYMENTS"],
        "appUrl": base,
        "tokenTargetUrl": f"{base}/register",
        "webhooks": [{
            "name": "Ventu Webpay payments",
            "targetUrl": f"{base}/webhooks/saleor",
            "syncEvents": events,
            "asyncEvents": [],
            "query": _WEBHOOK_SUBSCRIPTION,
            "isActive": True,
        }],
    }


@app.post("/register")
async def register(request: Request) -> dict:
    body = await request.json()
    token = body.get("auth_token")
    if not token:
        raise HTTPException(status_code=400, detail="falta auth_token")
    store.set_config("auth_token", token)
    # Saleor manda el dominio en el header; úsalo para JWKS y GraphQL si no hay env.
    saleor_domain = request.headers.get("saleor-domain") or request.headers.get("Saleor-Domain")
    saleor_api_url = body.get("saleor_api_url") or (
        f"https://{saleor_domain}/graphql/" if saleor_domain else config.SALEOR_API_URL
    )
    if saleor_api_url:
        store.set_config("saleor_api_url", saleor_api_url)
    logger.info("Ventu Pagos registrada; auth_token persistido (len=%d)", len(token))
    return {"status": "ok"}


@app.post("/webhooks/saleor")
async def saleor_webhook(
    request: Request,
    saleor_event: str | None = Header(default=None),
    saleor_signature_header: str | None = Header(default=None, alias="saleor-signature"),
) -> JSONResponse:
    raw = await request.body()
    if not saleor_signature.verify(raw, saleor_signature_header):
        raise HTTPException(status_code=401, detail="firma inválida")

    event = (saleor_event or "").lower()
    if event not in handlers.HANDLED_EVENTS:
        return JSONResponse({"result": "IGNORED", "event": event})

    payload = await request.json()
    try:
        if event == "payment_gateway_initialize_session":
            return JSONResponse(handlers.gateway_initialize_response())
        if event == "transaction_initialize_session":
            return JSONResponse(handlers.handle_transaction_initialize(payload))
        if event == "transaction_process_session":
            return JSONResponse(handlers.handle_transaction_process(payload))
        if event == "transaction_charge_requested":
            return JSONResponse(handlers.handle_charge_requested(payload))
        if event == "transaction_refund_requested":
            return JSONResponse(handlers.handle_refund(payload))
        if event == "transaction_cancelation_requested":
            return JSONResponse(handlers.handle_cancelation(payload))
        return JSONResponse({"result": "IGNORED", "event": event})
    except Exception as exc:  # noqa: BLE001
        logger.exception("error procesando %s: %s", event, exc)
        return JSONResponse({"result": "CHARGE_FAILURE", "message": str(exc)[:200]}, status_code=200)


async def _handle_webpay_return(request: Request) -> JSONResponse | RedirectResponse:
    """Fallback: retorno directo de Webpay (si el return_url apunta a esta app).

    El flujo normal manda el return_url al storefront, que llama transactionProcess.
    Esta ruta hace el commit idempotente directo y redirige a una página de
    resultado del storefront, por si se usa en pruebas o como respaldo.
    """
    params: dict[str, str] = {}
    if request.method == "POST":
        form = await request.form()
        params = {k: str(v) for k, v in form.items()}
    params.update({k: v for k, v in request.query_params.items()})

    token = params.get("token_ws")
    if not token:
        # Cliente anuló (TBK_TOKEN) o venció (solo TBK_ORDEN_COMPRA): sin commit.
        buy_order = params.get("TBK_ORDEN_COMPRA")
        if buy_order:
            tx = store.get_tx_by_buy_order(buy_order)
            if tx:
                store.close_tx(tx.token, status="ABORTED", result="CHARGE_FAILURE")
        return RedirectResponse(f"{config.STOREFRONT_URL}/checkout?webpay=aborted", status_code=303)

    outcome = handlers.commit_and_report(token, report_to_saleor=True)
    status = "ok" if outcome["result"] == "CHARGE_SUCCESS" else "failed"
    return RedirectResponse(
        f"{config.STOREFRONT_URL}/checkout?webpay={status}", status_code=303
    )


@app.get("/webpay/return")
async def webpay_return_get(request: Request):
    return await _handle_webpay_return(request)


@app.post("/webpay/return")
async def webpay_return_post(request: Request):
    return await _handle_webpay_return(request)


@app.post("/tasks/reconcile")
async def reconcile(request: Request, authorization: str | None = Header(default=None)) -> dict:
    if config.RECONCILE_TOKEN:
        token = (authorization or "").removeprefix("Bearer ").strip()
        if token != config.RECONCILE_TOKEN:
            raise HTTPException(status_code=401, detail="no autorizado")
    return handlers.reconcile()
