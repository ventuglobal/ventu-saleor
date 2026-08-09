"""Resolución/creación del ProductType por defecto (cache por-proceso).

Cada SKU de Ventu se modela como un **producto simple** con una variante. Todos
comparten un ProductType por defecto ("Ventu Default"): normal, con envío
requerido y sin atributos de variante (la variante se identifica por SKU). Si el
catálogo normalizado necesita atributos (marca, etc.) se agregan en un
incremento posterior.
"""

from __future__ import annotations

import threading
from typing import Optional

from .. import config
from ..saleor_client import data_errors, gql, payload

_lock = threading.Lock()
_cache: dict[str, str] = {}

_BY_SLUG = """
query($slug: String!) {
  productTypes(first: 1, filter: {slugs: [$slug]}) { edges { node { id } } }
}
"""

_CREATE = """
mutation($input: ProductTypeInput!) {
  productTypeCreate(input: $input) {
    productType { id }
    errors { field message code }
  }
}
"""


def default_product_type_id() -> str:
    """gid del ProductType por defecto; lo crea si no existe."""
    slug = config.DEFAULT_PRODUCT_TYPE_SLUG
    with _lock:
        cached = _cache.get(slug)
    if cached:
        return cached

    body = gql(_BY_SLUG, {"slug": slug})
    if data_errors(body):
        raise RuntimeError(f"product type lookup: {data_errors(body)}")
    edges = (payload(body).get("productTypes") or {}).get("edges") or []
    if edges:
        ptid = edges[0]["node"]["id"]
    else:
        created = gql(_CREATE, {"input": {
            "name": config.DEFAULT_PRODUCT_TYPE_NAME,
            "slug": slug,
            "kind": "NORMAL",
            "hasVariants": False,
            "isShippingRequired": True,
        }})
        if data_errors(created):
            raise RuntimeError(f"product type create: {data_errors(created)}")
        errs = (payload(created).get("productTypeCreate") or {}).get("errors") or []
        if errs:
            raise RuntimeError(f"product type create errors: {errs}")
        ptid = ((payload(created).get("productTypeCreate") or {}).get("productType") or {}).get("id")
        if not ptid:
            raise RuntimeError("product type create: sin id")

    with _lock:
        _cache[slug] = ptid
    return ptid
