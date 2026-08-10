"""Máquina de estados de la solicitud de crédito.

Módulo **puro**: valida transiciones. No habla con Saleor ni con Maxxa.

    sin_solicitud ──► pendiente ──► aprobada
                          │
                          └──────► rechazada ──► pendiente   (nueva solicitud)

Una decisión de crédito es financieramente consecuente, así que las
transiciones son explícitas y cerradas: cualquier salto no listado se rechaza en
vez de asumirse. Concretamente, no se puede pasar de `sin_solicitud` a
`aprobada` sin evaluación de por medio.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Optional, Tuple

SIN_SOLICITUD = "sin_solicitud"
PENDIENTE = "pendiente"
APROBADA = "aprobada"
RECHAZADA = "rechazada"

ESTADOS = (SIN_SOLICITUD, PENDIENTE, APROBADA, RECHAZADA)

# origen → destinos permitidos
_TRANSICIONES: Dict[str, Tuple[str, ...]] = {
    SIN_SOLICITUD: (PENDIENTE,),
    # Una solicitud pendiente puede resolverse en cualquier sentido.
    PENDIENTE: (APROBADA, RECHAZADA),
    # Una empresa rechazada puede volver a postular más adelante: su situación
    # tributaria cambia con el tiempo y el rechazo no debe ser definitivo.
    RECHAZADA: (PENDIENTE,),
    # Una línea aprobada puede revocarse (deja de tener crédito) o renovarse.
    APROBADA: (PENDIENTE, RECHAZADA),
}


class TransicionInvalida(ValueError):
    """El cambio de estado pedido no está permitido."""

    def __init__(self, desde: str, hacia: str):
        self.desde = desde
        self.hacia = hacia
        super().__init__(f"transición no permitida: {desde} → {hacia}")


@dataclass(frozen=True)
class Transicion:
    """Un cambio de estado con su motivo. Es la unidad del registro de auditoría."""

    desde: str
    hacia: str
    motivo: str = ""
    referencia: str = ""

    def __post_init__(self) -> None:
        validar(self.desde, self.hacia)


def es_valido(estado: str) -> bool:
    return estado in ESTADOS


def validar(desde: str, hacia: str) -> None:
    """Lanza `TransicionInvalida` si el cambio no está permitido."""
    if not es_valido(desde):
        raise TransicionInvalida(desde, hacia)
    if not es_valido(hacia):
        raise TransicionInvalida(desde, hacia)
    if hacia not in _TRANSICIONES.get(desde, ()):
        raise TransicionInvalida(desde, hacia)


def puede(desde: str, hacia: str) -> bool:
    try:
        validar(desde, hacia)
        return True
    except TransicionInvalida:
        return False


def destinos(desde: str) -> Tuple[str, ...]:
    """Estados alcanzables desde uno dado. Útil para la interfaz de operaciones."""
    return _TRANSICIONES.get(desde, ())


def aplicar(desde: str, hacia: str, *, motivo: str = "",
            referencia: str = "") -> Transicion:
    """Valida y devuelve la transición, lista para registrar en la auditoría."""
    return Transicion(desde=desde, hacia=hacia, motivo=motivo, referencia=referencia)


def resultado_maxxa(veredicto: str) -> Optional[str]:
    """Traduce el veredicto de Maxxa al estado interno.

    Devuelve `None` ante un veredicto desconocido: es preferible dejar la
    solicitud pendiente y revisarla a mano que interpretar mal la respuesta de
    un tercero y otorgar crédito por error.
    """
    normalizado = (veredicto or "").strip().lower()
    if normalizado in ("aprobada", "approved", "aprobado", "ok"):
        return APROBADA
    if normalizado in ("rechazada", "rejected", "rechazado", "denied"):
        return RECHAZADA
    return None
