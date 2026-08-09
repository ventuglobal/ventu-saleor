"""App Ventu Pagos — payment app (Webpay/Transbank) de Ventu 2.0.

Su propia Saleor App por el permiso especial `HANDLE_PAYMENTS` (Saleor la trata
como payment gateway) y por aislamiento de seguridad. Modo: Inyecta (webhooks
síncronos de transacción, camino crítico del checkout).

Endpoints:
  - GET  /health
  - GET  /manifest           → manifest de payment app (HANDLE_PAYMENTS + webhooks)
  - POST /register           → recibe el auth_token al instalar
  - POST /webhooks/saleor    → eventos síncronos de pago (dispatch)
  - POST /webpay/return      → retorno de Webpay: commit y cierre de la tx
"""

from __future__ import annotations

import hashlib
import hmac
import logging

from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.responses import JSONResponse

from . import config, handlers, webpay_client

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("ventu.pagos")

app = FastAPI(title="Ventu Pagos", version="0.1.0")


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
        "version": "0.1.0",
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
            "isActive": True,
        }],
    }


@app.post("/register")
async def register(request: Request) -> dict:
    body = await request.json()
    token = body.get("auth_token")
    if not token:
        raise HTTPException(status_code=400, detail="falta auth_token")
    logger.info("Ventu Pagos registrada; auth_token recibido (len=%d)", len(token))
    # TODO: persistir el token en el secret store.
    return {"status": "ok"}


def _verify_signature(raw: bytes, signature: str | None) -> bool:
    if not config.SALEOR_WEBHOOK_SECRET:
        return True
    if not signature:
        return False
    expected = hmac.new(config.SALEOR_WEBHOOK_SECRET.encode(), raw, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature)


@app.post("/webhooks/saleor")
async def saleor_webhook(
    request: Request,
    saleor_event: str | None = Header(default=None),
    saleor_signature: str | None = Header(default=None),
) -> JSONResponse:
    raw = await request.body()
    if not _verify_signature(raw, saleor_signature):
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
        if event == "transaction_refund_requested":
            return JSONResponse(handlers.handle_refund(payload))
        # process/charge/cancelation: el detalle se completa contra payload real.
        # TODO: capture diferido gobernado por OMS (TRANSACTION_CHARGE_REQUESTED).
        logger.info("evento de pago recibido (handler pendiente): %s", event)
        return JSONResponse({"result": "PENDING", "event": event})
    except Exception as exc:  # noqa: BLE001
        logger.exception("error procesando %s: %s", event, exc)
        # Falla de pago → Saleor marca la transacción como fallida.
        return JSONResponse({"result": "FAILURE", "message": str(exc)[:200]}, status_code=200)


@app.post("/webpay/return")
async def webpay_return(request: Request) -> JSONResponse:
    """Retorno de Webpay: recibe token_ws (o TBK_TOKEN si el usuario abortó),
    hace commit y devuelve el estado. En producción, tras el commit se actualiza
    la transacción en Saleor (transactionUpdate / event report) y se redirige al
    storefront."""
    form = await request.form()
    token = form.get("token_ws")
    if not token:
        # Usuario canceló en Webpay (TBK_TOKEN) → transacción abortada.
        return JSONResponse({"status": "aborted"}, status_code=200)
    try:
        result = webpay_client.commit(str(token))
    except Exception as exc:  # noqa: BLE001
        logger.exception("commit Webpay falló: %s", exc)
        return JSONResponse({"status": "error", "message": str(exc)[:200]}, status_code=200)
    return JSONResponse({"status": "committed", "result": handlers.commit_result(result),
                         "webpay": result})
