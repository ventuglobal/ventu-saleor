"""Resolución/creación de la categoría por defecto (cache por-proceso).

Saleor **exige categoría para publicar** un producto: sin ella,
`productChannelListingUpdate` responde `PRODUCT_WITHOUT_CATEGORY`. Como el
catálogo de Ventu aún no trae taxonomía propia, todo SKU creado por el
publisher cae en una categoría por defecto ("Ventu"), reemplazable más adelante
cuando se enriquezca el catálogo (marca/categoría real).

Mismo patrón que `product_type.py`: get-or-create idempotente con cache.
"""

from __future__ import annotations

import threading

from .. import config
from ..saleor_client import data_errors, gql, payload

_lock = threading.Lock()
_cache: dict[str, str] = {}

_BY_SLUG = """
query($slug: String!) {
  categories(first: 1, filter: {slugs: [$slug]}) { edges { node { id } } }
}
"""

_CREATE = """
mutation($input: CategoryInput!) {
  categoryCreate(input: $input) {
    category { id }
    errors { field message code }
  }
}
"""


def default_category_id() -> str:
    """gid de la categoría por defecto; la crea si no existe."""
    slug = config.DEFAULT_CATEGORY_SLUG
    with _lock:
        cached = _cache.get(slug)
    if cached:
        return cached

    body = gql(_BY_SLUG, {"slug": slug})
    if data_errors(body):
        raise RuntimeError(f"category lookup: {data_errors(body)}")
    edges = (payload(body).get("categories") or {}).get("edges") or []
    if edges:
        cid = edges[0]["node"]["id"]
    else:
        created = gql(_CREATE, {"input": {
            "name": config.DEFAULT_CATEGORY_NAME,
            "slug": slug,
        }})
        if data_errors(created):
            raise RuntimeError(f"category create: {data_errors(created)}")
        errs = (payload(created).get("categoryCreate") or {}).get("errors") or []
        if errs:
            raise RuntimeError(f"category create errors: {errs}")
        cid = ((payload(created).get("categoryCreate") or {}).get("category") or {}).get("id")
        if not cid:
            raise RuntimeError("category create: sin id")

    with _lock:
        _cache[slug] = cid
    return cid
