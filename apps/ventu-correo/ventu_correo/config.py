"""Configuración de Ventu Correo (variables de entorno)."""

import os

# ── Resend ──
RESEND_API_KEY = os.getenv("RESEND_API_KEY", "")
RESEND_URL = os.getenv("RESEND_URL", "https://api.resend.com/emails")

# Remitente. Debe ser de un dominio verificado en Resend; sin él no se envía
# nada: un remitente por defecto de otro dominio rebotaría o caería en spam, y
# eso se nota mucho más tarde que un "no configurado" en el log.
MAIL_FROM = os.getenv("MAIL_FROM", "")
# Respuestas de los clientes. Vacío = responden al remitente.
MAIL_REPLY_TO = os.getenv("MAIL_REPLY_TO", "")

# Nombre que encabeza los avisos de /enviar. Los correos de cuenta usan el
# nombre de la tienda que manda Saleor.
NOMBRE_TIENDA = os.getenv("CORREO_NOMBRE_TIENDA", "") or "Ventu"

# Tiempo máximo de espera a Resend. Saleor reintenta los webhooks que fallan,
# así que es preferible cortar y reintentar a quedarse colgado.
RESEND_TIMEOUT = float(os.getenv("RESEND_TIMEOUT", "10") or 10)

# ── autenticación de /enviar ──
# Lo usan los demás servicios del proyecto. Vacío = /enviar cerrado (503): un
# servicio que manda correos a nombre de la tienda no puede quedar abierto por
# una variable olvidada. CORREO_AUTH_ABIERTA=1 lo abre, solo en local.
SERVICE_TOKEN = os.getenv("CORREO_SERVICE_TOKEN", "")
AUTH_ABIERTA = os.getenv("CORREO_AUTH_ABIERTA", "") == "1"

# ── Saleor ──
# De aquí sale la clave pública con que se verifican los webhooks: solo se
# aceptan los firmados por esta instancia.
SALEOR_API_URL = os.getenv("SALEOR_API_URL", "")


def jwks_url() -> str:
    """URL de las claves públicas de Saleor, junto a /graphql/."""
    base = SALEOR_API_URL.rstrip("/")
    if base.endswith("/graphql"):
        base = base[: -len("/graphql")]
    return f"{base}/.well-known/jwks.json" if base else ""
