"""Carritos de WhatsApp: armar, recuperar y rehacer.

El carrito de Saleor cumple la función de cotización: es a la vez la propuesta
comercial editable y el inicio de la transacción. No hay entidad de cotización
aparte.

El precio por tramo se resuelve en Pricing y se aplica a la línea mediante
`price` de `CheckoutLineInput`, que Saleor sí admite aunque no tenga precios
escalonados nativos.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Dict, List, Optional, Sequence

from .. import config
from ..saleor_client import data_errors, gql, payload
from . import link as link_mod

# Clave donde el checkout guarda su enlace, para poder resolverlo de vuelta.
K_LINK = "ventu.b2b.link_id"
K_ORIGEN = "ventu.b2b.origen"

_CREAR = """
mutation($input: CheckoutCreateInput!) {
  checkoutCreate(input: $input) {
    checkout { id token }
    errors { field message code }
  }
}
"""

_POR_LINK = """
query($key: String!, $value: String!) {
  checkouts(first: 2, filter: {metadata: [{key: $key, value: $value}]}) {
    edges { node { id token channel { slug } lines { id quantity variant { id } } } }
  }
}
"""

_ADJUNTAR_CLIENTE = """
mutation($id: ID!, $customerId: ID!) {
  checkoutCustomerAttach(id: $id, customerId: $customerId) {
    errors { field message code }
  }
}
"""


# Motivo con que se marca un precio que fijó el staff a mano. El reprecio lo
# reconoce y no lo toca: recalcular por tramo desharía lo que se negoció.
# `priceOverrideReason` solo puede escribirlo una app con HANDLE_CHECKOUTS, así
# que el cliente no puede fabricar la marca para congelar un precio.
MOTIVO_NEGOCIADO = "Precio negociado (B2B)"

# Motivo del precio por volumen. Es el **único** que el reprecio puede
# recalcular o borrar: cualquier otro motivo es un precio que alguien fijó con
# intención (el staff, otra herramienta, una versión anterior de esta app) y
# pisarlo cobraría otra cosa que lo acordado.
MOTIVO_TRAMO = "Precio por volumen"


def motivo_negociado(cantidad: int) -> str:
    """Motivo de un precio negociado, con la cantidad para la que se acordó.

    Un precio negociado vale para esa cantidad: 500 unidades a precio de
    volumen no son 1 unidad al mismo precio. Saleor conserva el precio fijado
    cuando el cliente cambia solo la cantidad, así que la cantidad acordada
    tiene que quedar donde el cliente no pueda escribir: en el motivo, que solo
    fija una app con HANDLE_CHECKOUTS. La metadata de la línea no sirve: el
    cliente la escribe con `CheckoutLineInput.metadata`.
    """
    return f"{MOTIVO_NEGOCIADO} x{cantidad}"


_CANTIDAD_NEGOCIADA = re.compile(r"x([0-9]+)")


def cantidad_negociada(motivo: Optional[str]) -> Optional[int]:
    """Cantidad acordada que lleva un motivo negociado.

    `None` si el motivo no es negociado o no la lleva (un carrito armado antes
    de este formato): esa línea no se puede verificar y se respeta como antes.
    """
    if not motivo or not motivo.startswith(MOTIVO_NEGOCIADO):
        return None
    m = _CANTIDAD_NEGOCIADA.fullmatch(motivo[len(MOTIVO_NEGOCIADO):].strip())
    return int(m.group(1)) if m else None


def negociadas_alteradas(lineas: Sequence[dict]) -> List[str]:
    """Líneas del checkout con precio negociado cuya cantidad ya no es la
    acordada (ids de Saleor)."""
    alteradas = []
    for linea in lineas or []:
        acordada = cantidad_negociada(linea.get("priceOverrideReason"))
        if acordada is not None and int(linea.get("quantity") or 0) != acordada:
            alteradas.append(linea.get("id"))
    return alteradas


class CarritoError(RuntimeError):
    """No se pudo operar sobre el carrito."""


@dataclass(frozen=True)
class Linea:
    """Línea del carrito. `precio_unitario` fija el precio de la línea.

    `motivo` distingue un precio por tramo —que el reprecio puede recalcular—
    de uno negociado, que se respeta. Sin motivo se asume negociado: es el
    caso que no debe perderse por omisión. El negociado se escribe con la
    cantidad de la línea (ver `motivo_negociado`).
    """

    variant_id: str
    cantidad: int
    precio_unitario: Optional[float] = None
    motivo: Optional[str] = None

    def to_input(self) -> dict:
        entrada: Dict[str, object] = {
            "variantId": self.variant_id,
            "quantity": self.cantidad,
        }
        if self.precio_unitario is not None:
            entrada["price"] = self.precio_unitario
            # Saleor exige explicar por qué se sobrescribe el precio de lista.
            # Queda registrado en el checkout, así que sirve de rastro comercial.
            motivo = self.motivo or MOTIVO_NEGOCIADO
            if motivo == MOTIVO_NEGOCIADO:
                motivo = motivo_negociado(self.cantidad)
            entrada["priceOverrideReason"] = motivo
        return entrada


@dataclass(frozen=True)
class Carrito:
    link_id: str
    checkout_id: str
    token: str

    def url(self, base: str = "") -> str:
        return link_mod.url(base or config.STOREFRONT_URL, self.link_id)


def crear(lineas: Sequence[Linea], *, canal: str = "", origen: str = "whatsapp",
          extra_metadata: Optional[Dict[str, str]] = None) -> Carrito:
    """Arma un carrito y devuelve su enlace recuperable.

    Nace directamente en el canal B2B: el ejecutivo ya sabe que habla con una
    empresa, así que el carrito no necesita rehacerse cuando el cliente se
    identifique.
    """
    if not lineas:
        raise CarritoError("un carrito sin líneas no es una propuesta")

    link_id = link_mod.generar()
    metadata = {K_LINK: link_id, K_ORIGEN: origen}
    metadata.update(extra_metadata or {})

    entrada = {
        "channel": canal or config.CANAL_CARRITO,
        "lines": [l.to_input() for l in lineas],
        "metadata": [{"key": k, "value": v} for k, v in metadata.items()],
    }
    body = gql(_CREAR, {"input": entrada})
    if data_errors(body):
        raise CarritoError(f"crear carrito: {data_errors(body)}")

    res = payload(body).get("checkoutCreate") or {}
    if res.get("errors"):
        raise CarritoError(f"crear carrito: {res['errors']}")

    checkout = res.get("checkout") or {}
    if not checkout.get("id"):
        raise CarritoError("Saleor no devolvió el carrito")

    return Carrito(link_id=link_id, checkout_id=checkout["id"],
                   token=checkout.get("token", ""))


def resolver(link_id: str) -> Optional[dict]:
    """Checkout vigente detrás de un enlace, o `None` si ya no existe.

    Valida la forma del identificador antes de consultar: así una URL manipulada
    no se convierte en tráfico contra la API.
    """
    link_mod.validar(link_id)
    body = gql(_POR_LINK, {"key": K_LINK, "value": link_id})
    if data_errors(body):
        raise CarritoError(f"resolver enlace: {data_errors(body)}")

    edges = ((payload(body).get("checkouts") or {}).get("edges")) or []
    return edges[0]["node"] if edges else None


def adjuntar_cliente(checkout_id: str, user_id: str) -> None:
    """Asocia un carrito anónimo al usuario que acaba de identificarse."""
    body = gql(_ADJUNTAR_CLIENTE, {"id": checkout_id, "customerId": user_id})
    if data_errors(body):
        raise CarritoError(f"adjuntar cliente: {data_errors(body)}")
    errs = (payload(body).get("checkoutCustomerAttach") or {}).get("errors") or []
    if errs:
        raise CarritoError(f"adjuntar cliente: {errs}")


def rehacer(link_id: str, lineas: Sequence[Linea], *, canal: str,
            origen: str = "whatsapp") -> Carrito:
    """Recrea el carrito en otro canal conservando el mismo enlace.

    Hace falta porque el canal de un checkout es inmutable: si una empresa cambia
    de nivel de precio, o el carrito caducó, la única salida es crear uno nuevo.
    Reusar el `link_id` es lo que evita invalidar el enlace que el cliente ya
    tiene en su teléfono.
    """
    link_mod.validar(link_id)
    if not lineas:
        raise CarritoError("un carrito sin líneas no es una propuesta")

    entrada = {
        "channel": canal,
        "lines": [l.to_input() for l in lineas],
        "metadata": [{"key": K_LINK, "value": link_id},
                     {"key": K_ORIGEN, "value": origen}],
    }
    body = gql(_CREAR, {"input": entrada})
    if data_errors(body):
        raise CarritoError(f"rehacer carrito: {data_errors(body)}")

    res = payload(body).get("checkoutCreate") or {}
    if res.get("errors"):
        raise CarritoError(f"rehacer carrito: {res['errors']}")

    checkout = res.get("checkout") or {}
    return Carrito(link_id=link_id, checkout_id=checkout.get("id", ""),
                   token=checkout.get("token", ""))
