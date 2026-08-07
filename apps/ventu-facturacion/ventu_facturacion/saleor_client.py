"""Cliente Saleor mínimo: escribe el folio del DTE en la metadata de la orden."""

from __future__ import annotations

import logging
from typing import Any

import httpx

from . import config

logger = logging.getLogger("ventu.facturacion.saleor")

_UPDATE_METADATA = """
mutation($id: ID!, $input: [MetadataInput!]!) {
  updateMetadata(id: $id, input: $input) {
    errors { field message code }
  }
}
"""


def _gql(query: str, variables: dict) -> dict[str, Any]:
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {config.SALEOR_AUTH_TOKEN}",
    }
    resp = httpx.post(config.SALEOR_API_URL, headers=headers,
                      json={"query": query, "variables": variables}, timeout=30)
    resp.raise_for_status()
    return resp.json()


def write_dte_metadata(order_id: str, *, folio, status: str) -> None:
    """Estampa folio + estado del DTE en la orden (idempotencia + trazabilidad)."""
    from .handlers import DTE_STATUS_KEY, FOLIO_KEY
    inp = [{"key": DTE_STATUS_KEY, "value": str(status)}]
    if folio is not None:
        inp.append({"key": FOLIO_KEY, "value": str(folio)})
    body = _gql(_UPDATE_METADATA, {"id": order_id, "input": inp})
    errs = (((body.get("data") or {}).get("updateMetadata") or {}).get("errors")) or []
    if body.get("errors") or errs:
        logger.warning("updateMetadata order=%s errs=%s", order_id, body.get("errors") or errs)
