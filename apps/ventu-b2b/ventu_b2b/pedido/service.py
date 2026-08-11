"""Convierte el carrito en orden.

Usa `orderCreateFromCheckout` y no `checkoutComplete` porque el pedido B2B nace
**por pagar**: `checkoutComplete` exige que el total esté cubierto, que es la
regla correcta para una venta al consumidor y la equivocada para una venta a 30
días. `orderCreateFromCheckout` es una mutación de app —pide `HANDLE_CHECKOUTS`,
que esta app ya tiene— y crea la orden sin transacción asociada.

La identidad tributaria de la empresa y el medio de pago viajan en la metadata
de la orden: es lo que después permite facturar y cobrar.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Optional

from ..saleor_client import data_errors, gql, payload
from . import medios as medios_mod

_CREAR_ORDEN = """
mutation($id: ID!, $metadata: [MetadataInput!]) {
  orderCreateFromCheckout(id: $id, metadata: $metadata, removeCheckout: true) {
    order { id number status total { gross { amount currency } } }
    errors { field message code }
  }
}
"""


class PedidoError(RuntimeError):
    """No se pudo crear la orden."""


@dataclass(frozen=True)
class Pedido:
    order_id: str
    numero: str
    estado: str
    total: float
    moneda: str
    metodo_pago: str


def _entradas(datos: Dict[str, str]) -> list:
    return [{"key": k, "value": v} for k, v in datos.items() if v]


def crear(checkout_id: str, metodo: str, *, tiene_credito: bool,
          extra_metadata: Optional[Dict[str, str]] = None) -> Pedido:
    """Cierra el carrito como orden con el medio de pago elegido.

    Valida el medio **antes** de tocar Saleor: si el medio no corresponde, el
    carrito debe quedar intacto para que el cliente elija otro. Crear la orden y
    después descubrir que el pago no aplicaba dejaría un pedido huérfano.
    """
    medio = medios_mod.validar(metodo, tiene_credito=tiene_credito)

    metadata = dict(extra_metadata or {})
    metadata[medios_mod.K_METODO] = medio.codigo
    # Todo pedido diferido nace por pagar; hoy no hay ningún medio que nazca
    # pagado, pero el estado se escribe explícitamente para que la facturación no
    # tenga que deducirlo del método.
    metadata[medios_mod.K_ESTADO] = medios_mod.PENDIENTE

    body = gql(_CREAR_ORDEN, {"id": checkout_id, "metadata": _entradas(metadata)})
    if data_errors(body):
        raise PedidoError(f"creación de la orden: {data_errors(body)}")

    resultado = payload(body).get("orderCreateFromCheckout") or {}
    errores = resultado.get("errors") or []
    if errores:
        raise PedidoError(str(errores))

    orden = resultado.get("order")
    if not orden:
        raise PedidoError("Saleor no devolvió la orden")

    total = (orden.get("total") or {}).get("gross") or {}
    return Pedido(
        order_id=orden["id"],
        numero=str(orden.get("number") or ""),
        estado=orden.get("status") or "",
        total=float(total.get("amount") or 0),
        moneda=total.get("currency") or "",
        metodo_pago=medio.codigo,
    )
