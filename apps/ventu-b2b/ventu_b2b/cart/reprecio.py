"""Aplica al carrito el precio que corresponde a la cantidad.

La tabla de tramos de la ficha dice «12 unidades, $9.130 c/u». Sin esto el
carrito cobra el precio de catálogo y la tienda muestra un precio y cobra otro,
que es peor que no mostrar la tabla.

Saleor no tiene precios escalonados —un channel-listing guarda un precio único
por variante— pero `CheckoutLineUpdateInput` admite `price`, así que el tramo se
resuelve aquí y se fija en la línea. Queda registrado como precio con motivo,
que es exactamente lo que es: un precio distinto del de lista, con una razón.

Se recalcula el carrito **entero** en cada cambio y no solo la línea tocada:
cambiar la cantidad de una línea no altera las otras hoy, pero un carrito a
medio reprecificar cobraría mal sin que nada falle, y ese es el tipo de error
que se descubre en la facturación del mes.

Si una línea ya no alcanza ningún tramo (bajó la cantidad, se agotó el stock,
se quitó la escalera) su precio por volumen se **borra** y vuelve al de lista. Dejar
el anterior cobraría un precio por volumen a quien ya no compra volumen.

Solo se tocan las líneas sin precio fijado o con el motivo del tramo
(`MOTIVO_TRAMO`). Cualquier otro motivo —el negociado por el staff
(`MOTIVO_NEGOCIADO`) u otro que no reconozcamos— se respeta: la duda se
resuelve a favor de lo que alguien fijó a mano. El límite: Saleor admite un
precio fijado sin motivo, y ese no se distingue de una línea a precio de lista;
por eso esta app nunca fija un precio sin motivo.
"""

from __future__ import annotations

import logging
from typing import Dict, List, Optional

from .. import config
from ..saleor_client import SaleorRespuestaError, data_errors, gql, payload
from ..tiers import TramoInvalido
from . import precios as precios_mod
from .service import MOTIVO_TRAMO

logger = logging.getLogger("ventu-b2b.reprecio")

# Todo lo que el pedido necesita saber del carrito en una sola lectura: el
# dueño (para no cerrar carritos ajenos), el canal (el precio sale de ahí, no de
# la empresa), las direcciones (la orden exige facturación) y el motivo de cada
# precio fijado (para distinguir tramo de negociado).
_CHECKOUT = """
query($id: ID!) {
  checkout(id: $id) {
    id
    channel { slug }
    user { id }
    billingAddress { id }
    shippingAddress {
      firstName lastName companyName streetAddress1 streetAddress2
      city cityArea postalCode countryArea phone country { code }
    }
    lines { id quantity priceOverrideReason variant { id } }
  }
}
"""

_ACTUALIZAR = """
mutation($id: ID!, $lines: [CheckoutLineUpdateInput!]!) {
  checkoutLinesUpdate(id: $id, lines: $lines) {
    checkout { id totalPrice { gross { amount } } }
    errors { field message code }
  }
}
"""


class ReprecioError(RuntimeError):
    """No se pudo reprecificar el carrito."""


def leer_checkout(checkout_id: str) -> Optional[dict]:
    """El carrito con dueño, canal, direcciones y líneas; `None` si no existe."""
    cuerpo = gql(_CHECKOUT, {"id": checkout_id})
    if data_errors(cuerpo):
        raise SaleorRespuestaError(f"lectura del carrito: {data_errors(cuerpo)}")
    return payload(cuerpo).get("checkout")


def canal_de(checkout: dict) -> str:
    return (checkout.get("channel") or {}).get("slug") or ""


def aplicar(checkout_id: str, *, canal: Optional[str] = None) -> dict:
    """Lee el carrito y le aplica los tramos. Ver `aplicar_a`."""
    checkout = leer_checkout(checkout_id)
    if not checkout:
        raise ReprecioError("el carrito no existe")
    return aplicar_a(checkout, canal=canal)


