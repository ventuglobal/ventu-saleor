"""
facturador_v2 — Facturas electrónicas SII (DTE 33) por HTTP puro, sin Selenium.

Reemplazo moderno de sii_bot/facturador.py: replica el portal MiPyme por requests,
con Playwright solo para el login. La firma es CENTRALIZADA (server-side en el SII).
Ver docs/facturador_v2_reverse.md.
"""
from .emitir import emitir_factura, emitir_nota_credito
from .auth import get_session, login
from .client import flujo_hasta_firma, firmar, enviar

__all__ = ["emitir_factura", "emitir_nota_credito", "get_session", "login",
           "flujo_hasta_firma", "firmar", "enviar"]
