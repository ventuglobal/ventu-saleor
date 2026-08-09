"""Resolución del warehouse global "VENTU" (cache por-proceso)."""

from __future__ import annotations

import threading
from typing import Optional

from .. import config
from ..saleor_client import data_errors, gql, payload

_lock = threading.Lock()
_cache: dict[str, str] = {}

_WAREHOUSE_BY_SLUG = """
query($slug: String!) {
  warehouses(first: 1, filter: {slugs: [$slug]}) { edges { node { id } } }
}
"""


def warehouse_id() -> str:
    """gid del warehouse. Prefiere SALEOR_WAREHOUSE_ID; si no, resuelve por slug."""
    if config.SALEOR_WAREHOUSE_ID:
        return config.SALEOR_WAREHOUSE_ID

    slug = config.SALEOR_WAREHOUSE_SLUG
    with _lock:
        cached = _cache.get(slug)
    if cached:
        return cached

    body = gql(_WAREHOUSE_BY_SLUG, {"slug": slug})
    if data_errors(body):
        raise RuntimeError(f"warehouse lookup: {data_errors(body)}")
    edges = (payload(body).get("warehouses") or {}).get("edges") or []
    if not edges:
        raise RuntimeError(f"warehouse '{slug}' no existe en Saleor")
    wid = edges[0]["node"]["id"]
    with _lock:
        _cache[slug] = wid
    return wid


def channel_id(slug: str) -> Optional[str]:
    """gid de un channel por slug (cache). None si no existe."""
    key = f"channel:{slug}"
    with _lock:
        cached = _cache.get(key)
    if cached:
        return cached
    body = gql("query($slug: String!){ channel(slug:$slug){ id } }", {"slug": slug})
    if data_errors(body):
        raise RuntimeError(f"channel lookup: {data_errors(body)}")
    node = payload(body).get("channel")
    if not node:
        return None
    with _lock:
        _cache[key] = node["id"]
    return node["id"]
