"""Cliente GraphQL de Saleor para la app Ventu.

Un endpoint (`SALEOR_API_URL`) autenticado con el token de la Saleor App
(`Authorization: Bearer <token>`). Reintentos con backoff ante errores
transitorios (429/5xx/timeout). Los errores GraphQL a nivel documento
(`body["errors"]`) se devuelven en el resultado; es el llamador quien decide
si son transitorios o de validación.
"""

from __future__ import annotations

import logging
import random
import time
from typing import Any, Optional

import httpx

from . import config

logger = logging.getLogger("ventu.saleor")

DEFAULT_TIMEOUT = 45
MAX_RETRIES = 6
BACKOFF_BASE = 1.0
BACKOFF_JITTER = 0.4


class SaleorConfigError(RuntimeError):
    """Falta configuración de Saleor (URL o token)."""


class SaleorTransportError(RuntimeError):
    """Error transitorio de transporte tras agotar reintentos."""


def _backoff(attempt: int) -> float:
    return (BACKOFF_BASE * (2 ** (attempt - 1))) + (random.random() * BACKOFF_JITTER)


def gql(query: str, variables: Optional[dict] = None, *,
        timeout: int = DEFAULT_TIMEOUT) -> dict[str, Any]:
    """Ejecuta una operación GraphQL. Devuelve el cuerpo JSON completo
    (`{"data": {...}, "errors": [...]}`). Lanza SaleorTransportError si el
    transporte falla tras los reintentos."""
    if not config.SALEOR_API_URL:
        raise SaleorConfigError("SALEOR_API_URL no configurada")
    if not config.SALEOR_AUTH_TOKEN:
        raise SaleorConfigError("SALEOR_AUTH_TOKEN no configurado")

    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {config.SALEOR_AUTH_TOKEN}",
    }
    payload = {"query": query, "variables": variables or {}}

    last_exc: Exception | None = None
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            resp = httpx.post(config.SALEOR_API_URL, headers=headers,
                              json=payload, timeout=timeout)
            if resp.status_code in (429, 500, 502, 503, 504):
                raise SaleorTransportError(
                    f"transient {resp.status_code}: {resp.text[:200]}")
            resp.raise_for_status()
            return resp.json()
        except Exception as exc:  # noqa: BLE001 — transporte: reintentar
            last_exc = exc
            wait = _backoff(attempt)
            logger.warning("(saleor gql) retry %s/%s en %.2fs: %s",
                           attempt, MAX_RETRIES, wait, exc)
            time.sleep(wait)

    raise SaleorTransportError(str(last_exc) if last_exc else "gql failed")


def data_errors(body: dict) -> list:
    """Errores GraphQL a nivel transporte/documento."""
    return body.get("errors") or []


def payload(body: dict) -> dict:
    return body.get("data") or {}
