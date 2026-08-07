"""Lógica pura de facturación (sin red): decisión boleta/factura, extracción de
receptor desde `order.metadata`, mapeo de líneas y RUT chileno.

El emisor real (Playwright/SII para factura, API para boleta) vive en
`emitter.py` y delega en los paquetes vendorizados.
"""

from __future__ import annotations

import re
from decimal import ROUND_HALF_UP, Decimal
from typing import Any, Dict, List, Optional

IVA_RATE = Decimal("0.19")

# Clave en metadata donde se estampa el folio (idempotencia).
FOLIO_KEY = "ventu.dte.folio"
DTE_STATUS_KEY = "ventu.dte.status"


# ───────────────────────────── RUT chileno ─────────────────────────────

def clean_rut(rut: str) -> str:
    return re.sub(r"[^0-9kK]", "", str(rut or "")).upper()


def rut_is_valid(rut: str) -> bool:
    """Valida RUT chileno (módulo 11)."""
    r = clean_rut(rut)
    if len(r) < 2:
        return False
    cuerpo, dv = r[:-1], r[-1]
    if not cuerpo.isdigit():
        return False
    suma, factor = 0, 2
    for d in reversed(cuerpo):
        suma += int(d) * factor
        factor = 2 if factor == 7 else factor + 1
    resto = 11 - (suma % 11)
    esperado = "0" if resto == 11 else "K" if resto == 10 else str(resto)
    return dv == esperado


# ─────────────────────── receptor / decisión de DTE ───────────────────────

def _md(metadata) -> Dict[str, str]:
    """Normaliza metadata de Saleor (lista [{key,value}] o dict) a dict."""
    if isinstance(metadata, dict):
        return {str(k): str(v) for k, v in metadata.items()}
    out: Dict[str, str] = {}
    for entry in metadata or []:
        if isinstance(entry, dict) and "key" in entry:
            out[str(entry["key"])] = str(entry.get("value", ""))
    return out


def extract_receptor(order: dict) -> Dict[str, str]:
    """Receptor tributario desde la metadata de la orden (la captura el checkout).

    Claves esperadas (namespaced): ventu.rut, ventu.razon_social, ventu.giro,
    ventu.direccion, ventu.comuna, ventu.ciudad.
    """
    md = _md(order.get("metadata"))
    ship = order.get("shipping_address") or order.get("shippingAddress") or {}
    return {
        "rut": md.get("ventu.rut", ""),
        "razon_social": md.get("ventu.razon_social", ""),
        "giro": md.get("ventu.giro", ""),
        "direccion": md.get("ventu.direccion") or ship.get("street_address_1")
        or ship.get("streetAddress1", ""),
        "comuna": md.get("ventu.comuna") or ship.get("city", ""),
        "ciudad": md.get("ventu.ciudad") or ship.get("country_area")
        or ship.get("countryArea", ""),
    }


def decide_document_type(receptor: Dict[str, str]) -> str:
    """factura si el comprador dio RUT válido + razón social; si no, boleta."""
    if rut_is_valid(receptor.get("rut", "")) and receptor.get("razon_social"):
        return "factura"
    return "boleta"


def already_invoiced(order: dict) -> bool:
    """Idempotencia: ya hay folio en metadata ⇒ no re-emitir."""
    return bool(_md(order.get("metadata")).get(FOLIO_KEY))


# ─────────────────────────── mapeo de líneas ───────────────────────────

def _line_qty(line: dict) -> int:
    return int(line.get("quantity") or 1)


def _line_gross_unit(line: dict) -> Decimal:
    """Precio unitario BRUTO (IVA incl.) de una línea de orden de Saleor."""
    for path in (("unit_price_gross_amount",),
                 ("unit_price", "gross", "amount"),
                 ("unitPrice", "gross", "amount")):
        cur: Any = line
        ok = True
        for k in path:
            if isinstance(cur, dict) and k in cur:
                cur = cur[k]
            else:
                ok = False
                break
        if ok and cur is not None:
            return Decimal(str(cur))
    return Decimal("0")


def _net_from_gross(gross: Decimal) -> int:
    return int((gross / (Decimal(1) + IVA_RATE)).quantize(Decimal(1), rounding=ROUND_HALF_UP))


def order_to_factura_items(order: dict) -> List[Dict[str, Any]]:
    """Ítems para `emitir_factura`: `precio_neto` (sin IVA) + `cantidad`."""
    items = []
    for ln in order.get("lines") or []:
        gross = _line_gross_unit(ln)
        items.append({
            "nombre": ln.get("product_name") or ln.get("productName") or ln.get("variant_name") or "Item",
            "cantidad": _line_qty(ln),
            "precio_neto": _net_from_gross(gross),
        })
    return items


def order_to_boleta_items(order: dict) -> List[Dict[str, Any]]:
    """Ítems para `emitir_boleta`: `precio` (BRUTO) + `cantidad`."""
    items = []
    for ln in order.get("lines") or []:
        gross = _line_gross_unit(ln)
        items.append({
            "nombre": ln.get("product_name") or ln.get("productName") or ln.get("variant_name") or "Item",
            "cantidad": _line_qty(ln),
            "precio": int(gross.quantize(Decimal(1), rounding=ROUND_HALF_UP)),
        })
    return items
