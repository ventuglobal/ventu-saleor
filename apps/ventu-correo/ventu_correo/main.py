"""Ventu Correo: envío de correos para todo el proyecto, por Resend.

Concentra en un servicio la clave de Resend, el remitente y las plantillas, en
vez de repetirlos en cada app. Dos entradas:

  - POST /enviar           → para los demás servicios (Bearer CORREO_SERVICE_TOKEN)
  - POST /webhooks/saleor  → correos de cuenta que pide Saleor (firma JWS)

Además, como Saleor App:
  - GET  /manifest         → permisos y webhooks de la app
  - POST /register         → Saleor entrega su token al instalar (no se usa)
  - GET  /health
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import logging
from typing import List, Optional, Union
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from . import config, plantillas, resend, saleor_firma

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("ventu.correo")


# Tope de adjuntos de una solicitud, ya decodificados. Resend acepta 40 MB por
# correo; se deja holgura para el base64 y el resto del cuerpo.
_ADJUNTOS_MAX_BYTES = 25 * 1024 * 1024


# ── autenticación ──

def _requiere_servicio(authorization: Optional[str] = Header(default=None)) -> None:
    if config.AUTH_ABIERTA:
        return
    if not config.SERVICE_TOKEN:
        raise HTTPException(503, "CORREO_SERVICE_TOKEN no configurado")
    presentado = (authorization or "").removeprefix("Bearer ").strip()
    # Se comparan bytes: compare_digest con str rechaza lo que no es ASCII.
    if not presentado or not hmac.compare_digest(presentado.encode(),
                                                 config.SERVICE_TOKEN.encode()):
        raise HTTPException(401, "token inválido")


def _avisar_configuracion() -> None:
    if not config.RESEND_API_KEY or not config.MAIL_FROM:
        logger.error("(correo) RESEND_API_KEY o MAIL_FROM vacíos: no se enviará ningún correo")
    if not config.SERVICE_TOKEN and not config.AUTH_ABIERTA:
        logger.warning("(correo) CORREO_SERVICE_TOKEN vacío: /enviar responde 503")
    if not config.SALEOR_API_URL:
        logger.warning("(correo) SALEOR_API_URL vacío: se rechazan los webhooks de Saleor")


@asynccontextmanager
async def _ciclo(_app):
    _avisar_configuracion()
    yield


app = FastAPI(title="Ventu Correo", version="0.1.0", lifespan=_ciclo)


@app.get("/health")
def health() -> dict:
    # Solo si está configurado, nunca los valores.
    return {
        "status": "ok",
        "resend": bool(config.RESEND_API_KEY),
        "remitente": bool(config.MAIL_FROM),
        "saleor": bool(config.SALEOR_API_URL),
    }


# ── envío para los demás servicios ──

class AdjuntoIn(BaseModel):
    nombre: str = Field(min_length=1, max_length=200)
    contenido_b64: str
    tipo: Optional[str] = None


class BotonIn(BaseModel):
    texto: str = Field(min_length=1, max_length=60)
    url: str = Field(min_length=1, max_length=2000)


class AvisoIn(BaseModel):
    """Solo el texto del correo; el formato lo pone `plantillas.aviso`."""
    nombre: Optional[str] = Field(default=None, max_length=100)
    parrafos: List[str] = Field(min_length=1, max_length=10)
    boton: Optional[BotonIn] = None
    pie: str = Field(default="", max_length=500)


class EnviarIn(BaseModel):
    para: Union[str, List[str]]
    asunto: str = Field(min_length=1, max_length=300)
    # Uno de los dos: el HTML ya armado, o un aviso con el marco de la tienda.
    html: Optional[str] = Field(default=None, min_length=1)
    aviso: Optional[AvisoIn] = None
    texto: Optional[str] = None
    responder_a: Optional[str] = None
    adjuntos: List[AdjuntoIn] = []
    # Clasifica el correo en el panel de Resend (p. ej. "pedido-b2b").
    etiqueta: Optional[str] = Field(default=None, max_length=100)
    # El llamador que reintenta debe mandar la misma clave para no duplicar.
    clave_idempotencia: Optional[str] = Field(default=None, max_length=256)


def _respuesta(r: resend.Resultado) -> JSONResponse:
    cuerpo = {"enviado": r.enviado, "id": r.id, "error": r.error}
    if r.enviado:
        return JSONResponse(cuerpo)
    return JSONResponse(cuerpo, status_code=503 if not r.configurado else 502)


def _contenido(entrada: EnviarIn) -> tuple:
    """`(html, texto)` del correo, del HTML recibido o del aviso."""
    if (entrada.html is None) == (entrada.aviso is None):
        raise HTTPException(422, "manda `html` o `aviso`, uno de los dos")
    if entrada.html is not None:
        return entrada.html, entrada.texto
    a = entrada.aviso
    boton, url = (a.boton.texto, a.boton.url) if a.boton else (None, None)
    if url and urlsplit(url).scheme not in ("https", "http"):
        # El enlace va a un botón: un `javascript:` ahí no tiene uso legítimo.
        raise HTTPException(422, "el enlace del botón debe ser http(s)")
    c = plantillas.aviso(entrada.asunto, a.nombre, a.parrafos, boton, url, a.pie,
                         config.NOMBRE_TIENDA)
    return c.html, entrada.texto or c.texto


@app.post("/enviar", dependencies=[Depends(_requiere_servicio)])
def enviar(entrada: EnviarIn) -> JSONResponse:
    para = resend.como_lista(entrada.para)
    if not para or len(para) > 50 or any("@" not in d for d in para):
        raise HTTPException(422, "destinatarios inválidos (1 a 50 correos)")
    html, texto = _contenido(entrada)
    adjuntos = []
    total = 0
    for a in entrada.adjuntos:
        try:
            contenido = base64.b64decode(a.contenido_b64, validate=True)
        except (binascii.Error, ValueError):
            raise HTTPException(422, f"adjunto {a.nombre!r}: base64 inválido")
        total += len(contenido)
        if total > _ADJUNTOS_MAX_BYTES:
            raise HTTPException(413, "adjuntos demasiado grandes")
        adjuntos.append(resend.Adjunto(a.nombre, contenido, a.tipo))
    correo = resend.Correo(para=para, asunto=entrada.asunto, html=html,
                           texto=texto, responder_a=entrada.responder_a,
                           adjuntos=adjuntos, etiqueta=entrada.etiqueta)
    return _respuesta(resend.enviar(correo, clave_idempotencia=entrada.clave_idempotencia))


# ── Saleor App ──

_CAMPOS = "redirectUrl token user { email firstName } channel { slug } shop { name }"
_PLANTILLAS = {
    "account_confirmation_requested": ("AccountConfirmationRequested",
                                       plantillas.confirmar_cuenta, "confirmar-cuenta"),
    "account_set_password_requested": ("AccountSetPasswordRequested",
                                       plantillas.restablecer_clave, "restablecer-clave"),
}
SUSCRIPCION = "subscription { event { __typename %s } }" % " ".join(
    f"... on {tipo} {{ {_CAMPOS} }}" for tipo, _, _ in _PLANTILLAS.values())


@app.get("/manifest")
def manifest(request: Request) -> dict:
    base = str(request.base_url).rstrip("/")
    # Railway termina TLS antes del servicio: la URL llega como http.
    if base.startswith("http://") and request.headers.get("x-forwarded-proto") == "https":
        base = "https://" + base[len("http://"):]
    return {
        "id": "cl.ventu.correo",
        "version": "0.1.0",
        "name": "Ventu Correo",
        "about": "Correos de cuenta (confirmación, contraseña) enviados por Resend.",
        # Saleor solo entrega los eventos de cuenta a apps con MANAGE_USERS.
        "permissions": ["MANAGE_USERS"],
        "appUrl": base,
        "tokenTargetUrl": f"{base}/register",
        "webhooks": [{
            "name": "Correos de cuenta",
            "targetUrl": f"{base}/webhooks/saleor",
            "asyncEvents": [e.upper() for e in _PLANTILLAS],
            "query": SUSCRIPCION,
            "isActive": True,
        }],
    }


@app.post("/register")
async def register(request: Request) -> dict:
    # Esta app no llama a Saleor: el token no se guarda.
    return {"status": "ok"}


def url_con_token(redirect_url: str, email: str, token: str) -> str:
    """Lo mismo que hace Saleor (`prepare_url`): agrega email y token a la URL."""
    partes = urlsplit(redirect_url)
    query = parse_qsl(partes.query, keep_blank_values=True)
    query += [("email", email), ("token", token)]
    return urlunsplit(partes._replace(query=urlencode(query)))


@app.post("/webhooks/saleor")
async def saleor_webhook(
    request: Request,
    saleor_event: Optional[str] = Header(default=None),
    saleor_signature: Optional[str] = Header(default=None),
) -> JSONResponse:
    cuerpo = await request.body()
    if not saleor_firma.verificar(cuerpo, saleor_signature):
        raise HTTPException(401, "firma inválida")

    evento = (saleor_event or "").lower()
    if evento not in _PLANTILLAS:
        return JSONResponse({"resultado": "ignorado", "evento": evento})
    _, plantilla, etiqueta = _PLANTILLAS[evento]

    datos = await request.json()
    usuario = datos.get("user") or {}
    email, token, redirect = usuario.get("email"), datos.get("token"), datos.get("redirectUrl")
    if not (email and token and redirect):
        # Reintentar no lo arregla: se responde 200 para que Saleor no insista.
        logger.error("(correo) %s sin email, token o redirectUrl", evento)
        return JSONResponse({"resultado": "incompleto"})

    tienda = ((datos.get("shop") or {}).get("name") or "").strip() or "la tienda"
    contenido = plantilla(url_con_token(redirect, email, token), usuario.get("firstName"), tienda)
    correo = resend.Correo(para=[email], asunto=contenido.asunto, html=contenido.html,
                           texto=contenido.texto, etiqueta=etiqueta)
    # Saleor reentrega el webhook si no responde 2xx: la clave impide que un
    # reintento tras un envío exitoso mande el correo dos veces.
    clave = f"{etiqueta}-{hashlib.sha256(token.encode()).hexdigest()[:32]}"
    resultado = resend.enviar(correo, clave_idempotencia=clave)
    if not resultado.enviado:
        # 503 → Saleor reintenta más tarde.
        return JSONResponse({"resultado": "error", "error": resultado.error}, status_code=503)
    return JSONResponse({"resultado": "enviado", "id": resultado.id})
