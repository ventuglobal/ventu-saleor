"""Ventu Sync App — el lado *entrante* de la sincronización (Saleor → Ventu).

Recibe los webhooks de Saleor y reenvía los eventos de orden al backend Ventu.
La sincronización *saliente* (catálogo/stock/precio Ventu → Saleor) NO vive aquí:
está en el backend Ventu (app `channel_sync`, propagador `saleor.py`).

Endpoints:
  - GET  /health           → liveness.
  - GET  /manifest         → manifest de Saleor App (para instalarla en Saleor).
  - POST /webhooks/saleor  → un único endpoint; el tipo viene en el header
                             `saleor-event`. Maneja ORDER_CREATED y
                             ORDER_FULLY_PAID reenviando a Ventu.

Skeleton intencional: la validación de firma HMAC y el mapeo exacto del payload
de orden → esquema de Ventu se completan al cablear contra el backend real.
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import os

import httpx
from fastapi import FastAPI, Header, HTTPException, Request

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("ventu-sync")

app = FastAPI(title="Ventu Sync App", version="0.1.0")

VENTU_API_URL = os.getenv("VENTU_API_URL", "").rstrip("/")
VENTU_API_TOKEN = os.getenv("VENTU_API_TOKEN", "")
WEBHOOK_SECRET = os.getenv("SALEOR_WEBHOOK_SECRET", "")

# Eventos de Saleor que reenviamos al backend Ventu.
FORWARDED_EVENTS = {"order_created", "order_fully_paid", "order_updated"}


@app.get("/health")
async def health() -> dict:
    return {"status": "ok"}


@app.post("/register")
async def register(request: Request) -> dict:
    """Recibe el `auth_token` que emite Saleor al instalar la App.

    Saleor hace POST aquí (tokenTargetUrl del manifest) con {"auth_token": "..."}.
    Ese token es el que usa el backend Ventu (SALEOR_AUTH_TOKEN) para la
    sincronización saliente.

    PENDIENTE: persistir el token de forma segura (secret manager / var de
    Railway). Por ahora se registra su recepción; NO se loguea el valor.
    """
    body = await request.json()
    token = body.get("auth_token")
    if not token:
        raise HTTPException(status_code=400, detail="falta auth_token")
    logger.info("Saleor App registrada; auth_token recibido (len=%d)", len(token))
    # TODO: guardar `token` en el store de secretos y propagarlo al backend Ventu.
    return {"status": "ok"}


@app.get("/manifest")
async def manifest(request: Request) -> dict:
    """Manifest mínimo para registrar esta App en Saleor (Extensiones → Add)."""
    base = str(request.base_url).rstrip("/")
    return {
        "id": "cl.ventu.sync",
        "version": "0.1.0",
        "name": "Ventu Sync",
        "about": "Reenvía órdenes de Saleor al backend Ventu.",
        "permissions": ["MANAGE_ORDERS", "MANAGE_PRODUCTS"],
        "appUrl": base,
        "tokenTargetUrl": f"{base}/register",
        "webhooks": [
            {
                "name": "Ventu order events",
                "targetUrl": f"{base}/webhooks/saleor",
                "syncEvents": [],
                "asyncEvents": ["ORDER_CREATED", "ORDER_FULLY_PAID", "ORDER_UPDATED"],
                "isActive": True,
            }
        ],
    }


def _verify_signature(raw_body: bytes, signature: str | None) -> bool:
    """HMAC-SHA256 del cuerpo con el secreto compartido (header saleor-signature).

    Si no hay secreto configurado, no se valida (útil en dev). En producción
    SIEMPRE configurá SALEOR_WEBHOOK_SECRET.
    """
    if not WEBHOOK_SECRET:
        return True
    if not signature:
        return False
    expected = hmac.new(WEBHOOK_SECRET.encode(), raw_body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature)


async def _forward_to_ventu(event: str, payload: dict) -> None:
    """Reenvía el evento al backend Ventu. Idempotencia: Ventu deduplica por
    el id de la orden de Saleor (implementar del lado Ventu)."""
    if not VENTU_API_URL:
        logger.warning("VENTU_API_URL no configurada; evento %s no reenviado", event)
        return
    url = f"{VENTU_API_URL}/saleor/orders/"
    headers = {"Authorization": f"Bearer {VENTU_API_TOKEN}", "X-Saleor-Event": event}
    async with httpx.AsyncClient(timeout=20) as client:
        resp = await client.post(url, json={"event": event, "data": payload}, headers=headers)
        resp.raise_for_status()
    logger.info("evento %s reenviado a Ventu (%s)", event, resp.status_code)


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
    if event not in FORWARDED_EVENTS:
        # No es un evento que nos interese; ack silencioso (Saleor no reintenta).
        return {"ignored": event}

    payload = await request.json()
    await _forward_to_ventu(event, payload)
    return {"forwarded": event}
