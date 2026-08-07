"""Adapter al emisor real de DTE (paquetes vendorizados de Ventu 1.0).

Import **lazy**: `facturador_v2` (Playwright/SII) y `boleta_bot` (API) traen deps
pesadas; se importan solo al emitir, así los tests de la lógica pura no las
requieren. El directorio `vendor/` se agrega al path en tiempo de import.
"""

from __future__ import annotations

import os
import sys
from typing import Any, Dict, List

_VENDOR = os.path.join(os.path.dirname(__file__), "..", "vendor")
if _VENDOR not in sys.path:
    sys.path.insert(0, os.path.abspath(_VENDOR))


def emitir_factura(receptor: Dict[str, str], items: List[Dict[str, Any]]) -> dict:
    from facturador_v2 import emitir_factura as _f  # noqa: WPS433 (lazy)
    return _f(receptor, items)


def emitir_boleta(items: List[Dict[str, Any]], receptor: Dict[str, str] | None = None) -> dict:
    from boleta_bot import emitir_boleta as _b  # noqa: WPS433 (lazy)
    return _b(items, receptor=receptor)
