"""Medios de pago que ofrece Ventu B2B.

Dos familias, y la diferencia no es cosmética:

- **Inmediatos** (tarjeta de crédito, tarjeta de débito). El pago lo confirma una
  pasarela (Webpay/Transbank, vía la app `ventu-pagos`). Bajo el modelo
  orden-primero el pedido igual nace **por pagar** y la pasarela lo cobra sobre la
  orden ya creada; queda pagado cuando el cobro se confirma (`ORDER_FULLY_PAID`).
- **Diferidos** (transferencia, Cheke Maxxa 30 días). El pedido nace **por
  pagar** y esa es su condición normal, no una anomalía: en distribución
  mayorista la orden se despacha contra una promesa de pago. No necesitan
  pasarela para ser correctos.

La diferencia ahora es *cómo* se salda —pasarela inmediata vs. promesa de pago—,
no si el medio está conectado: ambas familias cierran el pedido de verdad.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Optional

# Claves en la metadata de la orden. Viajan al ERP y a la facturación.
K_METODO = "ventu.pago.metodo"
K_ESTADO = "ventu.pago.estado"

PENDIENTE = "pendiente"

TARJETA_CREDITO = "tarjeta_credito"
TARJETA_DEBITO = "tarjeta_debito"
TRANSFERENCIA = "transferencia"
MAXXA_30 = "maxxa_30"


class MedioNoDisponible(ValueError):
    """El medio existe pero esta empresa no puede usarlo ahora."""


@dataclass(frozen=True)
class Medio:
    codigo: str
    etiqueta: str
    #: `False` si el medio se muestra pero aún no puede usarse (p. ej. sin
    #: pasarela conectada): se ofrece en la vitrina, pero `validar()` lo rechaza.
    operativo: bool
    #: El pedido nace por pagar en vez de pagado.
    diferido: bool
    #: Exige crédito aprobado por Maxxa.
    requiere_credito: bool = False


MEDIOS: Dict[str, Medio] = {
    TARJETA_CREDITO: Medio(TARJETA_CREDITO, "Tarjeta de crédito",
                           operativo=True, diferido=False),
    TARJETA_DEBITO: Medio(TARJETA_DEBITO, "Tarjeta de débito",
                          operativo=True, diferido=False),
    TRANSFERENCIA: Medio(TRANSFERENCIA, "Transferencia bancaria",
                         operativo=True, diferido=True),
    MAXXA_30: Medio(MAXXA_30, "Cheke Maxxa 30 días",
                    operativo=True, diferido=True, requiere_credito=True),
}

# Orden en que se ofrecen. Explícito y no el del diccionario, para que reordenar
# la vitrina no dependa de en qué línea se declaró cada medio.
ORDEN = (TARJETA_CREDITO, TARJETA_DEBITO, TRANSFERENCIA, MAXXA_30)


# Motivo por el que un medio se muestra deshabilitado. El storefront traduce
# cada uno; agregar uno exige agregarlo allá.
SIN_CREDITO = "sin_credito"
NO_OPERATIVO = "no_operativo"
PENDIENTE_APROBACION = "pendiente_aprobacion"


def disponibles(*, tiene_credito: bool, aprobada: bool) -> list:
    """Los medios tal como debe verlos esta empresa.

    Se devuelven **todos**, incluidos los que no puede usar, con el motivo. Un
    listado que esconde «Cheke Maxxa 30 días» a quien no tiene crédito le oculta
    justamente la razón para solicitarlo.

    Mientras Ventu no apruebe la empresa, ninguno está habilitado y todos dicen
    por qué: el motivo que importa es ese, no el de cada medio. `aprobada` es
    obligatorio para que olvidarlo sea un error y no una empresa en revisión
    con los medios abiertos.
    """
    salida = []
    for codigo in ORDEN:
        m = MEDIOS[codigo]
        motivo = None
        if not aprobada:
            motivo = PENDIENTE_APROBACION
        elif m.requiere_credito and not tiene_credito:
            motivo = SIN_CREDITO
        elif not m.operativo:
            motivo = NO_OPERATIVO
        salida.append({
            "codigo": m.codigo,
            "etiqueta": m.etiqueta,
            "diferido": m.diferido,
            "habilitado": motivo is None,
            **({"motivo": motivo} if motivo else {}),
        })
    return salida


def validar(codigo: str, *, tiene_credito: bool) -> Medio:
    """El medio elegido, o el motivo por el que no se puede usar."""
    medio: Optional[Medio] = MEDIOS.get(codigo)
    if medio is None:
        raise MedioNoDisponible(f"medio de pago desconocido: {codigo!r}")
    if medio.requiere_credito and not tiene_credito:
        raise MedioNoDisponible(
            "Cheke Maxxa 30 días requiere crédito aprobado")
    if not medio.operativo:
        # Se distingue de «no existe»: el medio está en la vitrina y la empresa
        # podría elegirlo, pero cerrar el pedido implicaría dar por cobrado algo
        # que ninguna pasarela cobró.
        raise MedioNoDisponible(
            f"{medio.etiqueta} todavía no está conectado")
    return medio
