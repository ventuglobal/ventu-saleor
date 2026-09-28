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

from .. import auditoria
from ..company.models import K_CREDITO, K_CREDITO_REF, Company
from ..saleor_client import SaleorError, data_errors, gql, payload
from . import estados as st

logger = logging.getLogger("ventu-b2b.credito")

# Historial de transiciones de crédito (lista JSON acotada, ver `auditoria`). El
# estado vigente se sobrescribe; sin esto, «¿por qué esta empresa tiene crédito
# aprobado?» no tiene respuesta.
K_AUDIT = "ventu.b2b.credito_log"

# Se lee solo la clave del historial: la metadata completa del usuario no hace
# falta para anexar una entrada.
_LEER_LOG = """
query($id: ID!, $key: String!) {
  user(id: $id) { privateMetafield(key: $key) }
}
"""

_ESCRIBIR_PRIVADA = """
mutation($id: ID!, $input: [MetadataInput!]!) {
  updatePrivateMetadata(id: $id, input: $input) {
    errors { field message code }
  }
}
"""


class CreditoError(RuntimeError):
    """No se pudo operar sobre la solicitud."""


class RegistroFallido(CreditoError):
    """Saleor no guardó el cambio de estado (o no se pudo leer el historial).

    Es un fallo del servidor, no de la solicitud: la API lo responde como 502
    para que el cliente reintente en vez de corregir algo que está bien.
    """


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


def _historial(user_id: str) -> str:
    try:
        res = gql(_LEER_LOG, {"id": user_id, "key": K_AUDIT})
    except SaleorError as exc:
        raise RegistroFallido(f"leer historial de crédito: {exc}") from exc
    if data_errors(res):
        raise RegistroFallido(f"leer historial de crédito: {data_errors(res)}")
    return ((payload(res).get("user") or {}).get("privateMetafield")) or ""


def _registrar(user_id: str, transicion: st.Transicion, *, ahora: str,
               actor: str = "") -> None:
    """Escribe el estado nuevo y anexa la transición al historial.

    `ahora` se recibe como parámetro para que el registro sea reproducible en
    los tests; en la API lo fija el servidor (`auditoria.ahora_utc`), nunca
    quien llama.

    Si no se puede leer el historial previo no se escribe nada: registrar el
    cambio sin la historia la borraría.
    """
    registro = auditoria.anexar(_historial(user_id), {
        "ts": ahora,
        "transicion": f"{transicion.desde}>{transicion.hacia}",
        "motivo": transicion.motivo,
        "referencia": transicion.referencia,
        "actor": actor,
    })
    entrada = [
        {"key": K_CREDITO, "value": transicion.hacia},
        {"key": K_AUDIT, "value": registro},
    ]
    if transicion.referencia:
        entrada.append({"key": K_CREDITO_REF, "value": transicion.referencia})

    try:
        res = gql(_ESCRIBIR_PRIVADA, {"id": user_id, "input": entrada})
    except SaleorError as exc:
        raise RegistroFallido(f"registrar crédito: {exc}") from exc
    if data_errors(res):
        raise RegistroFallido(f"registrar crédito: {data_errors(res)}")
    errs = (payload(res).get("updatePrivateMetadata") or {}).get("errors") or []
    if errs:
        raise RegistroFallido(f"registrar crédito: {errs}")


def solicitar(user_id: str, company: Company, *, ahora: str) -> Solicitud:
    """Abre una solicitud de crédito. Paso voluntario: no bloquea la compra al
    contado."""
    transicion = st.aplicar(company.credito_estado, st.PENDIENTE,
                            motivo="solicitud del cliente")
    _registrar(user_id, transicion, ahora=ahora, actor="cliente")
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
             referencia: str = "", actor: str = "") -> Solicitud:
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
    _registrar(user_id, transicion, ahora=ahora, actor=actor)
    return Solicitud(company_rut=company.rut, estado=destino, referencia=referencia)
