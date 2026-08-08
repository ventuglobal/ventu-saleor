"""Config de la app Ventu Facturación (env)."""

from __future__ import annotations

import os

# Saleor (para escribir el folio en order.metadata)
SALEOR_API_URL = os.getenv("SALEOR_API_URL", "http://localhost:8000/graphql/")
SALEOR_AUTH_TOKEN = os.getenv("SALEOR_AUTH_TOKEN", "")
SALEOR_WEBHOOK_SECRET = os.getenv("SALEOR_WEBHOOK_SECRET", "")

# Las credenciales del SII / API de boletas las leen los paquetes vendorizados
# desde su propio env (SII_RUT_USUARIO, SII_CLAVE, SII_CLAVE_FIRMA, etc.).
