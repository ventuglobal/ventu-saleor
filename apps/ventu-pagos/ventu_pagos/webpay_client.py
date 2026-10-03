"""Cliente Webpay Plus (Transbank) — REST v1.2.

Cubre el flujo de Webpay Plus: create → (redirect) → commit → refund, más status
para recuperarse de errores. Por defecto usa el ambiente de **integración** con
las credenciales públicas de prueba (ver config).

    create → POST /rswebpaytransaction/api/webpay/v1.2/transactions
    commit → PUT  /rswebpaytransaction/api/webpay/v1.2/transactions/{token}
    status → GET  /rswebpaytransaction/api/webpay/v1.2/transactions/{token}
    refund → POST /rswebpaytransaction/api/webpay/v1.2/transactions/{token}/refunds

Transbank responde los errores con cuerpo {"error_message": ...} y códigos HTTP
400/401/404/422/500. Se encapsulan en `WebpayError` para no filtrar la llave.
"""

from __future__ import annotations

import logging
from typing import Any

import httpx

from . import config

logger = logging.getLogger("ventu.pagos.webpay")

_PATH = "/rswebpaytransaction/api/webpay/v1.2/transactions"
DEFAULT_TIMEOUT = 30


class WebpayError(Exception):
    """Error de la API de Transbank (HTTP != 2xx o fallo de red)."""

    def __init__(self, message: str, *, status_code: int | None = None):
        super().__init__(message)
        self.status_code = status_code


def _headers() -> dict[str, str]:
    return {
        "Tbk-Api-Key-Id": config.WEBPAY_COMMERCE_CODE,
        "Tbk-Api-Key-Secret": config.WEBPAY_API_KEY,
        "Content-Type": "application/json",
    }


def _url(suffix: str = "") -> str:
    return f"{config.webpay_base_url()}{_PATH}{suffix}"


def _request(method: str, suffix: str, *, json: dict | None = None) -> dict[str, Any]:
    try:
        resp = httpx.request(
            method, _url(suffix), headers=_headers(), json=json, timeout=DEFAULT_TIMEOUT
        )
    except httpx.HTTPError as exc:  # red/timeout: resultado desconocido
        raise WebpayError(f"fallo de red con Transbank: {exc}") from exc
    if resp.status_code >= 400:
        detail = ""
        try:
            detail = str(resp.json().get("error_message", ""))
        except Exception:  # noqa: BLE001
            detail = resp.text[:200]
        raise WebpayError(
            f"Transbank {resp.status_code}: {detail}", status_code=resp.status_code
        )
    return resp.json()


def create(*, buy_order: str, session_id: str, amount: int, return_url: str) -> dict[str, Any]:
    """Crea una transacción. Devuelve {token, url} para redirigir al tarjetahabiente."""
    return _request(
        "POST",
        "",
        json={
            "buy_order": buy_order,
            "session_id": session_id,
            "amount": int(amount),
            "return_url": return_url,
        },
    )


def commit(token: str) -> dict[str, Any]:
    """Confirma la transacción tras el retorno de Webpay. Devuelve estado final
    (status AUTHORIZED/FAILED, response_code, authorization_code, amount, …)."""
    return _request("PUT", f"/{token}")


def status(token: str) -> dict[str, Any]:
    """Consulta el estado de una transacción (recuperación ante errores)."""
    return _request("GET", f"/{token}")


def refund(token: str, amount: int) -> dict[str, Any]:
    """Reembolso total o parcial (REVERSED el mismo día, NULLIFIED después)."""
    return _request("POST", f"/{token}/refunds", json={"amount": int(amount)})
