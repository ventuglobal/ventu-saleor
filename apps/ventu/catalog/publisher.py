"""Publicador de catálogo → Saleor.

Empuja el estado deseado de una variante (identificada por SKU) a Saleor:
  1. Stock en el warehouse VENTU: quantity = available_deseado + allocated_actual
     (absoluto e idempotente; evita el "efecto serrucho" con órdenes en curso).
  2. Precio por channel (el precio final ya calculado por Pricing).
  3. Publicación del producto en el channel (idempotente; MVP: siempre publicado).

Identidad: la variante se resuelve por `externalReference` (el SKU que la App
Ventu controla) y, como respaldo, por el campo `sku` nativo de Saleor.

Creación de producto/variante (para SKUs que aún no existen en Saleor) requiere
el mapeo de tipos de producto y atributos del catálogo normalizado — es el
próximo incremento. Hoy el publicador opera sobre variantes existentes y reporta
`no encontrado` para las que faltan (las recoge el reconciler / la creación).
"""

from __future__ import annotations

import logging
from typing import Iterable, List, Optional

from ..saleor_client import data_errors, gql, payload
from . import warehouse
from .models import PublishResult, VariantInput

logger = logging.getLogger("ventu.catalog")

_VARIANT_BY_SKU = """
query($sku: String!) {
  productVariant(sku: $sku) {
    id
    product { id }
    stocks { quantity quantityAllocated warehouse { id } }
  }
}
"""

_STOCKS_UPDATE = """
mutation($variantId: ID!, $stocks: [StockInput!]!) {
  productVariantStocksUpdate(variantId: $variantId, stocks: $stocks) {
    errors { field message code }
  }
}
"""

_STOCKS_CREATE = """
mutation($variantId: ID!, $stocks: [StockInput!]!) {
  productVariantStocksCreate(variantId: $variantId, stocks: $stocks) {
    errors { field message code }
  }
}
"""

_VARIANT_CHANNEL_LISTING = """
mutation($id: ID!, $input: [ProductVariantChannelListingAddInput!]!) {
  productVariantChannelListingUpdate(id: $id, input: $input) {
    errors { field message code }
  }
}
"""

_PRODUCT_CHANNEL_LISTING = """
mutation($id: ID!, $channelId: ID!) {
  productChannelListingUpdate(
    id: $id
    input: {updateChannels: [{channelId: $channelId, isPublished: true, isAvailableForPurchase: true}]}
  ) {
    errors { field message code }
  }
}
"""


def _mutation_errors(body: dict, name: str) -> list:
    return (payload(body).get(name) or {}).get("errors") or []


def _resolve(sku: str) -> Optional[dict]:
    body = gql(_VARIANT_BY_SKU, {"sku": sku})
    if data_errors(body):
        raise RuntimeError(f"lookup errors: {data_errors(body)}")
    return payload(body).get("productVariant")


def _set_stock(variant_id: str, wh_id: str, target: int, *, exists: bool) -> list:
    query = _STOCKS_UPDATE if exists else _STOCKS_CREATE
    name = "productVariantStocksUpdate" if exists else "productVariantStocksCreate"
    body = gql(query, {"variantId": variant_id,
                       "stocks": [{"warehouse": wh_id, "quantity": int(target)}]})
    if data_errors(body):
        raise RuntimeError(f"stock errors: {data_errors(body)}")
    return _mutation_errors(body, name)


def _set_price(variant_id: str, channel_id: str, amount: float) -> list:
    body = gql(_VARIANT_CHANNEL_LISTING, {
        "id": variant_id,
        "input": [{"channelId": channel_id, "price": amount}],
    })
    if data_errors(body):
        raise RuntimeError(f"price errors: {data_errors(body)}")
    return _mutation_errors(body, "productVariantChannelListingUpdate")


def _ensure_published(product_id: str, channel_id: str) -> list:
    body = gql(_PRODUCT_CHANNEL_LISTING, {"id": product_id, "channelId": channel_id})
    if data_errors(body):
        raise RuntimeError(f"publish errors: {data_errors(body)}")
    return _mutation_errors(body, "productChannelListingUpdate")


def publish_variant(item: VariantInput) -> PublishResult:
    """Publica stock + precios + visibilidad de una variante existente en Saleor."""
    from .. import config

    node = _resolve(item.sku)
    if not node or not node.get("id"):
        return PublishResult(item.sku, ok=False, detail="variante no encontrada en Saleor")
    variant_id = node["id"]
    product_id = (node.get("product") or {}).get("id")

    # ── stock: quantity = available_deseado + allocated_actual ──
    wh_id = warehouse.warehouse_id()
    current = next((s for s in (node.get("stocks") or [])
                    if (s.get("warehouse") or {}).get("id") == wh_id), None)
    allocated = int((current or {}).get("quantityAllocated") or 0)
    target = item.available + allocated
    errs = _set_stock(variant_id, wh_id, target, exists=current is not None)
    if errs:
        return PublishResult(item.sku, ok=False, detail=f"stock: {errs}")

    # ── precios por channel ──
    for price in item.prices:
        cid = warehouse.channel_id(price.channel_slug)
        if not cid:
            return PublishResult(item.sku, ok=False,
                                 detail=f"channel '{price.channel_slug}' no existe")
        errs = _set_price(variant_id, cid, price.amount)
        if errs:
            return PublishResult(item.sku, ok=False, detail=f"precio: {errs}")

    # ── visibilidad (idempotente) ──
    if config.ENSURE_PUBLISHED and product_id:
        for price in item.prices:
            cid = warehouse.channel_id(price.channel_slug)
            if cid:
                errs = _ensure_published(product_id, cid)
                if errs:
                    return PublishResult(item.sku, ok=False, detail=f"publish: {errs}")

    return PublishResult(item.sku, ok=True, detail="ok", stock_set=target)


def publish_batch(items: Iterable[VariantInput]) -> List[PublishResult]:
    results: List[PublishResult] = []
    for item in items:
        try:
            results.append(publish_variant(item))
        except Exception as exc:  # noqa: BLE001
            logger.warning("(catalog) publish sku=%s error: %s", item.sku, exc)
            results.append(PublishResult(item.sku, ok=False, detail=f"error: {exc}"))
    return results
