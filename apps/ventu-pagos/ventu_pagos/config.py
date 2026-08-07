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


# URL pública a la que Webpay redirige tras el pago (return_url del commit).
RETURN_URL = os.getenv("VENTU_PAGOS_RETURN_URL", "http://localhost:8090/webpay/return")

# ── Saleor ──
SALEOR_WEBHOOK_SECRET = os.getenv("SALEOR_WEBHOOK_SECRET", "")
