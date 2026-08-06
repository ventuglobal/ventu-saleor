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

# ── Auth de la propia app ──
# Token de servicio para los endpoints de administración (POST /catalog/publish).
VENTU_ADMIN_TOKEN = os.getenv("VENTU_ADMIN_TOKEN", "")
# Secreto compartido para validar los webhooks entrantes de Saleor.
SALEOR_WEBHOOK_SECRET = os.getenv("SALEOR_WEBHOOK_SECRET", "")
