"""Cliente GraphQL de Saleor para la App B2B.

Un endpoint (`SALEOR_API_URL`) autenticado con el token de la Saleor App
(`Authorization: Bearer <token>`). Los errores GraphQL a nivel documento
(`body["errors"]`) se devuelven en el resultado; es el llamador quien decide
si son transitorios o de validación.

**Reintentos.** Solo las lecturas se reintentan, y poco: el storefront corta a
los 8–20 s, así que un reintento que llega después de que el cliente se rindió
no sirve a nadie y sí mantiene ocupado un hilo. Las mutaciones no se reintentan
nunca: un timeout no dice si Saleor alcanzó a ejecutarla, y repetir
`orderCreateFromCheckout` puede crear dos pedidos por el mismo carrito.
"""

from __future__ import annotations

import logging
import random
import re
import time
from typing import Any, Optional

import httpx

from . import config

logger = logging.getLogger("ventu.saleor")

DEFAULT_TIMEOUT = 10
# Reintentos además del primer intento. Peor caso de una lectura: 3 intentos de
# 10 s más ~1 s de espera, dentro de lo que tolera el llamador más paciente.
MAX_RETRIES = 2
BACKOFF_BASE = 0.3
BACKOFF_JITTER = 0.2


class SaleorError(RuntimeError):
    """Cualquier fallo al hablar con Saleor. La app lo responde como 502."""


class SaleorConfigError(SaleorError):
    """Falta configuración de Saleor (URL o token)."""


class SaleorTransportError(SaleorError):
    """Error de transporte o de Saleor tras agotar los reintentos."""


class SaleorTimeoutError(SaleorTransportError):
    """Saleor no respondió a tiempo.

    Se distingue porque cambia lo que el llamador puede suponer: tras un error
    la operación no ocurrió, tras un timeout **quizás sí**. Se responde 504.
    """


class SaleorQueryError(SaleorError):
    """Error permanente de la petición (4xx salvo 429): no se reintenta."""


class SaleorRespuestaError(SaleorError):
    """Saleor respondió con `errors` a nivel documento (permisos, esquema)."""


_MUTACION = re.compile(r"^\s*mutation\b")


def _backoff(attempt: int) -> float:
    return (BACKOFF_BASE * (2 ** (attempt - 1))) + (random.random() * BACKOFF_JITTER)


def gql(query: str, variables: Optional[dict] = None, *,
        timeout: float = DEFAULT_TIMEOUT,
        token: Optional[str] = None,
        reintentar: Optional[bool] = None) -> dict[str, Any]:
    """Ejecuta una operación GraphQL. Devuelve el cuerpo JSON completo
    (`{"data": {...}, "errors": [...]}`).

    Lanza `SaleorTimeoutError` si Saleor no respondió a tiempo y
    `SaleorTransportError` ante cualquier otro fallo de transporte.

    `reintentar` por defecto es verdadero para consultas y falso para
    mutaciones: se deduce del documento para que una mutación nueva no nazca
    reintentable por olvido.

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

    if reintentar is None:
        reintentar = not _MUTACION.match(query)
    intentos = 1 + (MAX_RETRIES if reintentar else 0)

    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {auth}",
    }
    payload = {"query": query, "variables": variables or {}}

    ultimo: SaleorTransportError = SaleorTransportError("gql falló")
    for attempt in range(1, intentos + 1):
        try:
            resp = httpx.post(config.SALEOR_API_URL, headers=headers,
                              json=payload, timeout=timeout)
        except httpx.TimeoutException as exc:
            ultimo = SaleorTimeoutError(f"sin respuesta en {timeout}s: {exc}")
        except httpx.HTTPError as exc:
            ultimo = SaleorTransportError(f"transporte: {exc}")
        else:
            if resp.status_code == 504:
                ultimo = SaleorTimeoutError(f"504: {resp.text[:200]}")
            elif resp.status_code in (429, 500, 502, 503):
                ultimo = SaleorTransportError(
                    f"transitorio {resp.status_code}: {resp.text[:200]}")
            elif 400 <= resp.status_code < 500:
                # 4xx (salvo 429) es permanente: documento inválido, permisos,
                # etc. Reintentarlo no puede cambiar el resultado.
                raise SaleorQueryError(f"{resp.status_code}: {resp.text[:300]}")
            elif not resp.is_success:
                ultimo = SaleorTransportError(f"respuesta inesperada {resp.status_code}")
            else:
                try:
                    return resp.json()
                except ValueError as exc:
                    ultimo = SaleorTransportError(f"respuesta no es JSON: {exc}")

        if attempt < intentos:
            wait = _backoff(attempt)
            logger.warning("(saleor gql) reintento %s/%s en %.2fs: %s",
                           attempt, intentos - 1, wait, ultimo)
            time.sleep(wait)

    raise ultimo


def data_errors(body: dict) -> list:
    """Errores GraphQL a nivel transporte/documento."""
    return body.get("errors") or []


def payload(body: dict) -> dict:
    return body.get("data") or {}
