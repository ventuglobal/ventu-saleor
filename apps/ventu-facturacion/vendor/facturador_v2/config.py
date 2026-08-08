#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Configuración del Facturador v2 — facturas SII (DTE 33) por HTTP puro, sin Selenium.

A diferencia del facturador legacy (sii_bot/facturador.py, Selenium + Firefox), este
módulo replica el portal MiPyme por HTTP: login con Playwright solo para obtener las
cookies, y el resto (formulario, preview, firma, envío) por requests.

La FIRMA es CENTRALIZADA: el certificado vigente vive en el SII y firma server-side
vía postFirmaDigital.cgi. El certificado local de Firefox está vencido, por eso no
se puede firmar en el equipo. Ver docs/facturador_v2_reverse.md.
"""
import logging
import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

# El logging de Django deja httpx/urllib3 en DEBUG y ensucia la salida del
# facturador con líneas de SSL en cada request. Solo queremos ver el avance.
for _n in ("httpx", "httpcore", "urllib3", "asyncio"):
    logging.getLogger(_n).setLevel(logging.WARNING)

# ── Portal MiPyme (CGI) ───────────────────────────────────────────────────────
BASE = "https://www1.sii.cl/cgi-bin/Portal001"
SEL_EMPRESA_URL = (f"{BASE}/mipeSelEmpresa.cgi?DESDE_DONDE_URL=OPCION%3D33%26TIPO%3D4")
FORM_URL        = f"{BASE}/mipeGenFacEx.cgi?PTDC_CODIGO=33"
PREVIEW_URL     = f"{BASE}/mipeDisplayPreView.cgi"
XMLFIRMA_URL    = f"{BASE}/mipeGenXMLFirma.cgi"
CERT_URL        = f"{BASE}/getCertDigital.cgi"
FIRMA_URL       = f"{BASE}/postFirmaDigital.cgi"
SENDXML_URL     = f"{BASE}/mipeSendXML.cgi"

# ── Emisor ────────────────────────────────────────────────────────────────────
RUT_EMPRESA = os.getenv("SII_RUT_EMPRESA", "77844948-K")
CDG_SII_SUCUR = os.getenv("SII_CDG_SUCURSAL", "89779838")
ACTECO = os.getenv("SII_ACTECO", "479100")
DIR_ORIGEN = os.getenv("SII_DIR_ORIGEN", "LAS BELLOTAS 199 OF 62")
CMNA_ORIGEN = os.getenv("SII_CMNA_ORIGEN", "PROVIDENCIA")
CIUDAD_ORIGEN = os.getenv("SII_CIUDAD_ORIGEN", "Santiago")
# Contacto del emisor que va impreso en la factura (mismos valores que el legacy:
# el formulario trae otros por defecto y hay que sobreescribirlos).
EMAIL_EMISOR = os.getenv("SII_EMAIL_EMISOR", "contacto@ventu.cl")
FONO_EMISOR = os.getenv("SII_FONO_EMISOR", "952232832")

# ── Credenciales (.env) ───────────────────────────────────────────────────────
SII_RUT_USUARIO = os.getenv("SII_RUT_USUARIO", "")   # persona que firma
SII_CLAVE       = os.getenv("SII_CLAVE", "")         # clave tributaria (login)
SII_CLAVE_FIRMA = os.getenv("SII_CLAVE_FIRMA", "")   # clave del certificado (firma)

# ── Firma centralizada (valores exactos que espera el SII) ────────────────────
# El JS del portal transforma los paths: '/dte:DTE' → 'dte:DTE' y
# '/dte:DTE/dte:Documento' → 'dte:Documento'. Mandar los originales devuelve vacío.
FIRMA_NODO      = "dte:DTE"
FIRMA_NODO_ID   = "dte:Documento"
FIRMA_NAMESPACE = "http://www.sii.cl/SiiDte"

# Placeholder para campos obligatorios del receptor que la orden no trae
# (mismo criterio que sii_bot/facturador.py)
PLACEHOLDER_RECEPTOR = "No informado"

TIPO_DTE_FACTURA = 33      # factura electrónica afecta
IVA_TASA = 19

UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36")

# ── Rutas locales ─────────────────────────────────────────────────────────────
BASE_DIR    = Path(__file__).resolve().parent
COOKIE_CACHE = BASE_DIR / ".cookies.json"
PDF_DIR      = BASE_DIR.parent / "descargas_pdfs"
# Portada que se antepone al PDF (la misma del facturador legacy)
PORTADA_PDF  = BASE_DIR.parent / "sii_bot" / "portada.pdf"
INSERTAR_PORTADA = os.getenv("SII_FACTURA_PORTADA", "1") not in ("0", "false", "False", "")
