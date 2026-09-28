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
from typing import Dict, Optional, Tuple

from ..saleor_client import SaleorRespuestaError, data_errors, gql, payload
from . import medios as medios_mod

_CREAR_ORDEN = """
mutation($id: ID!, $metadata: [MetadataInput!]) {
  orderCreateFromCheckout(id: $id, metadata: $metadata, removeCheckout: true) {
    order { id number status total { gross { amount currency } } }
    errors { field message code }
  }
}
"""


_FACTURACION = """
mutation($id: ID!, $direccion: AddressInput!) {
  checkoutBillingAddressUpdate(id: $id, billingAddress: $direccion) {
    errors { field message code }
  }
}
"""

# Campos de `Address` que se copian a `AddressInput`. `country` se trata aparte:
# en la lectura es un objeto y en la escritura un código.
_CAMPOS_DIRECCION = ("firstName", "lastName", "companyName", "streetAddress1",
                     "streetAddress2", "city", "cityArea", "postalCode",
                     "countryArea", "phone")


class PedidoError(RuntimeError):
    """No se pudo crear la orden."""


class SinDireccion(PedidoError):
    """El carrito no tiene dirección de facturación ni de despacho.

    Saleor no crea una orden sin dirección de facturación, y en B2B no hay de
    dónde inventarla: la tiene que ingresar el cliente.
    """


class DireccionRechazada(PedidoError):
    """Saleor no aceptó la dirección de despacho como dirección de facturación.

    El mensaje lleva los errores crudos de Saleor: es para el log, no para el
    cliente.
    """


class OrdenRechazada(PedidoError):
    """`orderCreateFromCheckout` respondió con errores de validación.

    Guarda el código del primero (`OrderCreateFromCheckoutErrorCode`) para que
    la API lo traduzca; el mensaje, con los errores crudos, es para el log.
    """

    def __init__(self, errores: list):
        self.errores = errores
        self.codigo = str((errores[0] if errores else {}).get("code") or "")
        super().__init__(f"Saleor rechazó la orden: {errores}")


# Código de `orderCreateFromCheckout` → (estado HTTP, qué decirle al cliente).
# 409 cuando el carrito está bien armado pero algo del estado actual lo impide
# (stock, canal, descuentos): reintentar tal cual no sirve, hay que ajustar el
# carrito. 422 cuando al carrito le falta un dato que el cliente debe completar.
_EXPLICACIONES: Dict[str, Tuple[int, str]] = {
    "INSUFFICIENT_STOCK": (409, "no hay stock suficiente para uno o más productos "
                                "del carrito; ajusta las cantidades e intenta de nuevo"),
    "UNAVAILABLE_VARIANT_IN_CHANNEL": (409, "uno o más productos del carrito ya no "
                                            "están disponibles; quítalos e intenta de nuevo"),
    "CHANNEL_INACTIVE": (409, "la venta a empresas no está disponible en este momento; "
                              "intenta más tarde"),
    "VOUCHER_NOT_APPLICABLE": (409, "el cupón del carrito ya no aplica; quítalo e "
                                    "intenta de nuevo"),
    "GIFT_CARD_NOT_APPLICABLE": (409, "la gift card del carrito ya no aplica; quítala "
                                      "e intenta de nuevo"),
    "INVALID_SHIPPING_METHOD": (409, "el método de despacho elegido ya no está "
                                     "disponible; elige otro"),
    "TAX_ERROR": (409, "no se pudieron calcular los impuestos del pedido; intenta "
                       "de nuevo en unos minutos"),
    # Con `removeCheckout: true`, un carrito que desaparece suele ser uno que ya
    # se convirtió en orden: el aviso es no repetir el pedido a ciegas.
    "CHECKOUT_NOT_FOUND": (409, "el carrito ya no existe; puede que el pedido ya se "
                                "haya creado, revisa tus pedidos"),
    "SHIPPING_METHOD_NOT_SET": (422, "falta elegir el método de despacho"),
    "SHIPPING_ADDRESS_NOT_SET": (422, "falta la dirección de despacho del pedido"),
    "BILLING_ADDRESS_NOT_SET": (422, "falta la dirección de facturación del pedido"),
    "EMAIL_NOT_SET": (422, "falta el correo de contacto del pedido"),
    "NO_LINES": (422, "el carrito está vacío"),
}

_EXPLICACION_GENERICA = (422, "no se pudo crear el pedido con los datos del carrito; "
                              "revísalos e intenta de nuevo")


def explicar(codigo: str) -> Tuple[int, str]:
    """Estado HTTP y mensaje en castellano para un código de Saleor.

    Un código desconocido (o `GRAPHQL_ERROR`) recibe un mensaje genérico: el
    texto de Saleor está en inglés y puede nombrar campos internos.
    """
    return _EXPLICACIONES.get(codigo, _EXPLICACION_GENERICA)


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


def asegurar_facturacion(checkout: dict) -> bool:
    """Copia la dirección de despacho a la de facturación si falta esta.

    El checkout del storefront B2B solo pide dirección de despacho, y
    `orderCreateFromCheckout` rechaza un carrito sin facturación. Para una
    empresa la dirección tributaria vive en la carpeta del SII, no en la
    orden, así que usar la de despacho no pierde nada.

    Devuelve si hubo que copiarla.
    """
    if checkout.get("billingAddress"):
        return False
    despacho = checkout.get("shippingAddress")
    if not despacho:
        raise SinDireccion("el carrito no tiene dirección de despacho ni de facturación")

    direccion = {k: despacho[k] for k in _CAMPOS_DIRECCION if despacho.get(k)}
    pais = (despacho.get("country") or {}).get("code")
    if pais:
        direccion["country"] = pais

    body = gql(_FACTURACION, {"id": checkout["id"], "direccion": direccion},
               reintentar=False)
    if data_errors(body):
        raise SaleorRespuestaError(f"dirección de facturación: {data_errors(body)}")
    errores = (payload(body).get("checkoutBillingAddressUpdate") or {}).get("errors") or []
    if errores:
        raise DireccionRechazada(f"la dirección de despacho no sirve como facturación: {errores}")
    return True


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

    # Nunca se reintenta: tras un timeout no se sabe si la orden se creó, y
    # repetir la mutación puede cerrar dos pedidos por el mismo carrito.
    body = gql(_CREAR_ORDEN, {"id": checkout_id, "metadata": _entradas(metadata)},
               reintentar=False)
    if data_errors(body):
        # Errores a nivel documento (permisos, esquema) son de la integración,
        # no del carrito: el cliente no puede corregirlos.
        raise SaleorRespuestaError(f"creación de la orden: {data_errors(body)}")

    resultado = payload(body).get("orderCreateFromCheckout") or {}
    errores = resultado.get("errors") or []
    if errores:
        raise OrdenRechazada(errores)

    orden = resultado.get("order")
    if not orden:
        # Sin errores y sin orden es una respuesta que Saleor no debería dar: es
        # un fallo de la integración (502), no algo que el cliente pueda corregir.
        raise SaleorRespuestaError("orderCreateFromCheckout no devolvió la orden ni errores")

    total = (orden.get("total") or {}).get("gross") or {}
    return Pedido(
        order_id=orden["id"],
        numero=str(orden.get("number") or ""),
        estado=orden.get("status") or "",
        total=float(total.get("amount") or 0),
        moneda=total.get("currency") or "",
        metodo_pago=medio.codigo,
    )
