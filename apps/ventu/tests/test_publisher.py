"""Test del publicador de catálogo: quantity = available + allocated."""

from __future__ import annotations

import pytest

from ventu import config
from ventu.catalog import publisher
from ventu.catalog.models import ChannelPrice, VariantInput


def _variant(allocated=0, wh="WH", vid="V1", pid="P1"):
    stocks = [] if wh is None else [
        {"quantity": 100, "quantityAllocated": allocated, "warehouse": {"id": wh}}]
    node = None if vid is None else {"id": vid, "product": {"id": pid}, "stocks": stocks}
    return {"data": {"productVariant": node}}


def _mut_ok(name):
    return {"data": {name: {"errors": []}}}


@pytest.fixture(autouse=True)
def _cfg(monkeypatch):
    # Warehouse fijo (corta el lookup), sin publicación (aísla el stock) y sin
    # creación por defecto (cada test que la ejercita la activa explícitamente).
    monkeypatch.setattr(config, "SALEOR_WAREHOUSE_ID", "WH")
    monkeypatch.setattr(config, "ENSURE_PUBLISHED", False)
    monkeypatch.setattr(config, "CREATE_MISSING", False)


def _router(responses):
    def _fn(query, variables=None, **kw):
        if "productVariant(sku" in query:
            return responses["lookup"]
        if "productVariantStocksUpdate" in query:
            return responses.get("update", _mut_ok("productVariantStocksUpdate"))
        if "productVariantStocksCreate" in query:
            return responses.get("create", _mut_ok("productVariantStocksCreate"))
        if "productVariantChannelListingUpdate" in query:
            return _mut_ok("productVariantChannelListingUpdate")
        raise AssertionError(f"query inesperada: {query[:40]}")
    return _fn


def test_quantity_target_adds_allocated(monkeypatch):
    calls = []

    def spy(query, variables=None, **kw):
        calls.append((query, variables))
        return _router({"lookup": _variant(allocated=5)})(query, variables, **kw)

    monkeypatch.setattr(publisher, "gql", spy)
    res = publisher.publish_variant(VariantInput(sku="ABC", available=40))
    assert res.ok and res.stock_set == 45  # 40 + allocated(5)
    sent = next(v["stocks"][0]["quantity"] for q, v in calls if "Stocks" in q)
    assert sent == 45


def test_create_path_when_no_stock(monkeypatch):
    monkeypatch.setattr(publisher, "gql", _router({"lookup": _variant(wh=None)}))
    res = publisher.publish_variant(VariantInput(sku="ABC", available=40))
    assert res.ok and res.stock_set == 40


def test_mutation_errors_are_failure(monkeypatch):
    bad = {"data": {"productVariantStocksUpdate": {
        "errors": [{"field": "quantity", "message": "bad", "code": "INVALID"}]}}}
    monkeypatch.setattr(publisher, "gql",
                        _router({"lookup": _variant(allocated=0), "update": bad}))
    res = publisher.publish_variant(VariantInput(sku="ABC", available=40))
    assert not res.ok


def test_creates_missing_variant(monkeypatch):
    """SKU inexistente + CREATE_MISSING → crea producto+variante y publica stock."""
    monkeypatch.setattr(config, "CREATE_MISSING", True)
    monkeypatch.setattr(publisher.product_type, "default_product_type_id", lambda: "PT1")
    monkeypatch.setattr(publisher.category, "default_category_id", lambda: "CAT1")
    seen = []

    created_input = {}

    def router(query, variables=None, **kw):
        seen.append(query)
        if "productVariant(sku" in query:
            return _variant(vid=None)                 # no existe
        if "productCreate" in query:
            created_input.update((variables or {}).get("input") or {})
            return {"data": {"productCreate": {"product": {"id": "P9"}, "errors": []}}}
        if "productVariantCreate" in query:
            return {"data": {"productVariantCreate": {
                "productVariant": {"id": "V9", "product": {"id": "P9"}}, "errors": []}}}
        if "productVariantStocksCreate" in query:
            return _mut_ok("productVariantStocksCreate")
        raise AssertionError(f"query inesperada: {query[:40]}")

    monkeypatch.setattr(publisher, "gql", router)
    res = publisher.publish_variant(VariantInput(sku="NEW-1", available=7, name="Router X"))
    assert res.ok and res.created and res.stock_set == 7
    assert any("productCreate" in q for q in seen)
    assert any("productVariantCreate" in q for q in seen)
    # Sin categoría Saleor rechaza publicar el producto (PRODUCT_WITHOUT_CATEGORY).
    assert created_input.get("category") == "CAT1"


def test_create_disabled_reports_not_found(monkeypatch):
    monkeypatch.setattr(config, "CREATE_MISSING", False)
    monkeypatch.setattr(publisher, "gql", _router({"lookup": _variant(vid=None)}))
    res = publisher.publish_variant(VariantInput(sku="NOPE", available=1))
    assert not res.ok and not res.created


