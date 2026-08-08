#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Autenticación del Facturador v2: login SII con clave tributaria (Playwright) →
cookies → requests.Session para todo el flujo CGI.

Playwright se usa SOLO para el login (headless da 404 por detección anti-bot).
Las cookies se cachean; mientras la sesión del SII viva no se reabre el navegador.
"""
import json
import os
import time
from typing import Optional

import requests

from . import config


def _forzar_latin1(r, *args, **kwargs):
    """Hook: el portal del SII trabaja en ISO-8859-1 pero muchas respuestas no
    declaran charset, y requests entonces adivina mal (chardet) y corrompe los
    acentos (Í→?, ñ→?). Eso rompía el TIMBRE del DTE: el SII lo firma sobre la razón
    social real y nosotros reenviábamos el documento con la razón social corrupta
    → "Firma Timbre Electrónico Incorrecta". Forzar latin-1 preserva los bytes."""
    r.encoding = "ISO-8859-1"


def _nueva_sesion() -> requests.Session:
    s = requests.Session()
    s.headers["User-Agent"] = config.UA
    s.hooks["response"].append(_forzar_latin1)
    return s


def _session_desde_cookies(cookies) -> requests.Session:
    s = _nueva_sesion()
    for c in cookies:
        s.cookies.set(c["name"], c["value"],
                      domain=c.get("domain"), path=c.get("path", "/"))
    return s


def login_http(verbose: bool = True) -> Optional[requests.Session]:
    """Login 100% HTTP (sin navegador) contra el formulario legacy del SII.

    El portal MiPyme usa el login clásico de zeusr: un form POST a
    /cgi_AUT2000/CAutInicio.cgi con rut, dv, clave y `referencia` (la URL destino
    tal como la arma el JS: los segmentos del query string reunidos con '?').
    Devuelve la sesión autenticada, o None si no logró entrar.
    """
    if not config.SII_RUT_USUARIO or not config.SII_CLAVE:
        raise RuntimeError("Faltan SII_RUT_USUARIO / SII_CLAVE en .env")

    rut_full = config.SII_RUT_USUARIO.replace(".", "").strip().upper()
    rut, dv = (rut_full.split("-") + [""])[:2] if "-" in rut_full else (rut_full[:-1], rut_full[-1])

    s = _nueva_sesion()
    destino = config.SEL_EMPRESA_URL

    # `referencia` se arma EXACTAMENTE como en AutAll.js:
    #   var referencia='http://www.sii.cl'
    #   if (arr.length>1) referencia = arr[1]
    #   if (arr.length>2) referencia = arr[1]+'?'+arr[2]
    # donde arr = location.split('?'). O sea: SIN '?' inicial (mi versión anterior
    # le anteponía uno y el SII respondía "no se puede responder a sus requerimientos").
    login_url = ("https://zeusr.sii.cl/AUT2000/InicioAutenticacion/"
                 f"IngresoRutClave.html?{destino}")
    arr = login_url.split("?")
    referencia = "http://www.sii.cl"
    if len(arr) > 1 and arr[1]:
        referencia = arr[1]
    if len(arr) > 2 and arr[2]:
        referencia = arr[1] + "?" + arr[2]

    if verbose:
        print("→ Login SII (HTTP, sin navegador)…")
    # el GET deja las cookies iniciales (TS…) que el CGI espera en el POST
    s.get(login_url, timeout=30)
    r = s.post("https://zeusr.sii.cl/cgi_AUT2000/CAutInicio.cgi",
               data={"rut": rut.lstrip("0"), "dv": dv, "referencia": referencia,
                     "411": "", "rutcntr": rut_full, "clave": config.SII_CLAVE},
               headers={"Referer": login_url,
                        "Origin": "https://zeusr.sii.cl",
                        "Content-Type": "application/x-www-form-urlencoded"},
               timeout=60, allow_redirects=True)
    if r.status_code != 200:
        if verbose:
            print(f"  ✗ login HTTP status {r.status_code}")
        return None

    # seleccionar la empresa (el portal exige elegir con qué RUT se opera)
    s.post(config.SEL_EMPRESA_URL.split("?")[0],
           data={"RUT_EMP": config.RUT_EMPRESA,
                 "DESDE_DONDE_URL": "OPCION=33&TIPO=4"},
           headers={"Referer": config.SEL_EMPRESA_URL}, timeout=60)

    if _sesion_viva(s):
        if verbose:
            print(f"  ✓ sesión HTTP iniciada ({len(s.cookies)} cookies)")
        try:
            cookies = [{"name": c.name, "value": c.value, "domain": c.domain,
                        "path": c.path} for c in s.cookies]
            config.COOKIE_CACHE.write_text(json.dumps(cookies))
            config.COOKIE_CACHE.chmod(0o600)
        except Exception:
            pass
        return s
    if verbose:
        print("  ✗ el login HTTP no dejó sesión válida")
    return None


def login(verbose: bool = True) -> list:
    """Abre el portal, entra con RUT+clave, selecciona la empresa y devuelve cookies."""
    from playwright.sync_api import sync_playwright

    if not config.SII_RUT_USUARIO or not config.SII_CLAVE:
        raise RuntimeError("Faltan SII_RUT_USUARIO / SII_CLAVE en .env")

    with sync_playwright() as p:
        # HEADLESS por defecto: el portal MiPyme usa el login legacy (zeusr), que sí
        # carga headless. (El 404 anti-bot en headless era de la página OAuth nueva
        # que usa e-Boleta, no esta.) Se puede forzar ventana con SII_HEADFUL=1.
        _headless = os.getenv("SII_HEADFUL", "") != "1"
        b = p.chromium.launch(headless=_headless,
                              args=["--disable-blink-features=AutomationControlled"])
        ctx = b.new_context(user_agent=config.UA)
        pg = ctx.new_page()
        if verbose:
            print("→ Login SII…")
        pg.goto(config.SEL_EMPRESA_URL, wait_until="domcontentloaded")
        # El SII sirve DOS páginas de login distintas según el flujo:
        #   • moderna (clave.w.sii.cl/oauthsii): #inputRut / #inputPass
        #   • legacy  (zeusr.sii.cl/AUT2000):    #rutcntr / #clave
        # Probamos ambas para no depender de cuál toque.
        try:
            pg.wait_for_selector("#inputRut, #rutcntr, select[name=RUT_EMP]", timeout=25000)
        except Exception:
            pass
        variantes = [("#inputRut", "#inputPass"), ("#rutcntr", "#clave")]
        for sel_rut, sel_pass in variantes:
            if pg.query_selector(sel_rut):
                if verbose:
                    print(f"  · login con selectores {sel_rut}/{sel_pass}")
                pg.fill(sel_rut, config.SII_RUT_USUARIO)
                pg.fill(sel_pass, config.SII_CLAVE)
                for btn in ("#bt_ingresar", "button[type=submit]", "input[type=submit]"):
                    if pg.query_selector(btn):
                        pg.click(btn)
                        break
                break
        # selección de empresa
        try:
            pg.wait_for_selector("select[name=RUT_EMP]", timeout=120000)
        except Exception:
            # Diagnóstico: dejar evidencia de qué está mostrando el SII
            try:
                shot = config.BASE_DIR.parent / "_scratch_login_fallo.png"
                pg.screenshot(path=str(shot))
                txt = pg.inner_text("body")[:400].replace("\n", " | ")
                print(f"  ✗ No apareció el selector de empresa.\n"
                      f"    URL: {pg.url}\n    Pantalla: {txt}\n    Captura: {shot}")
            except Exception:
                pass
            ctx.close(); b.close()
            raise
        pg.select_option("select[name=RUT_EMP]", config.RUT_EMPRESA)
        pg.click("form button, form input[type=submit]")
        pg.wait_for_url("**/mipeGenFacEx.cgi**", timeout=60000)
        time.sleep(1.5)
        cookies = ctx.cookies()
        if verbose:
            print(f"  ✓ sesión iniciada ({len(cookies)} cookies)")
        ctx.close(); b.close()

    try:
        config.COOKIE_CACHE.write_text(json.dumps(cookies))
        config.COOKIE_CACHE.chmod(0o600)
    except Exception:
        pass
    return cookies


def _sesion_viva(s: requests.Session) -> bool:
    """La sesión sirve si el formulario de factura responde con el form real.

    Guarda el HTML en `s._form_html` para que el flujo de emisión lo REUSE en vez de
    volver a pedirlo: es la request más lenta del portal (se han visto 30-60 s cuando
    el SII anda cargado) y pedirla dos veces duplicaba ese costo por factura.
    """
    try:
        r = s.get(config.FORM_URL, timeout=90)
        ok = r.status_code == 200 and "EFXP_RUT_RECEP" in r.text
        if ok:
            s._form_html = r.text
        return ok
    except Exception:
        return False


def get_session(forzar_login: bool = False, permitir_navegador: bool = True
                ) -> requests.Session:
    """Devuelve una requests.Session autenticada.

    Orden: cookies cacheadas → login HTTP (headless total) → Playwright (respaldo).
    Con permitir_navegador=False nunca abre navegador (modo 100% headless estricto).
    """
    if not forzar_login and config.COOKIE_CACHE.exists():
        try:
            s = _session_desde_cookies(json.loads(config.COOKIE_CACHE.read_text()))
            if _sesion_viva(s):
                return s
        except Exception:
            pass

    s = login_http()
    if s is not None:
        return s

    if not permitir_navegador:
        raise RuntimeError(
            "El login HTTP falló y el modo headless estricto no permite abrir el "
            "navegador. Revisa SII_RUT_USUARIO / SII_CLAVE.")
    return _session_desde_cookies(login())
