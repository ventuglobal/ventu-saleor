"""Plantillas de los correos de cuenta.

HTML simple con estilos en línea: es lo único que respetan todos los clientes
de correo. Todo dato que viene del usuario se escapa; la URL viene firmada por
Saleor, que ya validó su dominio contra ALLOWED_CLIENT_HOSTS.
"""

from __future__ import annotations

from dataclasses import dataclass
from html import escape
from typing import Optional


@dataclass
class Contenido:
    asunto: str
    html: str
    texto: str


def _saludo(nombre: Optional[str]) -> str:
    nombre = (nombre or "").strip()
    return f"Hola {nombre}," if nombre else "Hola,"


def _marco(tienda: str, saludo: str, parrafos: list, boton: str, url: str, pie: str) -> str:
    cuerpo = "".join(
        f'<p style="margin:0 0 16px;font-size:15px;line-height:1.5;color:#333">{escape(p)}</p>'
        for p in parrafos
    )
    url_html = escape(url, quote=True)
    return (
        '<!doctype html><html lang="es"><body style="margin:0;padding:24px;background:#f5f5f5;'
        'font-family:Arial,Helvetica,sans-serif">'
        '<table role="presentation" width="100%" cellpadding="0" cellspacing="0" '
        'style="max-width:520px;margin:0 auto;background:#fff;border-radius:8px">'
        '<tr><td style="padding:32px">'
        f'<p style="margin:0 0 24px;font-size:18px;font-weight:bold;color:#111">{escape(tienda)}</p>'
        f'<p style="margin:0 0 16px;font-size:15px;color:#333">{escape(saludo)}</p>'
        f"{cuerpo}"
        f'<p style="margin:24px 0"><a href="{url_html}" style="display:inline-block;padding:12px 20px;'
        'background:#111;color:#fff;text-decoration:none;border-radius:6px;font-size:15px">'
        f"{escape(boton)}</a></p>"
        '<p style="margin:0 0 8px;font-size:13px;color:#666">Si el botón no funciona, copia este '
        "enlace en tu navegador:</p>"
        f'<p style="margin:0 0 24px;font-size:13px;word-break:break-all"><a href="{url_html}" '
        f'style="color:#0645ad">{url_html}</a></p>'
        f'<p style="margin:0;font-size:12px;color:#888">{escape(pie)}</p>'
        "</td></tr></table></body></html>"
    )


def confirmar_cuenta(url: str, nombre: Optional[str], tienda: str) -> Contenido:
    saludo = _saludo(nombre)
    parrafos = [f"Gracias por registrarte en {tienda}. Confirma tu correo para activar tu cuenta."]
    pie = "Si no creaste esta cuenta, ignora este correo."
    return Contenido(
        asunto=f"Confirma tu cuenta en {tienda}",
        html=_marco(tienda, saludo, parrafos, "Confirmar mi cuenta", url, pie),
        texto=f"{saludo}\n\n{parrafos[0]}\n\n{url}\n\n{pie}\n",
    )


def restablecer_clave(url: str, nombre: Optional[str], tienda: str) -> Contenido:
    saludo = _saludo(nombre)
    parrafos = [
        f"Recibimos una solicitud para crear o cambiar la contraseña de tu cuenta en {tienda}.",
        "El enlace es de un solo uso y vence pronto.",
    ]
    pie = "Si no lo pediste, ignora este correo: tu contraseña no cambia."
    return Contenido(
        asunto=f"Crea tu contraseña en {tienda}",
        html=_marco(tienda, saludo, parrafos, "Crear contraseña", url, pie),
        texto=f"{saludo}\n\n{' '.join(parrafos)}\n\n{url}\n\n{pie}\n",
    )