def test_channel_listing_sets_visible_in_listings(monkeypatch):
    """Publicar debe marcar visibleInListings, no solo isPublished.

    Son flags independientes en Saleor: sin visibleInListings el producto es
    comprable por link directo pero no aparece en listados ni búsqueda, así que
    el storefront muestra la vitrina vacía.
    """
    monkeypatch.setattr(config, "ENSURE_PUBLISHED", True)
    monkeypatch.setattr(publisher.warehouse, "channel_id", lambda slug: "CH1")
    listing = {}

    def router(query, variables=None, **kw):
        if "productVariant(sku" in query:
            return _variant(allocated=0)
        if "productVariantStocksUpdate" in query:
            return _mut_ok("productVariantStocksUpdate")
        if "productChannelListingUpdate" in query:
            listing["query"] = query
            listing["vars"] = variables or {}
            return _mut_ok("productChannelListingUpdate")
        if "productVariantChannelListingUpdate" in query:
            return _mut_ok("productVariantChannelListingUpdate")
        raise AssertionError(f"query inesperada: {query[:40]}")

    monkeypatch.setattr(publisher, "gql", router)
    res = publisher.publish_variant(
        VariantInput(sku="ABC", available=5, prices=[ChannelPrice("retail-cl", 1000)]))
    assert res.ok
    assert "visibleInListings" in listing["query"]
    assert listing["vars"].get("isPublished") is True


def _media_router(existing_urls, seen_creates, fail=False):
    def router(query, variables=None, **kw):
        if "productVariant(sku" in query:
            return _variant(allocated=0)
        if "productVariantStocksUpdate" in query:
            return _mut_ok("productVariantStocksUpdate")
        if "product(id" in query and "media" in query:
            # La URL de origen vive en la metadata de la foto (metafield),
            # porque ProductMedia no expone la URL externa en la API.
            return {"data": {"product": {"media": [
                {"id": "M0", "metafield": u} for u in existing_urls]}}}
        if "productMediaCreate" in query:
            seen_creates.append((variables or {}).get("url"))
            if fail:
                return {"data": {"productMediaCreate": {
                    "media": None, "errors": [{"field": "mediaUrl", "message": "no accesible"}]}}}
            return {"data": {"productMediaCreate": {"media": {"id": "M1"}, "errors": []}}}
        if "updateMetadata" in query:
            return _mut_ok("updateMetadata")
        raise AssertionError(f"query inesperada: {query[:40]}")
    return router


def test_publishes_images(monkeypatch):
    creates = []
    monkeypatch.setattr(publisher, "gql", _media_router([], creates))
    res = publisher.publish_variant(
        VariantInput(sku="ABC", available=3, images=["https://x/a.jpg", "https://x/b.jpg"]))
    assert res.ok
    assert creates == ["https://x/a.jpg", "https://x/b.jpg"]


def test_images_are_idempotent(monkeypatch):
    """Republicar no debe duplicar fotos ya adjuntas (match por externalUrl)."""
    creates = []
    monkeypatch.setattr(publisher, "gql", _media_router(["https://x/a.jpg"], creates))
    res = publisher.publish_variant(
        VariantInput(sku="ABC", available=3, images=["https://x/a.jpg", "https://x/b.jpg"]))
    assert res.ok
    assert creates == ["https://x/b.jpg"]        # solo la nueva


def test_image_failure_does_not_block_sale(monkeypatch):
    """Una foto que falla no impide que el SKU quede vendible."""
    creates = []
    monkeypatch.setattr(publisher, "gql", _media_router([], creates, fail=True))
    res = publisher.publish_variant(
        VariantInput(sku="ABC", available=3, images=["https://x/rota.jpg"]))
    assert res.ok                                 # sigue vendible
    assert res.stock_set == 3
    assert "fotos" in res.detail                  # pero la falla queda reportada


def test_calienta_miniaturas_de_fotos_nuevas(monkeypatch):
    """Publicar una foto debe generar sus miniaturas, para que la primera visita
    del comprador ya se sirva desde el CDN y no desde la API."""
    gets = []
    monkeypatch.setattr(publisher, "gql", _media_router([], []))
    monkeypatch.setattr(publisher.config, "SALEOR_API_URL", "http://saleor/graphql/")
    monkeypatch.setattr(publisher.config, "THUMBNAIL_WARM_SIZES", [256, 512])
    monkeypatch.setattr(publisher.config, "THUMBNAIL_WARM_FORMATS", [""])

    class _C:
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def get(self, url): gets.append(url)
    monkeypatch.setattr(publisher.httpx, "Client", lambda **k: _C())

    res = publisher.publish_variant(
        VariantInput(sku="ABC", available=1, images=["https://x/a.jpg"]))
    assert res.ok
    assert gets == ["http://saleor/thumbnail/M1/256/", "http://saleor/thumbnail/M1/512/"]


