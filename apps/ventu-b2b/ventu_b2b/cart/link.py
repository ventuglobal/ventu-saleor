"""Enlaces de carrito para WhatsApp.

El enlace que se envía al cliente **no** apunta al token del checkout de Saleor,
sino a un identificador propio:

    https://ventu.cl/c/<link_id>   →   resuelve al checkout vigente

La indirección existe porque un checkout no siempre sobrevive: puede caducar, o
haber que rehacerlo en otro canal —el canal de un checkout es inmutable en
Saleor, no hay mutación que lo cambie—. Con el enlace apuntando directo al token,
cualquiera de esos casos invalidaría un enlace ya enviado por WhatsApp, que es
justo lo que no se puede permitir: el cliente ya lo tiene en su teléfono.

Además evita exponer identificadores internos de Saleor en un mensaje que se
reenvía sin control.

Este módulo es **puro**: genera y valida identificadores. No habla con Saleor.
"""

from __future__ import annotations

import secrets
import string

# Alfabeto sin caracteres que se confunden al leer o dictar por teléfono:
# 0/O, 1/l/I. Un enlace de WhatsApp a veces se lee en voz alta.
ALFABETO = "23456789abcdefghjkmnpqrstuvwxyzABCDEFGHJKMNPQRSTUVWXYZ"

# 22 caracteres sobre este alfabeto son ~127 bits: no adivinable por fuerza
# bruta. Importa porque el enlace da acceso al carrito sin autenticación.
LARGO = 22

_VALIDOS = set(ALFABETO)


class LinkInvalido(ValueError):
    """El identificador no tiene la forma esperada."""


def generar() -> str:
    """Identificador nuevo, imposible de adivinar."""
    return "".join(secrets.choice(ALFABETO) for _ in range(LARGO))


def validar(link_id: str) -> str:
    """Devuelve el identificador si es válido; si no, lanza.

    Se valida antes de consultar Saleor para que una URL manipulada no se
    convierta en una consulta a la API.
    """
    if not link_id or len(link_id) != LARGO:
        raise LinkInvalido(f"largo inesperado: {len(link_id or '')}")
    if not _VALIDOS.issuperset(link_id):
        raise LinkInvalido("caracteres no permitidos")
    return link_id


def es_valido(link_id: str) -> bool:
    try:
        validar(link_id)
        return True
    except LinkInvalido:
        return False


def url(base: str, link_id: str) -> str:
    """URL completa para enviar por WhatsApp."""
    validar(link_id)
    return f"{base.rstrip('/')}/c/{link_id}"
