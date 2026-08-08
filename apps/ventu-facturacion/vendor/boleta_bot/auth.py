#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Autenticación e-Boleta: login SII (clave) → token federado Cognito → credenciales
AWS temporales (SigV4). Ver docs/eboleta_api_reverse.md.

Estrategia híbrida: Playwright SOLO para el login con clave (lo único que el SII
no expone trivialmente por HTTP), del que extraemos el token federado que la SPA
deja en localStorage['aws-amplify-federatedInfo']. Todo lo demás —canje del token
por credenciales AWS y la emisión— es HTTP puro.

Dos niveles de cache:
  • Token federado (dura ~12 h): persistido en .auth_cache.json. Mientras siga
    vigente NO se vuelve a abrir el navegador.
  • Credenciales AWS (duran ~1 h): se re-piden con GetCredentialsForIdentity usando
    el token federado, sin re-login, hasta que el token de 12 h venza.
"""
import json
import time
import datetime as dt
from typing import Dict, Any, Optional

import requests

from . import config


# ── Cache en disco del token federado ─────────────────────────────────────────
def _load_cache() -> Optional[Dict[str, Any]]:
    try:
        data = json.loads(config.AUTH_CACHE.read_text())
    except Exception:
        return None
    # expires_at viene en ms epoch desde la SPA
    exp_ms = data.get("expires_at") or 0
    # margen de 5 min
    if exp_ms and (exp_ms / 1000.0) > (time.time() + 300):
        return data
    return None


def _save_cache(info: Dict[str, Any]) -> None:
    try:
        config.AUTH_CACHE.write_text(json.dumps(info, ensure_ascii=False))
        config.AUTH_CACHE.chmod(0o600)
    except Exception:
        pass


# ── Login SII vía Playwright → token federado ─────────────────────────────────
def login_sii(headless: bool = False, manual_timeout: int = 200,
              verbose: bool = True) -> Dict[str, Any]:
    """Abre eboleta.sii.cl, ingresa RUT+clave y extrae el token federado.

    Autocompleta el formulario de Clave Tributaria; si los selectores cambian o
    hay un paso extra (p.ej. captcha), deja el navegador abierto y sondea
    localStorage hasta `manual_timeout` para que el usuario complete a mano.
    """
    from playwright.sync_api import sync_playwright

    rut = config.SII_RUT_USUARIO.strip()
    clave = config.SII_CLAVE
    if not rut or not clave:
        raise RuntimeError(
            "Faltan credenciales SII. Define SII_RUT_USUARIO y SII_CLAVE en .env")

    def _read_federated(page) -> Optional[Dict[str, Any]]:
        try:
            raw = page.evaluate(
                "() => localStorage.getItem('aws-amplify-federatedInfo')")
        except Exception:
            return None
        if not raw:
            return None
        try:
            info = json.loads(raw)
        except Exception:
            return None
        if info.get("token") and info.get("identity_id"):
            return info
        return None

    with sync_playwright() as p:
        # headless=True hace que el SII sirva un 404 (detección anti-bot); el login
        # SIEMPRE corre en ventana visible. La flag AutomationControlled + UA real
        # evitan que la página de autenticación OAuth se niegue a renderizar.
        browser = p.chromium.launch(
            headless=False,
            args=["--disable-blink-features=AutomationControlled"])
        ctx = browser.new_context(user_agent=(
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"))
        page = ctx.new_page()
        if verbose:
            print("→ Abriendo eboleta.sii.cl para login…")
        page.goto(config.LOGIN_URL, wait_until="domcontentloaded")

        # Autocompletado del form OAuth "Autenticación con Clave Tributaria".
        # Selectores reales (jun-2026): #inputRut / #inputPass / #bt_ingresar.
        try:
            page.wait_for_selector("#inputRut", timeout=20000)
            page.fill("#inputRut", rut)
            page.fill("#inputPass", clave)
            page.click("#bt_ingresar")
            if verbose:
                print("  ✓ Clave enviada, esperando token federado "
                      "(si aparece un challenge de correo/2FA, complétalo en la ventana)…")
        except Exception as e:
            if verbose:
                print(f"  ⚠️ Autocompletado no aplicó ({str(e).splitlines()[0]}); "
                      f"completa el login manualmente en la ventana.")

        # Sondeo activo del token federado (post-redirect a eboleta.sii.cl).
        info = None
        end = time.time() + manual_timeout
        while time.time() < end:
            # Asegurar que estamos en el origen de eboleta para leer su localStorage.
            info = _read_federated(page)
            if info:
                break
            time.sleep(1.5)

        ctx.close()
        browser.close()

    if not info:
        raise RuntimeError(
            "No se obtuvo el token federado. ¿Login incompleto o selectores del "
            "SII cambiaron? Reintenta con headless=False y completa a mano.")
    if verbose:
        print(f"  ✓ Token federado obtenido (usuario {info.get('user',{}).get('username')})")
    _save_cache(info)
    return info


def get_federated_info(force_login: bool = False, headless: bool = False) -> Dict[str, Any]:
    """Devuelve el token federado vigente (de cache si sirve, si no re-login)."""
    if not force_login:
        cached = _load_cache()
        if cached:
            return cached
    return login_sii(headless=headless)


# ── Canje del token por credenciales AWS temporales ───────────────────────────
_creds_cache: Dict[str, Any] = {}


def _parse_aws_dt(val) -> float:
    """Cognito devuelve Expiration como epoch (num) o ISO. Normaliza a epoch float."""
    if isinstance(val, (int, float)):
        return float(val)
    try:
        return dt.datetime.fromisoformat(str(val).replace("Z", "+00:00")).timestamp()
    except Exception:
        return time.time() + 3000  # fallback conservador ~50 min


def get_aws_credentials(force: bool = False) -> Dict[str, str]:
    """GetCredentialsForIdentity → {AccessKeyId, SecretKey, SessionToken}.

    Cachea en memoria hasta ~5 min antes de la expiración. Si el token federado
    de 12 h venció, get_federated_info() relanza el login automáticamente.
    """
    now = time.time()
    if not force and _creds_cache.get("expiration", 0) > now + 300:
        return _creds_cache["creds"]

    info = get_federated_info()
    payload = {
        "IdentityId": info["identity_id"],
        "Logins": {config.COGNITO_LOGIN_PROVIDER: info["token"]},
    }
    resp = requests.post(
        config.COGNITO_HOST,
        data=json.dumps(payload),
        headers={
            "Content-Type": "application/x-amz-json-1.1",
            "X-Amz-Target": "AWSCognitoIdentityService.GetCredentialsForIdentity",
        },
        timeout=30,
    )
    if resp.status_code != 200:
        # Token federado probablemente vencido → forzar re-login una vez.
        if not force:
            login_sii()
            return get_aws_credentials(force=True)
        raise RuntimeError(
            f"GetCredentialsForIdentity falló ({resp.status_code}): {resp.text[:300]}")

    data = resp.json()
    c = data["Credentials"]
    creds = {
        "access_key": c["AccessKeyId"],
        "secret_key": c["SecretKey"],
        "token": c["SessionToken"],
    }
    _creds_cache["creds"] = creds
    _creds_cache["expiration"] = _parse_aws_dt(c.get("Expiration"))
    return creds
