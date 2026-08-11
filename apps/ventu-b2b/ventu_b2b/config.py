"""Configuración de la App B2B (variables de entorno)."""

import os

SALEOR_API_URL = os.getenv("SALEOR_API_URL", "")
SALEOR_AUTH_TOKEN = os.getenv("SALEOR_AUTH_TOKEN", "")

# Canal por defecto de una empresa recién registrada. Se separa del canal en que
# se arman los carritos de WhatsApp: una empresa nueva parte en retail hasta que
# se le asigna nivel mayorista.
DEFAULT_NIVEL_PRECIO = os.getenv("B2B_DEFAULT_NIVEL_PRECIO", "retail-cl")

# Canal en que se crean los carritos enviados por WhatsApp. Nacen directamente
# en B2B por decisión de producto: el ejecutivo ya sabe que habla con una
# empresa, y así el carrito no necesita reconstruirse al identificarse.
CANAL_CARRITO = os.getenv("B2B_CANAL_CARRITO", "b2b-cl")

# Base pública para los enlaces de carrito enviados por WhatsApp.
STOREFRONT_URL = os.getenv("STOREFRONT_URL", "").rstrip("/")

# Tamaño máximo de la Carpeta Tributaria. Existe para acotar lo que el proceso
# llega a tener en memoria: el documento no se persiste, se reenvía.
CARPETA_MAX_BYTES = int(os.getenv("B2B_CARPETA_MAX_BYTES", str(15 * 1024 * 1024)))


def tramos_del_canal(channel_slug: str) -> str:
    """Escalera por defecto del channel, si la tiene.

    Es el último recurso: manda la del producto. Existe para no tener que cargar
    una tabla por cada uno de los 22.765 artículos cuando la regla es general.
    """
    key = "PRICING_TIERS_" + channel_slug.upper().replace("-", "_")
    return os.getenv(key, os.getenv("PRICING_TIERS", ""))


# ── margen mínimo en precios negociados ──
# Utilidad neta sobre el costo por debajo de la cual un precio negociado se
# rechaza. Vacío desactiva la revisión: sin costo publicado no hay nada que
# comparar, y bloquear ventas por un dato ausente sería peor que no revisar.
MARKUP_MINIMO = float(os.getenv("B2B_MARKUP_MINIMO", "0") or 0)

# Comisión de la pasarela de pago, que se descuenta de cada venta. Sin esto un
# markup del 30% con una pasarela del 3% deja 26,1% real.
COMISION_PASARELA = float(os.getenv("B2B_COMISION_PASARELA", "0") or 0)


# Stock por debajo del cual no se publican tramos por volumen: con pocas
# unidades, ofrecer precio por cantidad promete algo que no se puede cumplir.
STOCK_MINIMO_TRAMOS = int(os.getenv("B2B_STOCK_MINIMO_TRAMOS", "0") or 0)
