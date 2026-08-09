"""Cliente Webpay Plus (Transbank) — REST.

Cubre el flujo de Webpay Plus: create → (redirect) → commit → refund. Endpoints
y headers según la API REST de Transbank (v1.2). Por defecto usa el ambiente de
**integración** con las credenciales públicas de prueba (ver config).

    create → POST /rswebpaytransaction/api/webpay/v1.2/transactions
    commit → PUT  /rswebpaytransaction/api/webpay/v1.2/transactions/{token}
    refund → POST /rswebpaytransaction/api/webpay/v1.2/transactions/{token}/refunds
    status → GET  /rswebpaytransaction/api/webpay/v1.2/transactions/{token}
"""

from __future__ import annotations

import logging
from typing import Any

import httpx

from . import config

logger = logging.getLogger("ventu.pagos.webpay")

_PATH = "/rswebpaytransaction/api/webpay/v1.2/transactions"
DEFAULT_TIMEOUT = 30


def _headers() -> dict[str, str]:
    return {
        "Tbk-Api-Key-Id": config.WEBPAY_COMMERCE_CODE,
        "Tbk-Api-Key-Secret": config.WEBPAY_API_KEY,
        "Content-Type": "application/json",
    }


def _url(suffix: str = "") -> str:
    return f"{config.webpay_base_url()}{_PATH}{suffix}"


class WebpayError(RuntimeError):
    """Error devuelto por Transbank, con su mensaje incluido."""


def _check(resp: httpx.Response, op: str) -> Any:
    """Valida la respuesta conservando el motivo que da Transbank.

    `raise_for_status()` descarta el cuerpo, y Transbank explica ahí la causa
    real (p. ej. 422 "Invalid value for parameter: amount"). Sin ese detalle,
    diagnosticar un rechazo obliga a reproducir la llamada a mano.
    """
    if resp.status_code >= 400:
        try:
            detail = resp.json().get("error_message") or resp.text[:300]
        except Exception:  # noqa: BLE001 — cuerpo no-JSON
            detail = resp.text[:300]
        raise WebpayError(f"{op}: {resp.status_code} {detail}")
    return resp.json()


def create(*, buy_order: str, session_id: str, amount: int, return_url: str) -> dict[str, Any]:
    """Crea una transacción. Devuelve {token, url} para redirigir al tarjetahabiente."""
    payload = {
        "buy_order": buy_order,
        "session_id": session_id,
        "amount": int(amount),
        "return_url": return_url,
    }
    resp = httpx.post(_url(), headers=_headers(), json=payload, timeout=DEFAULT_TIMEOUT)
    return _check(resp, "create")  # {"token": "...", "url": "..."}


def commit(token: str) -> dict[str, Any]:
    """Confirma la transacción tras el retorno de Webpay. Devuelve estado final
    (status AUTHORIZED/FAILED, response_code, authorization_code, amount, …)."""
    resp = httpx.put(_url(f"/{token}"), headers=_headers(), timeout=DEFAULT_TIMEOUT)
    return _check(resp, "commit")


def status(token: str) -> dict[str, Any]:
    resp = httpx.get(_url(f"/{token}"), headers=_headers(), timeout=DEFAULT_TIMEOUT)
    return _check(resp, "status")


def refund(token: str, amount: int) -> dict[str, Any]:
    """Reembolso total o parcial (anulación si es el mismo día, reverse si no)."""
    resp = httpx.post(
        _url(f"/{token}/refunds"),
        headers=_headers(),
        json={"amount": int(amount)},
        timeout=DEFAULT_TIMEOUT,
    )
    return _check(resp, "refund")
