"""Cliente GraphQL mínimo hacia Saleor.

Se usa en el camino **asíncrono**: el reconciliador (cuando el navegador no volvió
y no hay webhook vivo al cual responder) y la escritura de metadata de la orden.
El camino feliz reporta el resultado en la respuesta síncrona del webhook, así que
no necesita estas mutations.

Auth: `Authorization: Bearer <auth_token>` con el token que la App recibió al
instalarse (persistido en app_config por `/register`).
"""

from __future__ import annotations

import logging
from typing import Any

import httpx

from . import config, store

logger = logging.getLogger("ventu.pagos.saleor")

DEFAULT_TIMEOUT = 20

_EVENT_REPORT = """
mutation VentuTxReport(
  $id: ID!, $type: TransactionEventTypeEnum!, $amount: PositiveDecimal!,
  $pspReference: String!, $time: DateTime, $message: String
) {
  transactionEventReport(
    id: $id, type: $type, amount: $amount, pspReference: $pspReference,
    time: $time, message: $message
  ) {
    alreadyProcessed
    transactionEvent { id }
    errors { field code message }
  }
}
"""

_UPDATE_METADATA = """
mutation VentuTxMeta($id: ID!, $input: [MetadataInput!]!) {
  updateMetadata(id: $id, input: $input) {
    errors { field code message }
  }
}
"""


def _api_url() -> str:
    return (store.get_config("saleor_api_url") or config.SALEOR_API_URL or "").strip()


def _auth_token() -> str:
    return (store.get_config("auth_token") or "").strip()


def _execute(query: str, variables: dict[str, Any]) -> dict[str, Any] | None:
    url = _api_url()
    token = _auth_token()
    if not url or not token:
        logger.warning("Saleor no configurado (url/token ausente); se omite %s", query.split("(")[0])
        return None
    try:
        resp = httpx.post(
            url,
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
            json={"query": query, "variables": variables},
            timeout=DEFAULT_TIMEOUT,
        )
        resp.raise_for_status()
        body = resp.json()
    except Exception as exc:  # noqa: BLE001
        logger.warning("fallo llamando a Saleor: %s", exc)
        return None
    if body.get("errors"):
        logger.warning("Saleor devolvió errores: %s", body["errors"])
    return body.get("data")


def report_transaction_event(
    *,
    transaction_id: str,
    event_type: str,
    amount,
    psp_reference: str,
    message: str | None = None,
    time: str | None = None,
) -> dict[str, Any] | None:
    """`transactionEventReport`: reporta un resultado fuera de la respuesta sync."""
    return _execute(
        _EVENT_REPORT,
        {
            "id": transaction_id,
            "type": event_type,
            "amount": amount,
            "pspReference": psp_reference,
            "message": (message or "")[:512] or None,
            "time": time,
        },
    )


def update_metadata(*, object_id: str, items: dict[str, Any]) -> dict[str, Any] | None:
    """Escribe metadata en un objeto de Saleor (transacción u orden)."""
    inp = [{"key": k, "value": str(v)} for k, v in items.items() if v is not None]
    if not inp:
        return None
    return _execute(_UPDATE_METADATA, {"id": object_id, "input": inp})
