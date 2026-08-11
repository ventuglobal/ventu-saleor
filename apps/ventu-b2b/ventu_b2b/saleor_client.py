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


class SaleorQueryError(RuntimeError):
    """Error permanente de la petición (4xx salvo 429): no se reintenta."""


def _backoff(attempt: int) -> float:
    return (BACKOFF_BASE * (2 ** (attempt - 1))) + (random.random() * BACKOFF_JITTER)


def gql(query: str, variables: Optional[dict] = None, *,
        timeout: int = DEFAULT_TIMEOUT,
        token: Optional[str] = None) -> dict[str, Any]:
    """Ejecuta una operación GraphQL. Devuelve el cuerpo JSON completo
    (`{"data": {...}, "errors": [...]}`). Lanza SaleorTransportError si el
    transporte falla tras los reintentos.

    `token` firma la consulta con una credencial distinta a la de la app. Lo usa
    la lectura de la escalera de tramos: vive en la metadata privada del
    producto, que exige `MANAGE_PRODUCTS` —permiso de escritura sobre todo el
    catálogo que esta app no necesita para ninguna otra cosa—.
    """
    if not config.SALEOR_API_URL:
        raise SaleorConfigError("SALEOR_API_URL no configurada")
    auth = token or config.SALEOR_AUTH_TOKEN
    if not auth:
        raise SaleorConfigError("SALEOR_AUTH_TOKEN no configurado")

    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {auth}",
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
            # 4xx (salvo 429) es permanente: documento inválido, permisos, etc.
            # Reintentarlo no puede cambiar el resultado y bloquea al llamador
            # durante todo el backoff, así que se falla de inmediato.
            if 400 <= resp.status_code < 500:
                raise SaleorQueryError(
                    f"{resp.status_code}: {resp.text[:300]}")
            resp.raise_for_status()
            return resp.json()
        except SaleorQueryError:
            raise
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
