#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Flujo CGI del Facturador v2, por HTTP puro:

  GET  mipeGenFacEx.cgi      → formulario (campos ocultos de sesión)
  POST mipeDisplayPreView.cgi→ vista previa (form PreViewDTE)
  POST mipeGenXMLFirma.cgi   → página de firma (trae el DTE sin firmar)
  POST postFirmaDigital.cgi  → firma CENTRALIZADA server-side → DTE firmado
  POST mipeSendXML.cgi       → EMITE y devuelve el folio

Detalles críticos (descubiertos capturando el tráfico real del portal):
  • nodo='dte:DTE' y nodoId='dte:Documento' (SIN '/' inicial; nodoId es solo el hijo)
  • la clave del certificado va CRUDA (no codificada como entidades)
  • mipeSendXML necesita TAMBIÉN los hidden de firma (nombre/clave/nodo/nodoId/
    nameSpace) además de txtPlainText y txtSignText; sin ellos → "Firma no reconocida"
"""
import html as _html
import re
from html.parser import HTMLParser
from typing import Optional
from urllib.parse import urlencode

from . import config


class _FormParser(HTMLParser):
    """Extrae los campos (name→value) de los formularios de una página."""

    def __init__(self):
        super().__init__()
        self.fields = {}
        self._select = None

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "input":
            n = a.get("name")
            if n and a.get("type") not in ("submit", "button"):
                self.fields[n] = a.get("value", "")
        elif tag == "select":
            self._select = a.get("name")
            if self._select and self._select not in self.fields:
                self.fields[self._select] = ""
        elif tag == "option" and self._select and "selected" in a:
            self.fields[self._select] = a.get("value", "")
        elif tag == "textarea":
            n = a.get("name")
            if n:
                self.fields[n] = ""

    def handle_endtag(self, tag):
        if tag == "select":
            self._select = None


def _post_form(s, url, data, referer=None, timeout=90, charset="ISO-8859-1"):
    """POST de formulario con charset explícito.

    OJO — el portal NO es uniforme:
      • Las páginas del formulario (preview/genXMLFirma/mipeSendXML) trabajan en
        ISO-8859-1: el navegador envía los forms con ese charset.
      • `postFirmaDigital.cgi` en cambio recibe el AJAX con `charset=UTF-8` (así lo
        manda jQuery). Enviarlo en latin-1 hace que los acentos (Í=0xCD) sean UTF-8
        inválido y el CGI los reemplaza por '?', corrompiendo el DTE y rompiendo el
        TIMBRE ("Firma Timbre Electrónico Incorrecta"). Por eso la firma va en UTF-8.
    """
    body = urlencode(data, encoding=charset, errors="xmlcharrefreplace")
    headers = {"Content-Type": f"application/x-www-form-urlencoded; charset={charset}"}
    if referer:
        headers["Referer"] = referer
    return s.post(url, data=body.encode("latin-1"), headers=headers, timeout=timeout)


def _post_latin1(s, url, data, referer=None, timeout=90):
    return _post_form(s, url, data, referer=referer, timeout=timeout, charset="ISO-8859-1")


def _norm_rut(rutdv: str):
    """'76.469.595-K' → ('76469595', 'K')"""
    r = re.sub(r"[.\s]", "", (rutdv or "")).upper()
    if "-" in r:
        num, dv = r.rsplit("-", 1)
    else:
        num, dv = r[:-1], r[-1:]
    return num, dv


def construir_campos(base_fields: dict, receptor: dict, items: list,
                     fecha_emision: Optional[str] = None,
                     forma_pago: str = "credito",
                     referencias: Optional[list] = None) -> dict:
    """Arma el POST del formulario a partir de los campos del form + receptor + ítems.

    `items`: [{'nombre','cantidad','precio_neto'}]  (precio NETO, la factura lleva IVA aparte)
    `referencias`: para Notas de Crédito/Débito (DTE 61/56). Lista de dicts
        {'tpo_doc','folio','fecha','codigo','razon'} — p.ej. anular la factura N° 6869:
        {'tpo_doc':'33','folio':'6869','fecha':'2026-07-30','codigo':'1','razon':'ANULA...'}.
        codigo 1=anula documento, 2=corrige texto, 3=corrige montos.
    """
    rut, dv = _norm_rut(receptor["rut"])

    # GUARD: nunca emitir una factura a nuestro propio RUT (auto-factura)
    emisor_num, _ = _norm_rut(config.RUT_EMPRESA)
    if rut == emisor_num:
        raise ValueError(
            f"Auto-factura bloqueada: el receptor ({receptor['rut']}) es el mismo RUT "
            f"emisor ({config.RUT_EMPRESA}). Facturar a sí mismo puede causar problemas "
            f"tributarios.")

    neto = sum(int(round(i["precio_neto"])) * int(i["cantidad"]) for i in items)
    iva = int(round(neto * config.IVA_TASA / 100))
    total = neto + iva

    d = dict(base_fields)
    d.update({
        # emisor (el JS del portal los rellena en el navegador; acá van explícitos)
        "EFXP_CDG_SII_SUCUR": config.CDG_SII_SUCUR,
        "EFXP_ACTECO": config.ACTECO, "EFXP_ACTECO_SELECT": config.ACTECO,
        "EFXP_DIR_ORIGEN": config.DIR_ORIGEN,
        "EFXP_CMNA_ORIGEN": config.CMNA_ORIGEN,
        "EFXP_CIUDAD_ORIGEN": config.CIUDAD_ORIGEN,
        # contacto del emisor: el form trae otros valores por defecto y hay que
        # sobreescribirlos para que la factura salga con los datos correctos
        "EFXP_EMAIL_EMISOR": config.EMAIL_EMISOR,
        "EFXP_FONO_EMISOR": config.FONO_EMISOR,
        # tipo de venta/compra: sin esto el DTE sale sin TpoTranVenta/TpoTranCompra
        "EFXP_TIPOVENTA_SELECT": "1", "EFXP_TIPOCOMPRA_SELECT": "1",
        # receptor
        "EFXP_RUT_RECEP": rut, "EFXP_DV_RECEP": dv,
        "EFXP_RZN_SOC_RECEP": receptor.get("razon_social", "")[:100],
        # El SII exige giro/dirección/comuna/ciudad del receptor. Si la orden no los
        # trae, se usa el mismo placeholder que el facturador legacy para no abortar.
        "EFXP_GIRO_RECEP": (receptor.get("giro") or config.PLACEHOLDER_RECEPTOR)[:40],
        "EFXP_DIR_RECEP": (receptor.get("direccion") or config.PLACEHOLDER_RECEPTOR)[:70],
        "EFXP_CMNA_RECEP": (receptor.get("comuna") or config.PLACEHOLDER_RECEPTOR)[:20],
        "EFXP_CIUDAD_RECEP": (receptor.get("ciudad") or receptor.get("comuna")
                              or config.PLACEHOLDER_RECEPTOR)[:20],
        # totales
        "EFXP_SUBTOTAL": str(neto), "EFXP_MNT_NETO": str(neto),
        "EFXP_TASA_IVA": str(config.IVA_TASA), "EFXP_IVA": str(iva),
        "EFXP_MNT_TOTAL": str(total),
        "EFXP_MNT_DESC": "0", "EFXP_PCT_DESC": "0",
        "CANT_DET": str(len(items)),
    })
    # Fecha de emisión: el formulario la rellena por JS en el navegador, así que si
    # no viene en los campos parseados hay que ponerla (si no: "Debe ingresar el
    # campo : Fecha emision").
    if fecha_emision:
        d["EFXP_FCH_EMIS"] = fecha_emision
    elif not d.get("EFXP_FCH_EMIS"):
        import datetime as _dt
        d["EFXP_FCH_EMIS"] = _dt.date.today().strftime("%Y-%m-%d")
    # Forma de pago (queda impresa en la factura: "Contado"/"Crédito")
    _mapa_pago = {"contado": "1", "credito": "2", "crédito": "2", "sin costo": "3"}
    d["EFXP_FMA_PAGO"] = _mapa_pago.get(str(forma_pago or "credito").lower(), "2")

    for idx, it in enumerate(items, 1):
        p = int(round(it["precio_neto"])); q = int(it["cantidad"])
        # Igual que el legacy: en el campo "nombre" va la REFERENCIA de la orden
        # (queda como código en la factura) y el producto va en la descripción
        # extendida. Así la factura se puede cruzar con la orden de ML.
        ref = str(it.get("referencia") or "")[:25]
        d[f"EFXP_NMB_{idx:02d}"] = ref or str(it["nombre"])[:50]
        if ref:
            d[f"EFXP_DSC_ITEM_{idx:02d}"] = str(it["nombre"])[:120]
        d[f"EFXP_QTY_{idx:02d}"] = str(q)
        d[f"EFXP_UNMD_{idx:02d}"] = it.get("unidad", "unid")
        d[f"EFXP_PRC_{idx:02d}"] = str(p)
        d[f"EFXP_SUBT_{idx:02d}"] = str(p * q)

    # Bloque de REFERENCIAS (NC/ND). El portal lo activa con REF_SI_NO="SiChecked" y
    # numera las filas _001.._003 (EFXP_TPO_DOC_REF_00 + i). Los nombres y reglas salen
    # de validaFacEx.js: fila 1 exige tipo doc + folio + fecha válida; IND_GLOBAL solo
    # admite '1' (referencia global, que fuerza folio 0) — para anular un folio concreto
    # va vacío.
    if referencias:
        d["REF_SI_NO"] = "SiChecked"
        for i, ref in enumerate(referencias[:3], 1):
            d[f"EFXP_TPO_DOC_REF_00{i}"] = str(ref.get("tpo_doc", ""))
            d[f"EFXP_IND_GLOBAL_00{i}"] = str(ref.get("ind_global", ""))
            d[f"EFXP_FOLIO_REF_00{i}"] = str(ref.get("folio", ""))
            d[f"EFXP_FCH_REF_00{i}"] = str(ref.get("fecha", ""))
            d[f"EFXP_CODIGO_REF_00{i}"] = str(ref.get("codigo", ""))
            d[f"EFXP_RAZON_REF_00{i}"] = str(ref.get("razon", ""))[:90]
    return d


def lookup_receptor(s, base_fields: dict, rut: str, dv: str) -> dict:
    """Pregunta al SII los datos del receptor a partir del RUT.

    Replica lo que hace el portal al salir del campo DV (`enviaCGI`): NO es un AJAX,
    sino un re-POST del formulario a `mipeGenFacEx.cgi?`, que el SII devuelve con la
    razón social / giro / dirección ya completados desde su registro de contribuyentes.
    Devuelve {'razon_social','giro','direccion','comuna','ciudad'} (vacíos si no hay).
    """
    d = dict(base_fields)
    d["EFXP_RUT_RECEP"] = rut
    d["EFXP_DV_RECEP"] = dv
    r = _post_latin1(s, f"{config.BASE}/mipeGenFacEx.cgi?", d,
                     referer=config.FORM_URL, timeout=90)
    fp = _FormParser(); fp.feed(r.text)
    f = fp.fields
    return {
        "razon_social": (f.get("EFXP_RZN_SOC_RECEP") or "").strip(),
        "giro":         (f.get("EFXP_GIRO_RECEP") or "").strip(),
        "direccion":    (f.get("EFXP_DIR_RECEP") or "").strip(),
        "comuna":       (f.get("EFXP_CMNA_RECEP") or "").strip(),
        "ciudad":       (f.get("EFXP_CIUDAD_RECEP") or "").strip(),
        "_campos":      f,     # el form ya viene con el estado del SII
    }


def flujo_hasta_firma(s, receptor: dict, items: list,
                      fecha_emision: Optional[str] = None,
                      usar_lookup: bool = True,
                      forma_pago: str = "credito",
                      ptdc_codigo: int = 33,
                      referencias: Optional[list] = None) -> str:
    """GET form → (lookup del receptor) → POST preview → POST genXMLFirma.

    ptdc_codigo=33 factura, 61 nota de crédito (requiere `referencias`).
    """
    # Reusa el formulario que ya bajó la validación de sesión (auth._sesion_viva):
    # es la request más lenta del portal, así no se pide dos veces. Se consume una
    # sola vez para que la siguiente factura del lote traiga campos frescos. Para NC
    # (PTDC_CODIGO≠33) hay que pedir SU formulario, no el de factura cacheado.
    if ptdc_codigo != 33:
        html = s.get(f"{config.BASE}/mipeGenFacEx.cgi?PTDC_CODIGO={ptdc_codigo}",
                     timeout=90).text
    else:
        html = getattr(s, "_form_html", None)
        if html:
            s._form_html = None
        else:
            html = s.get(config.FORM_URL, timeout=90).text
    if "EFXP_RUT_RECEP" not in html:
        raise RuntimeError("La sesión no devolvió el formulario de factura (¿expiró?).")
    fp = _FormParser(); fp.feed(html)
    base = fp.fields

    receptor = dict(receptor)
    if usar_lookup:
        # La razón social la DEDUCE el SII desde el RUT: es su dato autoritativo,
        # así que manda sobre lo que traiga la orden (que puede ser un nick de ML).
        rut_l, dv_l = _norm_rut(receptor["rut"])
        try:
            datos = lookup_receptor(s, base, rut_l, dv_l)
            if datos.get("_campos"):
                base = datos["_campos"]
            for k in ("razon_social", "giro", "direccion", "comuna", "ciudad"):
                if datos.get(k):
                    receptor[k] = datos[k]
        except Exception:
            pass   # si el lookup falla se sigue con los datos de la orden

    data = construir_campos(base, receptor, items, fecha_emision, forma_pago,
                            referencias=referencias)
    pr = _post_latin1(s, config.PREVIEW_URL, data, referer=config.FORM_URL, timeout=60)
    if "PreViewDTE" not in pr.text:
        alerta = re.search(r"alert\('([^']+)'\)", pr.text)
        raise RuntimeError(
            f"El SII no avanzó a la vista previa: "
            f"{alerta.group(1)[:300] if alerta else pr.text[:200]}")

    fp2 = _FormParser(); fp2.feed(pr.text)
    sign_data = {k: v for k, v in fp2.fields.items()
                 if k not in ("btnSign", "btnCorregir")}
    fr = _post_latin1(s, config.XMLFIRMA_URL, sign_data,
                      referer=config.PREVIEW_URL, timeout=90)
    if "txtPlainText" not in fr.text:
        raise RuntimeError("No se obtuvo la página de firma (sin txtPlainText).")
    return fr.text


def firmar(s, firma_html: str) -> tuple:
    """Firma CENTRALIZADA del DTE. Devuelve (dato_plano, dato_firmado, certId)."""
    mp = re.search(r'name="txtPlainText"[^>]*>(.*?)</textarea>', firma_html, re.S)
    if not mp:
        raise RuntimeError("No se encontró el XML sin firmar (txtPlainText).")
    # OJO: el contenido del textarea ya es el XML tal cual debe firmarse. NO aplicar
    # html.unescape(): rompería las entidades legítimas del XML — un receptor con "&"
    # en la razón social ("B & S INVERSIONES SPA") viene como `&amp;` y des-escaparlo
    # deja un "&" suelto → XML inválido → postFirmaDigital responde vacío.
    dato = mp.group(1).strip()

    rut = s.cookies.get("NETSCAPE_LIVEWIRE.rut")
    dv = s.cookies.get("NETSCAPE_LIVEWIRE.dv")
    cert = s.get(f"{config.CERT_URL}?rut={rut}&dv={dv}", timeout=30)
    try:
        certs = cert.json()
    except Exception:
        raise RuntimeError(f"getCertDigital no devolvió JSON: {cert.text[:200]}")
    if not certs:
        raise RuntimeError(f"El RUT {rut}-{dv} no tiene certificado centralizado en el SII.")
    cert_id = certs[0].get("nombre", "")

    if not config.SII_CLAVE_FIRMA:
        raise RuntimeError("Falta SII_CLAVE_FIRMA en .env (clave del certificado).")

    payload = {
        "nombre": cert_id, "dato": dato, "rut": rut, "dv": dv,
        "clave": config.SII_CLAVE_FIRMA,          # CRUDA
        "nodo": config.FIRMA_NODO,                # 'dte:DTE'
        "nodoId": config.FIRMA_NODO_ID,           # 'dte:Documento'
        "nameSpace": config.FIRMA_NAMESPACE,
    }
    # UTF-8: postFirmaDigital.cgi recibe el AJAX del portal con charset=UTF-8. En
    # latin-1 los acentos de la razón social (Í=0xCD) llegan como UTF-8 inválido y el
    # CGI los sustituye por '?', rompiendo el TIMBRE ("Firma Timbre Electrónico
    # Incorrecta"). Ver nota en _post_form.
    fr = _post_form(s, config.FIRMA_URL, payload, referer=config.XMLFIRMA_URL,
                    charset="utf-8")
    firmado = fr.text
    if "<Signature" not in firmado:
        raise RuntimeError(
            f"El SII no firmó el documento (¿clave del certificado incorrecta?). "
            f"Respuesta: {firmado[:200]!r}")
    return dato, firmado, cert_id


def enviar(s, firma_html: str, dato: str, firmado: str, cert_id: str) -> dict:
    """POST final a mipeSendXML.cgi → emite. Devuelve {'folio', 'ok', 'html'}."""
    fp = _FormParser(); fp.feed(firma_html)
    campos = {k: v for k, v in fp.fields.items() if k not in ("btnSign", "btnCorregir")}
    campos["txtPlainText"] = dato
    campos["txtSignText"] = firmado
    # Hidden que el JS del portal inyecta en frmSign — imprescindibles: sin ellos el
    # SII responde "Firma no reconocida" aunque la firma sea válida.
    campos.update({
        "nombre": cert_id, "clave": config.SII_CLAVE_FIRMA,
        "nodo": config.FIRMA_NODO, "nodoId": config.FIRMA_NODO_ID,
        "nameSpace": config.FIRMA_NAMESPACE,
    })

    er = _post_latin1(s, config.SENDXML_URL, campos, referer=config.XMLFIRMA_URL)
    texto = er.text
    alerta = re.search(r"alert\('([^']+)'\)", texto)
    if alerta and "no reconocida" in alerta.group(1).lower():
        raise RuntimeError(f"El SII rechazó el envío: {alerta.group(1)}")

    folio = None
    m = re.search(r"N[°ºB&][^0-9]{0,12}(\d{2,10})", texto)
    if m:
        folio = m.group(1)
    exito = "EXITOSAMENTE" in texto.upper() or folio is not None
    if not exito:
        raise RuntimeError(
            f"Respuesta inesperada del SII: "
            f"{alerta.group(1)[:200] if alerta else texto[:200]}")
    return {"folio": folio, "ok": True, "html": texto}
