"""Avisos al cliente por correo, a través de Ventu Correo.

Esta app solo pone el texto: el marco, el remitente y la clave de Resend viven
en Ventu Correo (`POST /enviar` con `aviso`). Un aviso nunca hace fallar la
operación que lo dispara: si no sale, se informa y el staff avisa a mano.
"""

from __future__ import annotations

import hashlib
import logging
from typing import Optional

import httpx

from . import config
from .company import rut as rut_mod
from .company.models import Company

logger = logging.getLogger("ventu-b2b.avisos")

# Ventu Correo espera hasta 10 s a Resend: cortar antes daría por fallido un
# correo que quizás salió.
TIMEOUT = 15


def _publicar(url: str, json: dict, headers: dict) -> httpx.Response:
    return httpx.post(url, json=json, headers=headers, timeout=TIMEOUT)


def _enviar(cuerpo: dict) -> dict:
    """`{"enviado": bool, "id"|"motivo": str}`; nunca lanza."""
    if not config.CORREO_URL or not config.CORREO_SERVICE_TOKEN:
        logger.warning("(b2b) CORREO_URL o CORREO_SERVICE_TOKEN vacíos: aviso %s no enviado",
                       cuerpo.get("etiqueta"))
        return {"enviado": False, "motivo": "correo no configurado"}
    url = f"{config.CORREO_URL}/enviar"
    cabeceras = {"Authorization": f"Bearer {config.CORREO_SERVICE_TOKEN}"}
    for intento in (1, 2):
        try:
            resp = _publicar(url, cuerpo, cabeceras)
            break
        except httpx.ConnectError as exc:
            # Ventu Correo reiniciando (deploy): un segundo intento suele
            # alcanzarlo. La clave de idempotencia impide el duplicado.
            if intento == 2:
                logger.error("(b2b) Ventu Correo inalcanzable: %s", exc)
                return {"enviado": False, "motivo": "servicio de correo inalcanzable"}
        except httpx.TimeoutException:
            logger.error("(b2b) Ventu Correo sin respuesta en %ss", TIMEOUT)
            return {"enviado": False, "motivo": "sin respuesta del servicio de correo; "
                                                "puede haber salido"}
        except httpx.HTTPError as exc:
            logger.error("(b2b) fallo al pedir el aviso: %s", exc)
            return {"enviado": False, "motivo": "error al contactar el servicio de correo"}
    try:
        datos = resp.json()
    except ValueError:
        datos = {}
    if resp.status_code == 200 and datos.get("enviado"):
        return {"enviado": True, "id": datos.get("id")}
    motivo = datos.get("error") or datos.get("detail") or f"HTTP {resp.status_code}"
    logger.error("(b2b) aviso %s no enviado: %s", cuerpo.get("etiqueta"), motivo)
    return {"enviado": False, "motivo": str(motivo)}


def empresa_aprobada(user_id: str, email: Optional[str], nombre: Optional[str],
                     company: Company, ahora: str) -> dict:
    """Avisa al cliente que su empresa ya puede comprar en la tienda B2B."""
    if not email:
        return {"enviado": False, "motivo": "el usuario no tiene correo"}
    try:
        rut = rut_mod.formatear(company.rut)
    except ValueError:  # no debería pasar: la Company guarda la forma canónica
        rut = company.rut
    aviso = {
        "nombre": nombre or None,
        "parrafos": [
            f"Revisamos los datos de {company.razon_social} "
            f"(RUT {rut}) y la cuenta quedó habilitada "
            "para comprar en la tienda para empresas de Ventu.",
            "Ya puedes ver los precios para empresas y hacer tu pedido.",
        ],
        "pie": "Recibes este correo porque registraste una empresa en Ventu.",
    }
    if config.STOREFRONT_URL:
        aviso["boton"] = {"texto": "Ir a la tienda",
                          "url": f"{config.STOREFRONT_URL}/es/{company.nivel_precio}"}
    clave = hashlib.sha256(f"{user_id}|{ahora}".encode()).hexdigest()[:32]
    return _enviar({
        "para": email,
        "asunto": "Tu empresa ya puede comprar en Ventu",
        "aviso": aviso,
        "etiqueta": "empresa-aprobada",
        "clave_idempotencia": f"empresa-aprobada-{clave}",
    })
