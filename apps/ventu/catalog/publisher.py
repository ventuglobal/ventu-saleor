"""Publicador de catálogo → Saleor.

Empuja el estado deseado de una variante (identificada por SKU) a Saleor:
  1. Stock en el warehouse VENTU: quantity = available_deseado + allocated_actual
     (absoluto e idempotente; evita el "efecto serrucho" con órdenes en curso).
  2. Precio por channel (el precio final ya calculado por Pricing).
  3. Publicación del producto en el channel (idempotente; MVP: siempre publicado).

Identidad: la variante se resuelve por SKU; al crear, se fija además el
`externalReference` = SKU (la clave estable que la App Ventu controla) tanto en
el producto como en la variante.

Si el SKU no existe y `SALEOR_CREATE_MISSING` está activo, se **crea** un
producto simple (ProductType por defecto "Ventu Default") con una variante, y
luego se publica stock/precio como en el caso de actualización. Atributos ricos
del catálogo normalizado (marca, categoría) se agregan en un incremento
posterior.
"""

from __future__ import annotations

import logging
from typing import Iterable, List, Optional
from urllib.parse import urljoin

import httpx

from .. import config
from ..saleor_client import data_errors, gql, payload
from . import category, product_type, warehouse
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
mutation($id: ID!, $channelId: ID!, $isPublished: Boolean!) {
  productChannelListingUpdate(
    id: $id
    input: {updateChannels: [{
      channelId: $channelId
      isPublished: $isPublished
      isAvailableForPurchase: $isPublished
      visibleInListings: $isPublished
    }]}
  ) {
    errors { field message code }
  }
}
"""

_PRODUCT_CREATE = """
mutation($input: ProductCreateInput!) {
  productCreate(input: $input) {
    product { id }
    errors { field message code }
  }
}
"""

_VARIANT_CREATE = """
mutation($input: ProductVariantCreateInput!) {
  productVariantCreate(input: $input) {
    productVariant { id product { id } }
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


def _create(item: VariantInput) -> dict:
    """Crea un producto simple + su variante para un SKU que no existe en Saleor.

    Devuelve un nodo con la misma forma que `_resolve` (id, product{id},
    stocks:[]) para que el flujo posterior (stock/precio/publicación) sea
    uniforme. La variante recién creada no tiene stock aún → ruta create.
    """
    pt_id = product_type.default_product_type_id()
    name = item.name or item.sku

    prod = gql(_PRODUCT_CREATE, {"input": {
        "name": name,
        "productType": pt_id,
        # Sin categoría Saleor rechaza la publicación (PRODUCT_WITHOUT_CATEGORY).
        "category": category.default_category_id(),
        "externalReference": item.sku,
        **({"description": item.description} if item.description else {}),
    }})
    if data_errors(prod):
        raise RuntimeError(f"product create: {data_errors(prod)}")
    perrs = (payload(prod).get("productCreate") or {}).get("errors") or []
    if perrs:
        raise RuntimeError(f"product create errors: {perrs}")
    product_id = ((payload(prod).get("productCreate") or {}).get("product") or {}).get("id")
    if not product_id:
        raise RuntimeError("product create: sin id")

    var = gql(_VARIANT_CREATE, {"input": {
        "product": product_id,
        "sku": item.sku,
        "name": name,
        "externalReference": item.sku,
        "trackInventory": True,
        "attributes": [],
    }})
    if data_errors(var):
        raise RuntimeError(f"variant create: {data_errors(var)}")
    verrs = (payload(var).get("productVariantCreate") or {}).get("errors") or []
    if verrs:
        raise RuntimeError(f"variant create errors: {verrs}")
    node = (payload(var).get("productVariantCreate") or {}).get("productVariant")
    if not node or not node.get("id"):
        raise RuntimeError("variant create: sin id")
    node.setdefault("stocks", [])
    return node


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


# `ProductMedia` no expone la URL de origen en la API, así que la guardamos en
# su metadata (modelo de extensión de Saleor) para poder ser idempotentes.
MEDIA_SRC_KEY = "ventu.media.src"

_PRODUCT_MEDIA = """
query($id: ID!, $key: String!) {
  product(id: $id) { media { id metafield(key: $key) } }
}
"""

_MEDIA_CREATE = """
mutation($product: ID!, $url: String!, $alt: String) {
  productMediaCreate(input: {product: $product, mediaUrl: $url, alt: $alt}) {
    media { id }
    errors { field message code }
  }
}
"""

_MEDIA_TAG = """
mutation($id: ID!, $input: [MetadataInput!]!) {
  updateMetadata(id: $id, input: $input) {
    errors { field message code }
  }
}
"""


def _warm_thumbnails(media_ids: list) -> None:
    """Fuerza la generación de las miniaturas recién creadas.

    Saleor las genera de forma perezosa: hasta la primera petición a
    `/thumbnail/<id>/<size>/` no existen en el storage, y mientras tanto la API
    devuelve su propia URL en vez de la del CDN. Calentarlas al publicar hace
    que la primera visita del comprador ya se sirva directo desde el object
    storage, sin pasar por la API.

    Best-effort: cualquier fallo aquí es irrelevante para la venta (la miniatura
    se generará igual en la primera visita), así que nunca propaga excepciones.
    """
    sizes = config.THUMBNAIL_WARM_SIZES
    if not sizes or not media_ids:
        return
    formats = config.THUMBNAIL_WARM_FORMATS or [""]
    base = urljoin(config.SALEOR_API_URL, "/")
    try:
        with httpx.Client(timeout=30, follow_redirects=False) as client:
            for mid in media_ids:
                for size in sizes:
                    for fmt in formats:
                        suffix = f"{fmt}/" if fmt else ""
                        try:
                            client.get(f"{base}thumbnail/{mid}/{size}/{suffix}")
                        except Exception as exc:  # noqa: BLE001
                            logger.debug("warm thumbnail %s/%s/%s: %s",
                                         mid, size, fmt or "orig", exc)
    except Exception as exc:  # noqa: BLE001
        logger.debug("warm thumbnails: %s", exc)


def _publish_images(product_id: str, urls: list, alt: str) -> list:
    """Adjunta las fotos al producto, sin duplicar las que ya están.

    Idempotente por `externalUrl`: Saleor guarda la URL de origen, así que al
    republicar un SKU solo se crean las fotos nuevas. Saleor descarga la imagen
    de forma asíncrona (tarea Celery), por lo que api y worker necesitan
    compartir storage (S3/R2) para que la foto sea servible.
    """
    body = gql(_PRODUCT_MEDIA, {"id": product_id, "key": MEDIA_SRC_KEY})
    if data_errors(body):
        raise RuntimeError(f"media lookup: {data_errors(body)}")
    existing = {m.get("metafield")
                for m in ((payload(body).get("product") or {}).get("media") or [])
                if m.get("metafield")}
    errs: list = []
    nuevas: list = []
    for url in urls:
        if url in existing:
            continue
        created = gql(_MEDIA_CREATE, {"product": product_id, "url": url, "alt": alt})
        if data_errors(created):
            raise RuntimeError(f"media create: {data_errors(created)}")
        errs += (payload(created).get("productMediaCreate") or {}).get("errors") or []
        media_id = ((payload(created).get("productMediaCreate") or {})
                    .get("media") or {}).get("id")
        if media_id:
            nuevas.append(media_id)
            # Marca la foto con su URL de origen para no recrearla al republicar.
            tagged = gql(_MEDIA_TAG, {"id": media_id,
                                      "input": [{"key": MEDIA_SRC_KEY, "value": url}]})
            if data_errors(tagged):
                raise RuntimeError(f"media tag: {data_errors(tagged)}")
            errs += (payload(tagged).get("updateMetadata") or {}).get("errors") or []
    _warm_thumbnails(nuevas)
    return errs


def _ensure_published(product_id: str, channel_id: str, *, published: bool = True) -> list:
    """Asigna el producto al channel. `published` controla la visibilidad; la
    asignación se hace igual porque es prerequisito del precio de la variante.

    `visibleInListings` es un flag **aparte** de `isPublished` y por defecto es
    False: sin él el producto es comprable por link directo pero no aparece en
    listados ni búsqueda del storefront (vitrina vacía).
    """
    body = gql(_PRODUCT_CHANNEL_LISTING, {
        "id": product_id, "channelId": channel_id, "isPublished": published,
    })
    if data_errors(body):
        raise RuntimeError(f"publish errors: {data_errors(body)}")
    return _mutation_errors(body, "productChannelListingUpdate")


def publish_variant(item: VariantInput) -> PublishResult:
    """Publica una variante a Saleor: la crea si no existe, luego fija stock +
    precios + visibilidad. Idempotente (resuelve por SKU antes de crear)."""

    created = False
    node = _resolve(item.sku)
    if not node or not node.get("id"):
        if not config.CREATE_MISSING:
            return PublishResult(item.sku, ok=False, detail="variante no encontrada en Saleor")
        node = _create(item)
        created = True
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

    # ── channel listing del producto ANTES del precio: Saleor rechaza el precio
    # de una variante cuyo producto no está asignado al channel
    # (PRODUCT_NOT_ASSIGNED_TO_CHANNEL). La asignación es prerequisito; la
    # visibilidad la sigue gobernando ENSURE_PUBLISHED.
    if product_id:
        for price in item.prices:
            cid = warehouse.channel_id(price.channel_slug)
            if cid:
                errs = _ensure_published(product_id, cid,
                                         published=config.ENSURE_PUBLISHED)
                if errs:
                    return PublishResult(item.sku, ok=False, detail=f"publish: {errs}")

    # ── precios por channel ──
    for price in item.prices:
        cid = warehouse.channel_id(price.channel_slug)
        if not cid:
            return PublishResult(item.sku, ok=False,
                                 detail=f"channel '{price.channel_slug}' no existe")
        errs = _set_price(variant_id, cid, price.amount)
        if errs:
            return PublishResult(item.sku, ok=False, detail=f"precio: {errs}")

    # ── fotos (no bloqueantes) ──
    # Una foto que falle no debe impedir vender: el SKU ya quedó con stock,
    # precio y visibilidad. Se reporta en el detalle para no perder la señal.
    img_note = ""
    if item.images and product_id:
        try:
            ierrs = _publish_images(product_id, item.images, item.name or item.sku)
            if ierrs:
                img_note = f" (fotos: {ierrs})"
        except Exception as exc:  # noqa: BLE001
            logger.warning("fotos de %s: %s", item.sku, exc)
            img_note = f" (fotos: {exc})"

    return PublishResult(item.sku, ok=True,
                         detail=("created" if created else "updated") + img_note,
                         stock_set=target, created=created)


def publish_prices(sku: str, prices) -> PublishResult:
    """Escribe SOLO precios por channel de una variante existente (sin stock ni
    creación). Es el writer que usa el módulo Pricing tras computar el precio.
    `prices` es un iterable de objetos con `.channel_slug` y `.amount`."""
    node = _resolve(sku)
    if not node or not node.get("id"):
        return PublishResult(sku, ok=False, detail="variante no encontrada en Saleor")
    variant_id = node["id"]

    for price in prices:
        cid = warehouse.channel_id(price.channel_slug)
        if not cid:
            return PublishResult(sku, ok=False, detail=f"channel '{price.channel_slug}' no existe")
        errs = _set_price(variant_id, cid, price.amount)
        if errs:
            return PublishResult(sku, ok=False, detail=f"precio: {errs}")
    return PublishResult(sku, ok=True, detail="prices")


def publish_batch(items: Iterable[VariantInput]) -> List[PublishResult]:
    results: List[PublishResult] = []
    for item in items:
        try:
            results.append(publish_variant(item))
        except Exception as exc:  # noqa: BLE001
            logger.warning("(catalog) publish sku=%s error: %s", item.sku, exc)
            results.append(PublishResult(item.sku, ok=False, detail=f"error: {exc}"))
    return results