def test_no_calienta_las_fotos_ya_existentes(monkeypatch):
    """Republicar no debe re-generar miniaturas ya materializadas."""
    gets = []
    monkeypatch.setattr(publisher, "gql", _media_router(["https://x/a.jpg"], []))
    monkeypatch.setattr(publisher.config, "THUMBNAIL_WARM_SIZES", [256])
    monkeypatch.setattr(publisher.config, "THUMBNAIL_WARM_FORMATS", [""])

    class _C:
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def get(self, url): gets.append(url)
    monkeypatch.setattr(publisher.httpx, "Client", lambda **k: _C())

    res = publisher.publish_variant(
        VariantInput(sku="ABC", available=1, images=["https://x/a.jpg"]))
    assert res.ok
    assert gets == []


def test_fallo_al_calentar_no_afecta_la_venta(monkeypatch):
    """El calentamiento es best-effort: si falla, el SKU sigue publicado."""
    monkeypatch.setattr(publisher, "gql", _media_router([], []))
    monkeypatch.setattr(publisher.config, "THUMBNAIL_WARM_SIZES", [256])
    monkeypatch.setattr(publisher.config, "THUMBNAIL_WARM_FORMATS", [""])

    def _boom(**k): raise RuntimeError("sin red")
    monkeypatch.setattr(publisher.httpx, "Client", _boom)

    res = publisher.publish_variant(
        VariantInput(sku="ABC", available=7, images=["https://x/a.jpg"]))
    assert res.ok
    assert res.stock_set == 7
    assert "fotos" not in res.detail      # no se reporta: no es un fallo de foto


def test_calienta_cada_formato(monkeypatch):
    """El storefront pide `url(size:2048, format:WEBP)`: cada (tamaño, formato)
    es una miniatura distinta, y la que no se calienta vuelve a pasar por la API."""
    gets = []
    monkeypatch.setattr(publisher, "gql", _media_router([], []))
    monkeypatch.setattr(publisher.config, "SALEOR_API_URL", "http://saleor/graphql/")
    monkeypatch.setattr(publisher.config, "THUMBNAIL_WARM_SIZES", [2048])
    monkeypatch.setattr(publisher.config, "THUMBNAIL_WARM_FORMATS", ["", "webp"])

    class _C:
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def get(self, url): gets.append(url)
    monkeypatch.setattr(publisher.httpx, "Client", lambda **k: _C())

    res = publisher.publish_variant(
        VariantInput(sku="ABC", available=1, images=["https://x/a.jpg"]))
    assert res.ok
    assert gets == ["http://saleor/thumbnail/M1/2048/",
                    "http://saleor/thumbnail/M1/2048/webp/"]


# ─────────────────── slug de la ficha (URL pública) ───────────────────

def _slug_router(actual_slug, seen, existing=True):
    def router(query, variables=None, **kw):
        if "productVariant(sku" in query:
            return _variant(allocated=0) if existing else _variant(vid=None)
        if "productVariantStocksUpdate" in query:
            return _mut_ok("productVariantStocksUpdate")
        if "productVariantStocksCreate" in query:
            return _mut_ok("productVariantStocksCreate")
        if "product(id" in query and "slug" in query:
            return {"data": {"product": {"slug": actual_slug}}}
        if "productUpdate" in query:
            seen.append((variables or {}).get("slug"))
            return _mut_ok("productUpdate")
        if "productCreate" in query:
            seen.append(((variables or {}).get("input") or {}).get("slug"))
            return {"data": {"productCreate": {"product": {"id": "P9"}, "errors": []}}}
        if "productVariantCreate" in query:
            return {"data": {"productVariantCreate": {
                "productVariant": {"id": "V9", "product": {"id": "P9"}}, "errors": []}}}
        raise AssertionError(f"query inesperada: {query[:40]}")
    return router


def test_corrige_slug_distinto(monkeypatch):
    """Si el slug en Saleor no es el de origen, se corrige: la URL pública
    importa para conservar SEO y enlaces al migrar."""
    seen = []
    monkeypatch.setattr(publisher, "gql", _slug_router("autogenerado-por-saleor", seen))
    res = publisher.publish_variant(
        VariantInput(sku="ABC", available=1, slug="clickbox_raton-optico_mayorista"))
    assert res.ok
    assert seen == ["clickbox_raton-optico_mayorista"]


def test_no_reescribe_slug_igual(monkeypatch):
    """Idempotente: si ya coincide, no se escribe."""
    seen = []
    monkeypatch.setattr(publisher, "gql", _slug_router("ya-correcto", seen))
    res = publisher.publish_variant(
        VariantInput(sku="ABC", available=1, slug="ya-correcto"))
    assert res.ok
    assert seen == []


def test_slug_al_crear_producto(monkeypatch):
    """Al crear, el slug de origen va en el productCreate (no se autogenera)."""
    monkeypatch.setattr(config, "CREATE_MISSING", True)
    monkeypatch.setattr(publisher.product_type, "default_product_type_id", lambda: "PT1")
    monkeypatch.setattr(publisher.category, "default_category_id", lambda: "CAT1")
    seen = []
    monkeypatch.setattr(publisher, "gql", _slug_router("clickbox_x_mayorista", seen, existing=False))
    res = publisher.publish_variant(
        VariantInput(sku="NEW", available=2, slug="clickbox_x_mayorista"))
    assert res.ok and res.created
    assert seen[0] == "clickbox_x_mayorista"
