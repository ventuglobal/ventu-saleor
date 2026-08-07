"""App Ventu — el cerebro de Ventu 2.0 sobre Saleor (servicio principal).

Aloja los módulos que extienden Saleor (Ley 4 de la constitución): Catálogo &
Abastecimiento, Pricing, OMS/Facturación, etc. Pagos vive en una app aparte
(`apps/ventu-pagos`) por su permiso especial `HANDLE_PAYMENTS`.

Endpoints:
  - GET  /health              → liveness.
  - GET  /manifest            → manifest de Saleor App (para instalarla).
  - POST /register            → recibe el auth_token que emite Saleor al instalar.
  - POST /webhooks/saleor     → eventos async de Saleor (órdenes → OMS/Facturación).
  - POST /catalog/publish     → publica un lote de variantes (stock/precio) a Saleor.

Este incremento entrega el spine de **Catálogo** (publica stock/precio) y deja
los reactores de orden (OMS/Facturación) como stubs a completar en su fase.
"""

from __future__ import annotations

import hashlib
import hmac
import logging

from fastapi import Depends, FastAPI, Header, HTTPException, Request

from . import config
from .catalog.models import VariantInput
from .catalog.publisher import publish_batch
from .pricing.models import CostInput
from .pricing.service import compute_channel_prices, publish_prices_for

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("ventu")

app = FastAPI(title="Ventu App", version="0.1.0")

ORDER_EVENTS = {"order_created", "order_fully_paid", "order_updated"}


# ─────────────────────────── infra / auth ───────────────────────────

@app.get("/health")
async def health() -> dict:
    return {"status": "ok"}


@app.get("/manifest")
async def manifest(request: Request) -> dict:
    base = str(request.base_url).rstrip("/")
    return {
        "id": "cl.ventu.app",
        "version": "0.1.0",
        "name": "Ventu",
        "about": "Cerebro de Ventu: catálogo, pricing, stock y OMS sobre Saleor.",
        "permissions": ["MANAGE_PRODUCTS", "MANAGE_ORDERS", "MANAGE_CHANNELS"],
        "appUrl": base,
        "tokenTargetUrl": f"{base}/register",
        "webhooks": [{
            "name": "Ventu order events",
            "targetUrl": f"{base}/webhooks/saleor",
            "syncEvents": [],
            "asyncEvents": ["ORDER_CREATED", "ORDER_FULLY_PAID", "ORDER_UPDATED"],
            "isActive": True,
        }],
    }


@app.post("/register")
async def register(request: Request) -> dict:
    body = await request.json()
    token = body.get("auth_token")
    if not token:
        raise HTTPException(status_code=400, detail="falta auth_token")
    logger.info("Saleor App registrada; auth_token recibido (len=%d)", len(token))
    # TODO: persistir el token en el secret store y usarlo como SALEOR_AUTH_TOKEN.
    return {"status": "ok"}


def _require_admin(authorization: str = Header(default="")) -> None:
    """Protege endpoints de administración con VENTU_ADMIN_TOKEN (Bearer)."""
    if not config.VENTU_ADMIN_TOKEN:
        return  # sin token configurado → abierto (solo dev)
    presented = authorization[7:] if authorization.lower().startswith("bearer ") else ""
    if not presented or not hmac.compare_digest(presented, config.VENTU_ADMIN_TOKEN):
        raise HTTPException(status_code=401, detail="token de administración inválido")


# ─────────────────────────── catálogo (Publica) ───────────────────────────

@app.post("/catalog/publish")
async def catalog_publish(request: Request, _: None = Depends(_require_admin)) -> dict:
    """Publica un lote de variantes a Saleor (stock + precio + visibilidad).

    Body: {"items": [{"sku": "...", "available": 42,
                      "prices": [{"channel_slug": "retail-cl", "amount": 12990}]}]}
    """
    body = await request.json()
    raw_items = body.get("items") or []
    if not isinstance(raw_items, list):
        raise HTTPException(status_code=400, detail="'items' debe ser una lista")
    items = [VariantInput.from_dict(d) for d in raw_items]
    results = publish_batch(items)
    ok = sum(1 for r in results if r.ok)
    return {
        "published": ok,
        "failed": len(results) - ok,
        "results": [r.__dict__ for r in results],
    }


# ─────────────────────────── pricing (Publica) ───────────────────────────

@app.post("/pricing/publish")
async def pricing_publish(request: Request, _: None = Depends(_require_admin)) -> dict:
    """Computa el precio final por channel (costo + margen + fees + IVA) y lo
    escribe en Saleor.

    Body: {"items": [{"sku": "...", "cost_net": 8500}]}
    """
    body = await request.json()
    raw_items = body.get("items") or []
    if not isinstance(raw_items, list):
        raise HTTPException(status_code=400, detail="'items' debe ser una lista")
    items = [CostInput.from_dict(d) for d in raw_items]
    results = publish_prices_for(items)
    ok = sum(1 for r in results if r.ok)
    return {
        "published": ok,
        "failed": len(results) - ok,
        "results": [r.__dict__ for r in results],
    }


@app.post("/pricing/quote")
async def pricing_quote(request: Request, _: None = Depends(_require_admin)) -> dict:
    """Devuelve el precio computado por channel SIN escribir en Saleor (dry-run)."""
    body = await request.json()
    cost_net = body.get("cost_net")
    if cost_net is None:
        raise HTTPException(status_code=400, detail="falta 'cost_net'")
    prices = compute_channel_prices(float(cost_net))
    return {"cost_net": float(cost_net), "prices": [p.__dict__ for p in prices]}


# ─────────────────────────── órdenes (Reacciona) ───────────────────────────

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
) -> dict:
    raw = await request.body()
    if not _verify_signature(raw, saleor_signature):
        raise HTTPException(status_code=401, detail="firma inválida")

    event = (saleor_event or "").lower()
    if event not in ORDER_EVENTS:
        return {"ignored": event}

    # TODO (fase OMS/Facturación): despachar a los reactores.
    #   order_created / order_updated → OMS (abastecimiento, OC)
    #   order_fully_paid             → Facturación SII (emitir DTE, folio → metadata)
    logger.info("evento de orden recibido: %s (pendiente de OMS/Facturación)", event)
    return {"accepted": event}