def aplicar_a(checkout: dict, *, canal: Optional[str] = None) -> dict:
    """Fija en cada línea el precio de su tramo, o borra el que ya no aplica.

    El precio se resuelve en el canal **del carrito**: es el que Saleor usa
    para el precio de lista y los impuestos, y mezclar la escalera de un canal
    con la lista de otro cobraría un precio que ninguna de las dos publica.
    `canal` existe solo para los tests y herramientas; la API no lo expone.

    Una línea sin precio fijado y sin tramo no se toca: sobreescribirla con el
    precio de catálogo la marcaría como fijada sin que nadie fijara nada.

    Un fallo al leer Saleor se propaga: un carrito que no se pudo reprecificar
    no debe cerrarse como pedido con el precio anterior.
    """
    destino = canal or canal_de(checkout) or config.CANAL_CARRITO
    escalera = config.tramos_del_canal(destino)

    cambios: List[Dict[str, object]] = []
    fallidas: List[str] = []
    restablecidas = 0
    for linea in checkout.get("lines") or []:
        variante = (linea.get("variant") or {}).get("id")
        cantidad = int(linea.get("quantity") or 0)
        motivo_actual = linea.get("priceOverrideReason") or ""
        if not variante or cantidad < 1:
            continue
        if motivo_actual and motivo_actual != MOTIVO_TRAMO:
            # Precio negociado (o de origen desconocido): no es nuestro.
            continue

        try:
            precio = precios_mod.resolver_precio(
                variante, cantidad, canal=destino, escalera_channel=escalera,
                stock_minimo=config.STOCK_MINIMO_TRAMOS)
        except TramoInvalido as exc:
            # Una escalera mal escrita es un error de datos, no del carrito: la
            # línea vuelve al precio de lista y se deja constancia para
            # corregirla, en vez de impedir la compra.
            logger.warning("(reprecio) escalera inválida en %s: %s", variante, exc)
            fallidas.append(variante)
            precio = None

        # Sin `quantity`: la cantidad no cambia, y enviarla hace que Saleor
        # revalide stock y disponibilidad de la línea. Un producto agotado o
        # despublicado haría fallar el reprecio entero (502 que ningún
        # reintento arregla) en vez de llegar al pedido, que sí traduce
        # INSUFFICIENT_STOCK y compañía a un 409 legible. Saleor acepta omitirla
        # solo a una app, que es quien llama aquí.
        if precio is not None:
            cambios.append({
                "lineId": linea["id"],
                "price": precio,
                "priceOverrideReason": MOTIVO_TRAMO,
            })
        elif motivo_actual:
            # Solo llega aquí un tramo que ya no aplica (los demás motivos se
            # saltaron arriba). `price: null` borra la sobreescritura. Sin
            # motivo: Saleor solo lo admite junto a un precio.
            cambios.append({"lineId": linea["id"], "price": None})
            restablecidas += 1

    resultado: Dict[str, object] = {"aplicado": False, "lineas": 0}
    if fallidas:
        resultado["fallidas"] = fallidas
    if not cambios:
        return resultado

    # Mutación: nunca se reintenta (ver saleor_client). Reaplicar el mismo
    # precio sería inocuo, pero la regla es la misma para todas.
    r = gql(_ACTUALIZAR, {"id": checkout["id"], "lines": cambios}, reintentar=False)
    if data_errors(r):
        raise ReprecioError(f"actualización de líneas: {data_errors(r)}")

    actualizacion = payload(r).get("checkoutLinesUpdate") or {}
    if actualizacion.get("errors"):
        raise ReprecioError(str(actualizacion["errors"]))

    total = ((actualizacion.get("checkout") or {}).get("totalPrice") or {}).get("gross") or {}
    resultado.update({
        "aplicado": True,
        "lineas": len(cambios) - restablecidas,
        "restablecidas": restablecidas,
        "total": total.get("amount"),
    })
    return resultado
