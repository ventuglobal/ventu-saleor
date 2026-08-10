"""Solicitudes de crédito: estado, auditoría y entrega a Maxxa.

La App B2B **no** es un sistema financiero. Registra el estado de la solicitud y
una referencia al sistema que administra la línea; el cálculo del cupo y su
ejecución pertenecen a Maxxa.

**Custodia de la Carpeta Tributaria.** Ventu la recibe y la reenvía, así que
queda en la ruta del dato y asume obligaciones sobre el historial tributario del
cliente. El diseño minimiza la ventana de exposición: se entrega a Maxxa y se
borra en cuanto la entrega está confirmada. Recibir y reenviar no obliga a
conservar.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Callable, Optional

from ..company.models import K_CREDITO, K_CREDITO_REF, Company
from ..saleor_client import data_errors, gql, payload
from . import estados as st

logger = logging.getLogger("ventu-b2b.credito")

# La auditoría vive fuera de la metadata: la metadata se sobrescribe y no
# conserva historial. Sin esto, «¿por qué esta empresa tiene crédito aprobado?»
# no tiene respuesta.
K_AUDIT = "ventu.b2b.credito_log"

_ESCRIBIR_PRIVADA = """
mutation($id: ID!, $input: [MetadataInput!]!) {
  updatePrivateMetadata(id: $id, input: $input) {
    errors { field message code }
  }
}
"""


class CreditoError(RuntimeError):
    """No se pudo operar sobre la solicitud."""


class EntregaFallida(CreditoError):
    """La Carpeta no llegó a Maxxa.

    Se distingue del resto porque determina si el documento puede borrarse: solo
    se borra tras una entrega confirmada, para no perder el único ejemplar que
    el cliente subió.
    """


@dataclass(frozen=True)
class Solicitud:
    company_rut: str
    estado: str
    referencia: str = ""


def _registrar(user_id: str, transicion: st.Transicion, *, ahora: str) -> None:
    """Escribe el estado nuevo y añade la transición al registro de auditoría.

    `ahora` se recibe como parámetro y no se toma del reloj interno para que el
    registro sea reproducible en los tests y para que quien llame decida la
    fuente de tiempo.
    """
    entrada = [
        {"key": K_CREDITO, "value": transicion.hacia},
        {"key": K_AUDIT, "value": f"{ahora}|{transicion.desde}>{transicion.hacia}"
                                  f"|{transicion.motivo}|{transicion.referencia}"},
    ]
    if transicion.referencia:
        entrada.append({"key": K_CREDITO_REF, "value": transicion.referencia})

    res = gql(_ESCRIBIR_PRIVADA, {"id": user_id, "input": entrada})
    if data_errors(res):
        raise CreditoError(f"registrar crédito: {data_errors(res)}")
    errs = (payload(res).get("updatePrivateMetadata") or {}).get("errors") or []
    if errs:
        raise CreditoError(f"registrar crédito: {errs}")


def solicitar(user_id: str, company: Company, *, ahora: str) -> Solicitud:
    """Abre una solicitud de crédito. Paso voluntario: no bloquea la compra al
    contado."""
    transicion = st.aplicar(company.credito_estado, st.PENDIENTE,
                            motivo="solicitud del cliente")
    _registrar(user_id, transicion, ahora=ahora)
    return Solicitud(company_rut=company.rut, estado=st.PENDIENTE)


def entregar_carpeta(
    company: Company,
    documento: bytes,
    *,
    enviar_a_maxxa: Callable[[str, bytes], str],
    borrar_local: Optional[Callable[[], None]] = None,
) -> str:
    """Entrega la Carpeta Tributaria a Maxxa y borra la copia local.

    `enviar_a_maxxa` devuelve la referencia de la solicitud en Maxxa. El borrado
    solo ocurre **después** de una entrega confirmada: si el envío falla, el
    documento se conserva para poder reintentar, porque es el único ejemplar que
    el cliente subió y pedírselo de nuevo es una fricción real.
    """
    if not documento:
        raise CreditoError("carpeta vacía")

    try:
        referencia = enviar_a_maxxa(company.rut, documento)
    except Exception as exc:  # noqa: BLE001 — cualquier fallo del tercero
        raise EntregaFallida(f"Maxxa no recibió la carpeta: {exc}") from exc

    if not referencia:
        raise EntregaFallida("Maxxa no devolvió referencia de la solicitud")

    if borrar_local is not None:
        try:
            borrar_local()
        except Exception as exc:  # noqa: BLE001
            # La entrega ya está hecha: no se puede deshacer y el flujo debe
            # continuar. Pero un documento tributario que no se borró es
            # exposición retenida, así que queda registrado para revisarlo.
            logger.error("(credito) carpeta entregada pero NO borrada (rut=%s): %s",
                         company.rut, exc)

    return referencia


def resolver(user_id: str, company: Company, veredicto: str, *, ahora: str,
             referencia: str = "") -> Solicitud:
    """Registra el resultado que devuelve Maxxa.

    Un veredicto que no se entiende deja la solicitud pendiente en vez de
    adivinar: interpretarlo mal significaría otorgar o negar crédito por error.
    """
    destino = st.resultado_maxxa(veredicto)
    if destino is None:
        logger.warning("(credito) veredicto no reconocido (rut=%s): %r",
                       company.rut, veredicto)
        return Solicitud(company_rut=company.rut, estado=company.credito_estado,
                         referencia=company.credito_ref)

    transicion = st.aplicar(company.credito_estado, destino,
                            motivo=f"veredicto Maxxa: {veredicto}",
                            referencia=referencia)
    _registrar(user_id, transicion, ahora=ahora)
    return Solicitud(company_rut=company.rut, estado=destino, referencia=referencia)
