#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Configuración y constantes del emisor de Boletas Electrónicas SII (e-Boleta).

e-Boleta (eboleta.sii.cl) es una SPA serverless sobre AWS Amplify + Cognito.
NO usa Selenium ni el portal CGI del facturador de FACTURAS (sii_bot/facturador.py).
Ver docs/eboleta_api_reverse.md para el reverse engineering completo.
"""
import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

# ── Región / Cognito (capturados de la SPA) ───────────────────────────────────
AWS_REGION       = "us-east-1"
COGNITO_HOST     = f"https://cognito-identity.{AWS_REGION}.amazonaws.com/"
# El provider key del login federado: la SPA guarda el token bajo esta clave.
COGNITO_LOGIN_PROVIDER = "cognito-identity.amazonaws.com"

# ── API Gateway (auth AWS_IAM / SigV4, service = execute-api) ──────────────────
API_BASE   = "https://cn68i6qm0g.execute-api.us-east-1.amazonaws.com/prod"
GENERAR_URL      = f"{API_BASE}/api/dte/documentos/generar"
INFO_EMISOR_URL  = f"{API_BASE}/api/info-contribuyente/info-emisor-usuario"   # /{rutEmpresa}/{rutUsuario}
EMISORES_USR_URL = f"{API_BASE}/api/info-contribuyente/emisores-usuario"      # /{rutUsuario}
SIGV4_SERVICE    = "execute-api"

# ── Emisor (empresa) ──────────────────────────────────────────────────────────
# RUT de la empresa emisora con DV (formato SII: sin puntos, con guión).
RUT_EMPRESA = os.getenv("SII_RUT_EMPRESA", "77844948-K")

# ── Credenciales de login SII (clave tributaria del usuario) ───────────────────
# Las pone el usuario en .env. NUNCA hardcodear (a diferencia del CLAVE_FIRMA
# heredado en facturador.py).
SII_RUT_USUARIO = os.getenv("SII_RUT_USUARIO", "")   # ej "16367072-0"
SII_CLAVE       = os.getenv("SII_CLAVE", "")

# ── Documento ─────────────────────────────────────────────────────────────────
TIPO_DTE_AFECTA = 39   # boleta electrónica afecta (la única que usamos)

# Largo máx de la descripción (NmbItem). e-Boleta acepta hasta 80, pero el campo
# visible es corto → mantenemos una descripción compacta. Configurable por si acaso.
MAX_DESC_LEN = int(os.getenv("SII_BOLETA_MAX_DESC", "45"))
TIPO_DTE_EXENTA = 41   # exenta (no se usa por ahora; documentado)

# Consumidor final por defecto (cuando NO se informa receptor): RUT genérico SII.
RECEPTOR_CONSUMIDOR_FINAL = {
    "RUTRecep": "66666666-6",
    "RznSocRecep": "SII Boleta",
    "DirRecep": "Santiago",
}

# ── Rutas locales ─────────────────────────────────────────────────────────────
BASE_DIR   = Path(__file__).resolve().parent
AUTH_CACHE = BASE_DIR / ".auth_cache.json"          # token federado (gitignored)
PDF_DIR    = BASE_DIR.parent / "var" / "sii_boletas"  # PDFs emitidos
LOGIN_URL  = "https://eboleta.sii.cl/"

# Portada: misma que usa el facturador de facturas. Se antepone a cada PDF emitido.
PORTADA_PDF = BASE_DIR.parent / "sii_bot" / "portada.pdf"
INSERTAR_PORTADA = os.getenv("SII_BOLETA_PORTADA", "1") not in ("0", "false", "False", "")
