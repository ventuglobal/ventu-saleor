"""Medios de pago que ofrece Ventu B2B.

Dos familias, y la diferencia no es cosmética:

- **Inmediatos** (tarjeta de crédito, tarjeta de débito). El pedido nace pagado
  y la pasarela es quien lo confirma. Hoy no hay pasarela conectada, así que
  ofrecerlos y dejar el pedido «pagado» sería registrar un cobro que nadie hizo.
- **Diferidos** (transferencia, Cheke Maxxa 30 días). El pedido nace **por
  pagar** y esa es su condición normal, no una anomalía: en distribución
  mayorista la orden se despacha contra una promesa de pago. No necesitan
  pasarela para ser correctos.

Por eso el pedido diferido se puede cerrar de verdad hoy y el inmediato no.
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
    #: `False` mientras no haya pasarela: se ofrece, pero no cierra el pedido.
    operativo: bool
    #: El pedido nace por pagar en vez de pagado.
    diferido: bool
    #: Exige crédito aprobado por Maxxa.
    requiere_credito: bool = False


MEDIOS: Dict[str, Medio] = {
    TARJETA_CREDITO: Medio(TARJETA_CREDITO, "Tarjeta de crédito",
                           operativo=False, diferido=False),
    TARJETA_DEBITO: Medio(TARJETA_DEBITO, "Tarjeta de débito",
                          operativo=False, diferido=False),
    TRANSFERENCIA: Medio(TRANSFERENCIA, "Transferencia bancaria",
                         operativo=True, diferido=True),
    MAXXA_30: Medio(MAXXA_30, "Cheke Maxxa 30 días",
                    operativo=True, diferido=True, requiere_credito=True),
}

# Orden en que se ofrecen. Explícito y no el del diccionario, para que reordenar
# la vitrina no dependa de en qué línea se declaró cada medio.
ORDEN = (TARJETA_CREDITO, TARJETA_DEBITO, TRANSFERENCIA, MAXXA_30)


def disponibles(*, tiene_credito: bool) -> list:
    """Los medios tal como debe verlos esta empresa.

    Se devuelven **todos**, incluidos los que no puede usar, con el motivo. Un
    listado que esconde «Cheke Maxxa 30 días» a quien no tiene crédito le oculta
    justamente la razón para solicitarlo.
    """
    salida = []
    for codigo in ORDEN:
        m = MEDIOS[codigo]
        motivo = None
        if m.requiere_credito and not tiene_credito:
            motivo = "sin_credito"
        elif not m.operativo:
            motivo = "no_operativo"
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
