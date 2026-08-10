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
