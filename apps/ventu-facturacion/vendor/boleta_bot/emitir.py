#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Emisor de Boletas Electrónicas SII (e-Boleta) — HTTP puro + SigV4, sin Selenium.

Uso programático:
    from boleta_bot import emitir_boleta
    r = emitir_boleta(
        items=[{"nombre": "Cable HDMI 2m", "cantidad": 2, "precio": 5000}],
        # receptor=None  → consumidor final (boleta sin datos de receptor)
    )
    # r = {"estado","folio","tipo_dte","total","pdf_path","pdf_url","momento"}

CLI:
    python -m boleta_bot.emitir --test                 # emite boleta $1.000 de prueba
    python -m boleta_bot.emitir --inspect              # muestra el shape del emisor (debug)
    python -m boleta_bot.emitir --login                # fuerza re-login (refresca token)
"""
import re
import csv
import sys
import json
import time
import base64
import argparse
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Dict, List, Any, Optional

import requests

from . import config
from .client import signed_request, get_emisor_info


# ── Sanitización de texto (mismas reglas que el facturador de facturas) ───────
_SII_CHARS_RE = re.compile(r'[^A-Za-z0-9áéíóúñÁÉÍÓÚÑüÜ \.,;:/#\-\(\)\+&%$]')


def _sanitizar(texto: str) -> str:
    return _SII_CHARS_RE.sub('', str(texto or '')).strip()


# ── Construcción del cuerpo de emisión ────────────────────────────────────────
def _resolver_emisor() -> Dict[str, Any]:
    """Obtiene info_emisor + CdgSIISucur desde la API (cacheado por proceso)."""
    if not hasattr(_resolver_emisor, "_cache"):
        raw = get_emisor_info()
        # La respuesta puede venir directa o envuelta; normalizamos.
        info = raw.get("info_emisor") if isinstance(raw, dict) and "info_emisor" in raw else raw
        sucursales = (info or {}).get("sucursales") or []
        cdg = sucursales[0]["codigo"] if sucursales else None
        _resolver_emisor._cache = {"info_emisor": info, "cdg_sucursal": cdg}
    return _resolver_emisor._cache


def construir_body(items: List[Dict[str, Any]],
                   receptor: Optional[Dict[str, str]] = None,
                   rut_empresa: str = None,
                   rut_usuario: str = None) -> Dict[str, Any]:
    rut_empresa = (rut_empresa or config.RUT_EMPRESA).strip()
    rut_usuario = (rut_usuario or config.SII_RUT_USUARIO).strip()
    emisor = _resolver_emisor()

    # e-Boleta es de MONTO ÚNICO: su PDF solo renderiza UNA línea de Detalle (si se
    # mandan varias, suma el total pero muestra solo la primera → boleta inconsistente,
    # ej. línea $5.300 con IVA de $13.700). Por eso colapsamos SIEMPRE a una sola línea:
    # PrcItem = monto total, QtyItem = 1, NmbItem = descripción CORTA.
    nombres, total = [], 0
    for it in items:
        nombre = _sanitizar(it.get("nombre") or it.get("descripcion") or it.get("NmbItem") or "")
        qty = int(it.get("cantidad") or it.get("QtyItem") or 1)
        prc = int(round(float(it.get("precio") or it.get("PrcItem") or 0)))
        total += prc * qty
        if nombre:
            nombres.append(nombre)

    def _corta(texto: str, n: int) -> str:
        """Acorta a n chars cortando en límite de palabra (evita cortar a media palabra)."""
        if len(texto) <= n:
            return texto
        rec = texto[:n].rstrip()
        if " " in rec[max(0, n - 15):]:      # hay un espacio cerca del final
            rec = rec[:rec.rfind(" ")].rstrip()
        return rec

    if not nombres:
        descripcion = "Venta"
    elif len(nombres) == 1:
        descripcion = _corta(nombres[0], config.MAX_DESC_LEN)
    else:
        # pack: primer producto (acortado) + "(+N más)" para no pasar el largo
        sufijo = f" (+{len(nombres) - 1} más)"
        descripcion = _corta(nombres[0], config.MAX_DESC_LEN - len(sufijo)) + sufijo
    detalle = [{"NmbItem": descripcion, "QtyItem": 1, "PrcItem": total}]

    return {
        "vendedor": rut_usuario,
        "Encabezado": {
            "IdDoc": {"TipoDTE": config.TIPO_DTE_AFECTA, "Folio": 1},
            "Emisor": {"RUTEmisor": rut_empresa, "CdgSIISucur": emisor["cdg_sucursal"]},
            "Receptor": receptor or dict(config.RECEPTOR_CONSUMIDOR_FINAL),
        },
        "Detalle": detalle,
        "Meta": {"info_emisor": emisor["info_emisor"]},
    }


# ── Guardado de PDF ───────────────────────────────────────────────────────────
def _insertar_portada(pdf_path) -> None:
    """Antepone la portada (misma de la factura) al PDF de la boleta, in-place.

    Mismo criterio que facturador.py: silencioso si falta pypdf o la portada.
    """
    if not config.INSERTAR_PORTADA:
        return
    try:
        from pypdf import PdfReader, PdfWriter
    except ImportError:
        return
    portada = config.PORTADA_PDF
    if not portada.exists():
        return
    try:
        pdf_path = __import__("pathlib").Path(pdf_path)
        writer = PdfWriter()
        writer.append(PdfReader(str(portada)))
        writer.append(PdfReader(str(pdf_path)))
        tmp = pdf_path.with_suffix(".tmp.pdf")
        with tmp.open("wb") as fp:
            writer.write(fp)
        tmp.replace(pdf_path)
    except Exception as e:
        print(f"  ⚠️ No se pudo anteponer portada: {str(e).splitlines()[0]}")


def _guardar_pdf(data: Dict[str, Any], folio: Any) -> Optional[str]:
    config.PDF_DIR.mkdir(parents=True, exist_ok=True)
    destino = config.PDF_DIR / f"boleta_{config.TIPO_DTE_AFECTA}_folio{folio}_{time.strftime('%Y%m%d_%H%M%S')}.pdf"
    # Preferimos la descarga desde S3: es un %PDF garantizado. El b64 embebido puede
    # traer prefijo data-uri o encoding que corrompe el decode ingenuo → solo fallback.
    url = data.get("pdf_public_url")
    try:
        if url:
            r = requests.get(url, timeout=60)
            r.raise_for_status()
            if r.content[:5] == b"%PDF-":
                destino.write_bytes(r.content)
                _insertar_portada(destino)
                return str(destino)
        b64 = data.get("b64encoded_pdf") or data.get("pdf_base64") or ""
        if "," in b64[:64] and "base64" in b64[:64]:   # prefijo data:...;base64,
            b64 = b64.split(",", 1)[1]
        if b64:
            raw = base64.b64decode(b64)
            destino.write_bytes(raw)
            if raw[:5] != b"%PDF-":
                print(f"  ⚠️ PDF folio {folio} guardado pero no empieza con %PDF (revisar).")
            else:
                _insertar_portada(destino)
            return str(destino)
    except Exception as e:
        print(f"  ⚠️ No se pudo guardar PDF folio {folio}: {str(e).splitlines()[0]}")
    return None


# ── Emisión ───────────────────────────────────────────────────────────────────
def emitir_boleta(items: List[Dict[str, Any]],
                  receptor: Optional[Dict[str, str]] = None,
                  guardar_pdf: bool = True) -> Dict[str, Any]:
    """Emite una boleta afecta (TipoDTE 39) con N ítems. Devuelve dict resultado."""
    ts = time.strftime('%Y-%m-%d %H:%M:%S')
    total = sum(int(round(float(it.get("precio") or it.get("PrcItem") or 0))) *
                int(it.get("cantidad") or it.get("QtyItem") or 1) for it in items)
    try:
        body = construir_body(items, receptor=receptor)
        # Reintento con backoff ante throttling/errores transitorios de API Gateway.
        resp = None
        for intento in range(4):
            resp = signed_request("POST", config.GENERAR_URL, body=body)
            if resp.status_code == 200:
                break
            if resp.status_code in (401, 403):
                # credenciales AWS vencidas → refrescar y reintentar una vez
                from .auth import get_aws_credentials
                get_aws_credentials(force=True)
                continue
            if resp.status_code in (429, 500, 502, 503, 504):
                time.sleep(1.5 * (intento + 1))
                continue
            break
        if resp.status_code != 200:
            return {"estado": "no-emitida", "detalle": f"HTTP {resp.status_code}: {resp.text[:400]}",
                    "total": total, "momento": ts}
        data = resp.json()
        folio = (data.get("folio") or data.get("Folio")
                 or (data.get("Encabezado", {}).get("IdDoc", {}) or {}).get("Folio"))
        pdf_path = _guardar_pdf(data, folio) if guardar_pdf else None
        return {
            "estado": "emitida",
            "folio": folio,
            "tipo_dte": config.TIPO_DTE_AFECTA,
            "total": total,
            "pdf_path": pdf_path,
            "pdf_url": data.get("pdf_public_url"),
            "momento": ts,
        }
    except Exception as e:
        return {"estado": "no-emitida", "detalle": str(e).splitlines()[0],
                "total": total, "momento": ts}


def _boleta_id(b: Dict[str, Any], idx: int) -> str:
    """ID estable de una boleta para resumir (evita re-emitir)."""
    return str(b.get("id") if b.get("id") is not None else idx)


def _cargar_emitidas(resume_path) -> set:
    """Lee el JSONL de resultados previos y devuelve los ids ya emitidos."""
    done = set()
    if not resume_path:
        return done
    try:
        with open(resume_path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                r = json.loads(line)
                if r.get("estado") == "emitida" and r.get("id") is not None:
                    done.add(str(r["id"]))
    except FileNotFoundError:
        pass
    except Exception as e:
        print(f"⚠️ No se pudo leer resume {resume_path}: {str(e).splitlines()[0]}")
    return done


def run_from_data(boletas: List[Dict[str, Any]], workers: int = 5,
                  resume_path: Optional[str] = None,
                  on_result=None) -> List[Dict[str, Any]]:
    """Emite N boletas en paralelo, con reintentos y resumible por id.

    Cada boleta: {'id'?: str, 'items': [{nombre,cantidad,precio}], 'receptor'?: {...}}.
    - workers: emisiones concurrentes (moderado por rate-limit del SII).
    - resume_path: JSONL append-only; en un rerun se saltan las ya 'emitida'.
    Precarga los datos del emisor (1 vez) para no correr N logins/lookups en paralelo.
    """
    if not boletas:
        return []
    _resolver_emisor()  # warm-up serializado del info_emisor + credenciales

    done = _cargar_emitidas(resume_path)
    pendientes = [(i, b) for i, b in enumerate(boletas) if _boleta_id(b, i) not in done]
    total_n = len(boletas)
    if done:
        print(f"↻ Resume: {len(done)} ya emitidas, {len(pendientes)} pendientes de {total_n}.")

    lock = threading.Lock()
    resume_f = open(resume_path, "a", encoding="utf-8") if resume_path else None
    resultados: List[Dict[str, Any]] = []
    hechas = ok = 0

    def _trabajo(idx, b):
        r = emitir_boleta(b["items"], receptor=b.get("receptor"))
        r["id"] = _boleta_id(b, idx)
        return idx, b, r

    try:
        with ThreadPoolExecutor(max_workers=max(1, workers)) as ex:
            futs = [ex.submit(_trabajo, i, b) for i, b in pendientes]
            for fut in as_completed(futs):
                idx, b, r = fut.result()
                with lock:
                    hechas += 1
                    if r["estado"] == "emitida":
                        ok += 1
                    if resume_f:
                        resume_f.write(json.dumps(r, ensure_ascii=False) + "\n")
                        resume_f.flush()
                    resultados.append(r)
                    marca = "✓" if r["estado"] == "emitida" else "✗"
                    print(f"  {marca} [{hechas}/{len(pendientes)}] id={r['id']} "
                          f"folio={r.get('folio')} ${r.get('total')} "
                          f"{'' if r['estado']=='emitida' else r.get('detalle','')[:120]}")
                if on_result:
                    try:
                        on_result(idx, b, r)
                    except Exception as e:
                        print(f"  ⚠️ on_result falló: {str(e).splitlines()[0]}")
    finally:
        if resume_f:
            resume_f.close()
    print(f"\n✔ Emitidas {ok}/{len(pendientes)} (fallidas {len(pendientes)-ok}). "
          f"Resultados en {resume_path or '(sin log)'}")
    return resultados


def _parse_monto(s: str) -> float:
    """Parsea monto en formato chileno: '1.000'→1000, '1.234,56'→1234.56, '2500'→2500."""
    s = re.sub(r"[^\d,.-]", "", str(s or "")).strip()
    if not s:
        return 0.0
    if "," in s:                       # coma = decimal; puntos = miles
        s = s.replace(".", "").replace(",", ".")
    else:                              # sin coma: los puntos son separador de miles
        s = s.replace(".", "")
    try:
        return float(s)
    except ValueError:
        return 0.0


def cargar_boletas_archivo(path: str) -> List[Dict[str, Any]]:
    """Lee boletas desde CSV o JSON.

    JSON: lista de {id?, items:[{nombre,cantidad,precio}], receptor?}.
    CSV : columnas flexibles — 'monto'/'precio' (obligatoria), 'detalle'/'nombre',
          'cantidad' (def 1), 'id' (def nº fila), 'rut_receptor'+'razon_receptor' (opc).
    """
    if path.lower().endswith(".json"):
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, list) else data.get("boletas", [])

    boletas = []
    with open(path, newline="", encoding="utf-8-sig") as f:
        for i, row in enumerate(csv.DictReader(f)):
            row = { (k or "").strip().lower(): (v or "").strip() for k, v in row.items() }
            monto = row.get("monto") or row.get("precio") or row.get("total")
            if not monto:
                continue
            b: Dict[str, Any] = {
                "id": row.get("id") or str(i),
                "items": [{
                    "nombre": row.get("detalle") or row.get("nombre") or row.get("descripcion") or "Venta",
                    "cantidad": int(row.get("cantidad") or 1),
                    "precio": _parse_monto(monto),
                }],
            }
            if row.get("rut_receptor"):
                b["receptor"] = {
                    "RUTRecep": row["rut_receptor"],
                    "RznSocRecep": row.get("razon_receptor") or "Cliente",
                    "DirRecep": row.get("dir_receptor") or "Santiago",
                }
            boletas.append(b)
    return boletas


# ── CLI ───────────────────────────────────────────────────────────────────────
def main():
    ap = argparse.ArgumentParser(description="Emisor de Boletas Electrónicas SII (e-Boleta)")
    ap.add_argument("--file", help="CSV o JSON con las boletas a emitir (bulk)")
    ap.add_argument("--workers", type=int, default=5, help="emisiones concurrentes (def 5)")
    ap.add_argument("--resume", help="ruta JSONL de resultados (resume/idempotencia). "
                                     "Def: junto al --file con sufijo .resultados.jsonl")
    ap.add_argument("--dry-run", action="store_true", help="con --file: solo lista lo que emitiría")
    ap.add_argument("--test", action="store_true", help="emite una boleta de prueba ($1.000)")
    ap.add_argument("--monto", type=int, help="con --test: monto de la boleta de prueba")
    ap.add_argument("--detalle", help="con --test: texto del ítem de prueba")
    ap.add_argument("--inspect", action="store_true", help="muestra el shape del emisor (debug, no emite)")
    ap.add_argument("--login", action="store_true", help="fuerza re-login SII (refresca token)")
    args = ap.parse_args()

    if args.login:
        from .auth import login_sii
        login_sii()
        print("✓ Token federado refrescado.")
        return

    if args.inspect:
        raw = get_emisor_info()
        print(json.dumps(raw, ensure_ascii=False, indent=2)[:4000])
        return

    if args.file:
        boletas = cargar_boletas_archivo(args.file)
        print(f"→ {len(boletas)} boletas leídas de {args.file}")
        if args.dry_run:
            for b in boletas[:20]:
                it = b["items"][0]
                print(f"  id={b.get('id')} ${int(it['precio'])*it['cantidad']:>8} "
                      f"x{it['cantidad']}  {it['nombre'][:60]}")
            if len(boletas) > 20:
                print(f"  … (+{len(boletas)-20} más)")
            print(f"TOTAL a emitir: {len(boletas)} boletas")
            return
        resume = args.resume or (args.file.rsplit(".", 1)[0] + ".resultados.jsonl")
        run_from_data(boletas, workers=args.workers, resume_path=resume)
        return

    if args.test:
        r = emitir_boleta(items=[{
            "nombre": args.detalle or "PRUEBA API",
            "cantidad": 1,
            "precio": args.monto or 1000}])
        print("Resultado:", r)
        return

    ap.print_help()


if __name__ == "__main__":
    sys.exit(main())
