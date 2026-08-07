"""App Ventu Facturación — reactor de DTE sobre Saleor.

Su propia Saleor App (necesita Playwright para el login SII, distinto perfil que
el "cerebro"). Modo: Reacciona (async). En `ORDER_FULLY_PAID` emite el DTE y
estampa el folio en `order.metadata`.

Robustez (100% automático, sin validación humana):
  - Idempotencia: si la orden ya tiene folio, no re-emite.
  - Dead-letter: si el emisor falla, marca `ventu.dte.status=error` en la orden
    y responde 200 (no reintenta en loop); un reproceso/alerta lo recupera.
"""

from __future__ import annotations

import hashlib
import hmac
import logging

from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.responses import JSONResponse

from . import config, emitter, handlers, saleor_client

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("ventu.facturacion")

app = FastAPI(title="Ventu Facturación", version="0.1.0")

HANDLED = {"order_fully_paid"}


@app.get("/health")
async def health() -> dict:
    return {"status": "ok"}


@app.get("/manifest")
async def manifest(request: Request) -> dict:
    base = str(request.base_url).rstrip("/")
    return {
        "id": "cl.ventu.facturacion",
        "version": "0.1.0",
        "name": "Ventu Facturación (SII)",
        "about": "Emite boletas/facturas SII al pagarse la orden.",
        "permissions": ["MANAGE_ORDERS"],
        "appUrl": base,
        "tokenTargetUrl": f"{base}/register",
        "webhooks": [{
            "name": "Ventu DTE on paid",
            "targetUrl": f"{base}/webhooks/saleor",
            "syncEvents": [],
            "asyncEvents": ["ORDER_FULLY_PAID"],
            "isActive": True,
        }],
    }


@app.post("/register")
async def register(request: Request) -> dict:
    body = await request.json()
    if not body.get("auth_token"):
        raise HTTPException(status_code=400, detail="falta auth_token")
    return {"status": "ok"}


def _verify(raw: bytes, signature: str | None) -> bool:
    if not config.SALEOR_WEBHOOK_SECRET:
        return True
    if not signature:
        return False
    expected = hmac.new(config.SALEOR_WEBHOOK_SECRET.encode(), raw, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature)


def _emit_dte(order: dict) -> dict:
    """Decide boleta/factura y emite. Devuelve el resultado del emisor."""
    receptor = handlers.extract_receptor(order)
    if handlers.decide_document_type(receptor) == "factura":
        return emitter.emitir_factura(receptor, handlers.order_to_factura_items(order))
    return emitter.emitir_boleta(handlers.order_to_boleta_items(order), receptor=receptor)


@app.post("/webhooks/saleor")
async def saleor_webhook(
    request: Request,
    saleor_event: str | None = Header(default=None),
    saleor_signature: str | None = Header(default=None),
) -> JSONResponse:
    raw = await request.body()
    if not _verify(raw, saleor_signature):
        raise HTTPException(status_code=401, detail="firma inválida")

    event = (saleor_event or "").lower()
    if event not in HANDLED:
        return JSONResponse({"ignored": event})

    order = await request.json()
    order_id = order.get("id")
    if not order_id:
        return JSONResponse({"status": "ignored", "reason": "no id"})

    if handlers.already_invoiced(order):
        return JSONResponse({"status": "skipped", "reason": "ya facturada"})

    try:
        result = _emit_dte(order)
    except Exception as exc:  # noqa: BLE001 — emisor cayó (Playwright/API/SII)
        logger.exception("emisión DTE falló order=%s: %s", order_id, exc)
        _safe_mark_error(order_id, str(exc))
        return JSONResponse({"status": "error", "message": str(exc)[:200]})

    if result.get("estado") == "emitida":
        try:
            saleor_client.write_dte_metadata(order_id, folio=result.get("folio"), status="emitida")
        except Exception:  # noqa: BLE001
            logger.exception("no se pudo estampar folio en order=%s", order_id)
        return JSONResponse({"status": "emitida", "folio": result.get("folio")})

    # Emisor devolvió no-emitida → dead-letter.
    _safe_mark_error(order_id, result.get("detalle", "no-emitida"))
    return JSONResponse({"status": "no-emitida", "detalle": result.get("detalle")})


def _safe_mark_error(order_id: str, detail: str) -> None:
    try:
        saleor_client.write_dte_metadata(order_id, folio=None, status=f"error: {detail[:120]}")
    except Exception:  # noqa: BLE001
        logger.exception("no se pudo marcar error DTE en order=%s", order_id)
