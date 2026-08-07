"""
boleta_bot — Emisor de Boletas Electrónicas SII (e-Boleta), HTTP puro + SigV4.

Reemplazo moderno (sin Selenium) para emitir boletas en eboleta.sii.cl.
Distinto del facturador de FACTURAS (sii_bot/facturador.py, CGI legacy + certificado).
Ver docs/eboleta_api_reverse.md.
"""
from .emitir import (
    emitir_boleta, run_from_data, construir_body, cargar_boletas_archivo,
)
from .auth import login_sii, get_aws_credentials, get_federated_info

__all__ = [
    "emitir_boleta", "run_from_data", "construir_body", "cargar_boletas_archivo",
    "login_sii", "get_aws_credentials", "get_federated_info",
]
