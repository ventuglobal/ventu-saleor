#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Emisión de facturas (DTE 33) por HTTP puro — API del Facturador v2.

Uso programático:
    from facturador_v2 import emitir_factura
    r = emitir_factura(
        receptor={"rut": "76469595-K", "razon_social": "ACME SPA",
                  "giro": "COMERCIO", "direccion": "Av 123",
                  "comuna": "Santiago", "ciudad": "Santiago"},
        items=[{"nombre": "Cable HDMI", "cantidad": 2, "precio_neto": 4200}],
    )
    # r = {"estado","folio","neto","iva","total","pdf_path","momento"}

CLI:
    python -m facturador_v2 --test-receptor 76469595-K   # factura mínima de prueba
    python -m facturador_v2 --login                      # refresca la sesión
"""
import argparse
import re
import sys
import time
from typing import List, Optional
from urllib.parse import urljoin

from . import config
from .auth import get_session, login
from .client import flujo_hasta_firma, firmar, enviar, _norm_rut


def _insertar_portada(pdf_path) -> None:
    """Antepone la portada al PDF (igual que el facturador legacy). Silencioso si falta."""
    if not config.INSERTAR_PORTADA or not config.PORTADA_PDF.exists():
        return
    try:
        from pypdf import PdfReader, PdfWriter
        from pathlib import Path as _P
        pdf_path = _P(pdf_path)
        w = PdfWriter()
        w.append(PdfReader(str(config.PORTADA_PDF)))
        w.append(PdfReader(str(pdf_path)))
        tmp = pdf_path.with_suffix(".tmp.pdf")
        with tmp.open("wb") as fp:
            w.write(fp)
        tmp.replace(pdf_path)
    except Exception as e:
        print(f"  ⚠️ no se pudo anteponer la portada: {str(e).splitlines()[0]}")


def _descargar_pdf(s, html: str, folio: Optional[str], prefijo: str = "factura") -> Optional[str]:
    """Baja el PDF desde el link 'Ver Documento' de la respuesta de emisión.

    Se busca el ancla por su TEXTO (igual que el facturador legacy), no por la URL:
    el CGI del documento no tiene un nombre estable.
    """
    m = re.search(r'<a[^>]+href=["\']([^"\']+)["\'][^>]*>\s*Ver\s+Documento\s*</a>',
                  html, re.I | re.S)
    if not m:
        m = re.search(r'href=["\']([^"\']+)["\'][^>]{0,80}Ver\s+Documento', html, re.I | re.S)
    if not m:
        return None
    url = urljoin(config.SENDXML_URL, m.group(1))
    try:
        r = s.get(url, timeout=90)
        r.raise_for_status()
        if not r.content.startswith(b"%PDF"):
            return None
        config.PDF_DIR.mkdir(parents=True, exist_ok=True)
        destino = config.PDF_DIR / f"{prefijo}_{folio or 'sinfolio'}_{time.strftime('%Y%m%d_%H%M%S')}.pdf"
        destino.write_bytes(r.content)
        _insertar_portada(destino)
        return str(destino)
    except Exception:
        return None


def emitir_factura(receptor: dict, items: List[dict],
                   fecha_emision: Optional[str] = None,
                   session=None, forma_pago: str = "credito") -> dict:
    """Emite UNA factura electrónica (DTE 33). `precio_neto` por ítem (sin IVA)."""
    ts = time.strftime("%Y-%m-%d %H:%M:%S")
    neto = sum(int(round(i["precio_neto"])) * int(i["cantidad"]) for i in items)
    iva = int(round(neto * config.IVA_TASA / 100))
    try:
        s = session or get_session()
        firma_html = flujo_hasta_firma(s, receptor, items, fecha_emision,
                                       forma_pago=forma_pago)
        dato, firmado, cert_id = firmar(s, firma_html)
        res = enviar(s, firma_html, dato, firmado, cert_id)
        pdf = _descargar_pdf(s, res["html"], res.get("folio"))
        return {"estado": "emitida", "folio": res.get("folio"),
                "neto": neto, "iva": iva, "total": neto + iva,
                "pdf_path": pdf, "momento": ts}
    except Exception as e:
        return {"estado": "no-emitida", "detalle": str(e).splitlines()[0],
                "neto": neto, "iva": iva, "total": neto + iva, "momento": ts}


def emitir_nota_credito(receptor: dict, items: List[dict], referencias: List[dict],
                        fecha_emision: Optional[str] = None, session=None,
                        forma_pago: str = "credito") -> dict:
    """Emite UNA Nota de Crédito electrónica (DTE 61).

    `referencias`: [{'tpo_doc','folio','fecha','codigo','razon'}] — al menos una.
    Para ANULAR una factura: codigo='1' y los `items` deben ESPEJAR los del documento
    anulado (mismos neto/cantidad) para revertir exactamente lo declarado.
    """
    ts = time.strftime("%Y-%m-%d %H:%M:%S")
    neto = sum(int(round(i["precio_neto"])) * int(i["cantidad"]) for i in items)
    iva = int(round(neto * config.IVA_TASA / 100))
    if not referencias:
        return {"estado": "no-emitida", "detalle": "una NC exige al menos una referencia",
                "neto": neto, "iva": iva, "total": neto + iva, "momento": ts}
    try:
        s = session or get_session()
        firma_html = flujo_hasta_firma(s, receptor, items, fecha_emision,
                                       forma_pago=forma_pago, ptdc_codigo=61,
                                       referencias=referencias)
        dato, firmado, cert_id = firmar(s, firma_html)
        res = enviar(s, firma_html, dato, firmado, cert_id)
        pdf = _descargar_pdf(s, res["html"], res.get("folio"), prefijo="nota_credito")
        return {"estado": "emitida", "folio": res.get("folio"), "tipo_dte": 61,
                "neto": neto, "iva": iva, "total": neto + iva,
                "pdf_path": pdf, "momento": ts}
    except Exception as e:
        return {"estado": "no-emitida", "detalle": str(e).splitlines()[0],
                "neto": neto, "iva": iva, "total": neto + iva, "momento": ts}


def main():
    ap = argparse.ArgumentParser(description="Facturador v2 — facturas SII por HTTP")
    ap.add_argument("--login", action="store_true", help="refresca la sesión (abre login)")
    ap.add_argument("--test-receptor", help="emite una factura mínima de prueba a este RUT")
    ap.add_argument("--monto", type=int, default=1000, help="neto de la prueba (def 1000)")
    ap.add_argument("--detalle", default="PRUEBA FACTURADOR V2")
    args = ap.parse_args()

    if args.login:
        login()
        print("✓ Sesión refrescada.")
        return

    if args.test_receptor:
        rut, _dv = _norm_rut(args.test_receptor)
        emisor, _ = _norm_rut(config.RUT_EMPRESA)
        if rut == emisor:
            print("✗ No se factura al RUT propio (auto-factura bloqueada).")
            return 1
        r = emitir_factura(
            receptor={"rut": args.test_receptor, "razon_social": "", "giro": "",
                      "direccion": "", "comuna": "", "ciudad": ""},
            items=[{"nombre": args.detalle, "cantidad": 1, "precio_neto": args.monto}])
        print("Resultado:", r)
        return 0 if r["estado"] == "emitida" else 1

    ap.print_help()


if __name__ == "__main__":
    sys.exit(main() or 0)
