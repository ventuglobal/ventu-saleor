"""Envío por la API HTTP de Resend.

Mismo contrato que `src/lib/email.ts` de storefront-next: nunca lanza, devuelve
si se envió y por qué no. Quien envía un correo casi nunca debe fallar porque
el correo falló (un pedido no se cae por una notificación).
"""

from __future__ import annotations

import base64
import logging
from dataclasses import dataclass, field
from typing import List, Optional, Sequence, Union

import httpx

from . import config

logger = logging.getLogger("ventu.correo")


@dataclass
class Adjunto:
    nombre: str
    contenido: bytes
    tipo: Optional[str] = None


@dataclass
class Resultado:
    enviado: bool
    id: Optional[str] = None
    error: Optional[str] = None
    # Distingue "falta configurar" de "Resend lo rechazó": el primero no se
    # arregla reintentando.
    configurado: bool = True


@dataclass
class Correo:
    para: List[str]
    asunto: str
    html: str
    texto: Optional[str] = None
    responder_a: Optional[str] = None
    adjuntos: List[Adjunto] = field(default_factory=list)
    etiqueta: Optional[str] = None


def ocultar(direccion: str) -> str:
    """Correo apto para el log: se ve a quién, sin dejarlo entero."""
    usuario, _, dominio = direccion.partition("@")
    return f"{usuario[:2]}***@{dominio}" if dominio else "***"


def _cuerpo(correo: Correo) -> dict:
    cuerpo = {
        "from": config.MAIL_FROM,
        "to": correo.para,
        "subject": correo.asunto,
        "html": correo.html,
    }
    if correo.texto:
        cuerpo["text"] = correo.texto
    responder_a = correo.responder_a or config.MAIL_REPLY_TO
    if responder_a:
        cuerpo["reply_to"] = responder_a
    if correo.adjuntos:
        cuerpo["attachments"] = [
            {
                "filename": a.nombre,
                "content": base64.b64encode(a.contenido).decode(),
                **({"content_type": a.tipo} if a.tipo else {}),
            }
            for a in correo.adjuntos
        ]
    if correo.etiqueta:
        # Resend solo admite [A-Za-z0-9_-] en las etiquetas.
        valor = "".join(c if c.isalnum() or c in "_-" else "_" for c in correo.etiqueta)
        cuerpo["tags"] = [{"name": "tipo", "value": valor[:256]}]
    return cuerpo


def enviar(correo: Correo, *, clave_idempotencia: Optional[str] = None,
           cliente: Optional[httpx.Client] = None) -> Resultado:
    """Envía un correo. Nunca lanza.

    `clave_idempotencia` evita el duplicado cuando el llamador reintenta (p. ej.
    Saleor reentregando un webhook): Resend descarta el segundo envío con la
    misma clave durante 24 h.
    """
    if not config.RESEND_API_KEY or not config.MAIL_FROM:
        falta = "RESEND_API_KEY" if not config.RESEND_API_KEY else "MAIL_FROM"
        logger.warning("(correo) %s vacío; no se envía '%s'", falta, correo.asunto)
        return Resultado(False, error="no-configurado", configurado=False)
    if not correo.para:
        return Resultado(False, error="sin destinatarios")

    cabeceras = {"Authorization": f"Bearer {config.RESEND_API_KEY}"}
    if clave_idempotencia:
        cabeceras["Idempotency-Key"] = clave_idempotencia[:256]

    destino = ", ".join(ocultar(d) for d in correo.para)
    try:
        if cliente is None:
            with httpx.Client(timeout=config.RESEND_TIMEOUT) as c:
                resp = c.post(config.RESEND_URL, json=_cuerpo(correo), headers=cabeceras)
        else:
            resp = cliente.post(config.RESEND_URL, json=_cuerpo(correo), headers=cabeceras)
    except httpx.HTTPError as exc:
        logger.error("(correo) Resend inalcanzable para %s: %s", destino, type(exc).__name__)
        return Resultado(False, error=f"red: {type(exc).__name__}")

    if resp.status_code >= 300:
        detalle = resp.text[:300]
        logger.error("(correo) Resend %s para %s: %s", resp.status_code, destino, detalle)
        return Resultado(False, error=f"resend {resp.status_code}: {detalle}")

    try:
        ident = resp.json().get("id")
    except ValueError:
        ident = None
    logger.info("(correo) enviado '%s' a %s id=%s", correo.asunto, destino, ident)
    return Resultado(True, id=ident)


def como_lista(para: Union[str, Sequence[str]]) -> List[str]:
    if isinstance(para, str):
        return [p.strip() for p in para.split(",") if p.strip()]
    return [p.strip() for p in para if p and p.strip()]
