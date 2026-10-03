"""Config de la app Ventu Pagos (env). Ver README y .env.example."""

from __future__ import annotations

import os

# ── Webpay / Transbank ──
# En integración se usan las credenciales públicas de prueba de Transbank.
WEBPAY_ENV = os.getenv("WEBPAY_ENV", "integration")  # integration | production
WEBPAY_COMMERCE_CODE = os.getenv("WEBPAY_COMMERCE_CODE", "597055555532")  # test por defecto
WEBPAY_API_KEY = os.getenv(
    "WEBPAY_API_KEY",
    "579B532A7440BB0C9079DED94D31EA1615BACEB56610332264630D42D0A36B1C",  # test público
)

_BASE_URLS = {
    "integration": "https://webpay3gint.transbank.cl",
    "production": "https://webpay3g.transbank.cl",
}


def webpay_base_url() -> str:
    return _BASE_URLS.get(WEBPAY_ENV, _BASE_URLS["integration"])


# URL pública a la que Webpay redirige tras el pago (return_url del create).
# En el flujo normal apunta a la ruta server-side del STOREFRONT (no a esta app),
# que hace transactionProcess → dispara el commit por webhook. Ver README.
RETURN_URL = os.getenv("VENTU_PAGOS_RETURN_URL", "http://localhost:3000/checkout/webpay/retorno")

# Base del storefront para construir redirects de resultado desde el fallback.
STOREFRONT_URL = os.getenv("STOREFRONT_URL", "http://localhost:3000")

# Canales donde Webpay está habilitado. El resto (B2B) se rechaza en initialize.
WEBPAY_CHANNELS = {
    c.strip() for c in os.getenv("WEBPAY_CHANNELS", "retail-cl").split(",") if c.strip()
}

# Moneda soportada (Webpay CLP es entero, sin decimales).
WEBPAY_CURRENCY = os.getenv("WEBPAY_CURRENCY", "CLP")

# ── Saleor ──
# URL del GraphQL de Saleor (para transactionEventReport y JWKS). Se completa al
# instalar la app (/register) si no viene por env.
SALEOR_API_URL = os.getenv("SALEOR_API_URL", "")

# Verificación de firma JWS de los webhooks (Saleor-Signature). 0 solo para local.
VERIFY_SIGNATURE = os.getenv("VENTU_PAGOS_VERIFY_SIGNATURE", "1") not in ("0", "false", "False")

# Secreto legacy HMAC (solo si el webhook se configuró con secretKey; deprecado).
SALEOR_WEBHOOK_SECRET = os.getenv("SALEOR_WEBHOOK_SECRET", "")

# ── Persistencia ──
# Postgres en Railway (DATABASE_URL); SQLite por defecto en local/tests.
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./ventu_pagos.db")

# ── Reconciliador ──
# Token simple para proteger /tasks/reconcile (lo llama el cron de Railway).
RECONCILE_TOKEN = os.getenv("RECONCILE_TOKEN", "")
# Minutos tras los cuales una tx INITIALIZED sin cierre se reconcilia.
RECONCILE_AFTER_MIN = int(os.getenv("RECONCILE_AFTER_MIN", "15"))
