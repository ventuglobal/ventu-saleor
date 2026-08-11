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
"""

from __future__ import annotations

from typing import List, Optional

from .. import config
from ..saleor_client import data_errors, gql, payload
from . import precios as precios_mod

MOTIVO = "Precio por volumen"

_LINEAS = """
query($id: ID!) {
  checkout(id: $id) {
    id
    channel { slug }
    lines { id quantity variant { id } }
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


def aplicar(checkout_id: str, *, canal: Optional[str] = None) -> dict:
    """Fija en cada línea el precio de su tramo.

    Una línea sin tramos se deja **intacta**: sobreescribirla con el precio de
    catálogo la marcaría como negociada sin que nadie haya negociado nada, y esa
    marca viaja a la orden.
    """
    cuerpo = gql(_LINEAS, {"id": checkout_id})
    if data_errors(cuerpo):
        raise ReprecioError(f"lectura del carrito: {data_errors(cuerpo)}")

    checkout = payload(cuerpo).get("checkout")
    if not checkout:
        raise ReprecioError("el carrito no existe")

    destino = canal or (checkout.get("channel") or {}).get("slug") or config.CANAL_CARRITO
    escalera = config.tramos_del_canal(destino)

    cambios: List[dict] = []
    for linea in checkout.get("lines") or []:
        variante = (linea.get("variant") or {}).get("id")
        cantidad = int(linea.get("quantity") or 0)
        if not variante or cantidad < 1:
            continue

        try:
            precio = precios_mod.resolver_precio(
                variante, cantidad, canal=destino, escalera_channel=escalera,
                stock_minimo=config.STOCK_MINIMO_TRAMOS)
        except Exception:  # noqa: BLE001
            # Una escalera ilegible no debe impedir comprar: la línea se queda
            # con el precio de catálogo y el fallo ya quedó registrado al leerla.
            precio = None

        if precio is None:
            continue

        cambios.append({
            "lineId": linea["id"],
            "quantity": cantidad,
            "price": precio,
            "priceOverrideReason": MOTIVO,
        })

    if not cambios:
        return {"aplicado": False, "lineas": 0}

    r = gql(_ACTUALIZAR, {"id": checkout_id, "lines": cambios})
    if data_errors(r):
        raise ReprecioError(f"actualización de líneas: {data_errors(r)}")

    resultado = payload(r).get("checkoutLinesUpdate") or {}
    if resultado.get("errors"):
        raise ReprecioError(str(resultado["errors"]))

    total = ((resultado.get("checkout") or {}).get("totalPrice") or {}).get("gross") or {}
    return {"aplicado": True, "lineas": len(cambios), "total": total.get("amount")}
