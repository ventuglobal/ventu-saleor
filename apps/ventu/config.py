"""Configuración de la app Ventu (env). Ver README y .env.example."""

from __future__ import annotations

import os

# ── Saleor ──
SALEOR_API_URL = os.getenv("SALEOR_API_URL", "http://localhost:8000/graphql/")
SALEOR_AUTH_TOKEN = os.getenv("SALEOR_AUTH_TOKEN", "")

# Warehouse global "VENTU". gid preferido; si falta, se resuelve por slug.
SALEOR_WAREHOUSE_ID = os.getenv("SALEOR_WAREHOUSE_ID", "")
SALEOR_WAREHOUSE_SLUG = os.getenv("SALEOR_WAREHOUSE_SLUG", "ventu")

# MVP: mantener publicado aunque el available sea 0 (visible pero "agotado").
ENSURE_PUBLISHED = os.getenv("SALEOR_ENSURE_PUBLISHED", "1") not in ("0", "false", "False", "")

# Creación de producto/variante para SKUs que aún no existen en Saleor.
CREATE_MISSING = os.getenv("SALEOR_CREATE_MISSING", "1") not in ("0", "false", "False", "")
# Tipo de producto por defecto: cada SKU se modela como un producto simple con
# una variante. Se resuelve/crea por slug (una vez, cacheado).
DEFAULT_PRODUCT_TYPE_SLUG = os.getenv("SALEOR_DEFAULT_PRODUCT_TYPE_SLUG", "ventu-default")
DEFAULT_PRODUCT_TYPE_NAME = os.getenv("SALEOR_DEFAULT_PRODUCT_TYPE_NAME", "Ventu Default")
# Saleor exige categoría para publicar un producto (PRODUCT_WITHOUT_CATEGORY),
# así que los SKUs creados por el publisher caen en una categoría por defecto.
DEFAULT_CATEGORY_SLUG = os.getenv("SALEOR_DEFAULT_CATEGORY_SLUG", "ventu")
DEFAULT_CATEGORY_NAME = os.getenv("SALEOR_DEFAULT_CATEGORY_NAME", "Ventu")

# ── miniaturas ──
# Saleor genera cada miniatura en la PRIMERA petición a /thumbnail/, y solo
# entonces la sube al storage y puede devolver su URL directa. Sin calentarlas,
# la primera visita de cada producto pasa por la API en vez de ir al CDN.
# Vacío ("") desactiva el calentamiento.
# Los tamaños por defecto cubren los que pide el storefront: 1024 en el listado
# y 2048 en la ficha de producto (verificado sobre el HTML servido).
THUMBNAIL_WARM_SIZES = [int(s) for s in
                        os.getenv("THUMBNAIL_WARM_SIZES", "256,512,1024,2048").split(",")
                        if s.strip().isdigit()]

# Cada (tamaño, formato) es una miniatura DISTINTA en el storage. El storefront
# pide `url(size: 2048, format: WEBP)`, así que calentar solo el formato de
# origen deja la variante webp sin generar y la ficha vuelve a pasar por la API.
# "" = formato original; el resto son formatos de Saleor (webp, avif…).
THUMBNAIL_WARM_FORMATS = [f.strip().lower() for f in
                          os.getenv("THUMBNAIL_WARM_FORMATS", ",webp").split(",")]

# ── Pricing ──
# Channels a los que se publica precio, y política por defecto (env-configurable).
PRICING_CHANNELS = [c.strip() for c in os.getenv("PRICING_CHANNELS", "retail-cl,b2b-cl").split(",") if c.strip()]
PRICING_MARKUP = float(os.getenv("PRICING_MARKUP", "0.30"))          # margen sobre costo neto
PRICING_FIXED_FEE = float(os.getenv("PRICING_FIXED_FEE", "0"))       # fee fijo neto (CLP)
PRICING_IVA_RATE = float(os.getenv("PRICING_IVA_RATE", "0.19"))
PRICING_GROSS = os.getenv("PRICING_GROSS", "1") not in ("0", "false", "False", "")
PRICING_ROUND_TO = int(os.getenv("PRICING_ROUND_TO", "10"))
# Override de markup por channel: PRICING_MARKUP_RETAIL_CL=0.35, etc.


def markup_for(channel_slug: str) -> float:
    key = "PRICING_MARKUP_" + channel_slug.upper().replace("-", "_")
    val = os.getenv(key)
    return float(val) if val is not None else PRICING_MARKUP


def gross_for(channel_slug: str) -> bool:
    """¿Los precios de este channel se publican con IVA incluido?

    Override por channel (`PRICING_GROSS_<SLUG>`), igual que el markup. Existe
    porque retail y B2B difieren: al consumidor se le muestra el precio final con
    IVA, mientras que una empresa compra sobre el neto y el IVA se detalla en la
    factura. Sin esto, ambos channels heredarían el mismo tratamiento global y el
    canal mayorista publicaría precios con IVA incluido.
    """
    key = "PRICING_GROSS_" + channel_slug.upper().replace("-", "_")
    val = os.getenv(key)
    if val is None:
        return PRICING_GROSS
    return val not in ("0", "false", "False", "")


# Escalera de tramos por channel: PRICING_TIERS_B2B_CL="1:1.0,10:0.9,50:0.8"
# Cada par es `cantidad_minima:factor`, donde el factor multiplica el precio
# unitario del channel. Se expresa como factor y no como monto para que la
# escalera no dependa del precio de cada producto: un mismo "10+ paga 10% menos"
# sirve para todo el catálogo.
PRICING_TIERS_DEFAULT = os.getenv("PRICING_TIERS", "")


def tiers_for(channel_slug: str) -> str:
    """Definición cruda de tramos del channel, o cadena vacía si no tiene.

    Los tramos son **por channel**, no por empresa: la escalera es la misma para
    todo el canal mayorista. El precio por empresa queda para la fase 1.2.

    Es el valor por defecto: un producto puede traer su propia escalera y en ese
    caso manda la suya (ver `pricing.tiers.escalera_para`).
    """
    key = "PRICING_TIERS_" + channel_slug.upper().replace("-", "_")
    val = os.getenv(key)
    return val if val is not None else PRICING_TIERS_DEFAULT


# ── Auth de la propia app ──
# Token de servicio para los endpoints de administración (POST /catalog/publish).
VENTU_ADMIN_TOKEN = os.getenv("VENTU_ADMIN_TOKEN", "")
# Secreto compartido para validar los webhooks entrantes de Saleor.
SALEOR_WEBHOOK_SECRET = os.getenv("SALEOR_WEBHOOK_SECRET", "")
