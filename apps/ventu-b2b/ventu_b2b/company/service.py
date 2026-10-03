"""Alta y consulta de empresas contra Saleor.

La Company vive en la metadata del usuario; este módulo la escribe y la lee. No
calcula precios ni decide condiciones de crédito: solo persiste identidad.
"""

from __future__ import annotations

import dataclasses
import logging
from typing import Dict, List, Optional, Tuple

from .. import auditoria
from ..saleor_client import SaleorRespuestaError, data_errors, gql, payload
from .models import (ESTADO_PENDIENTE, K_CONDICION, K_ESTADO, K_GIRO, K_NIVEL,
                     K_RAZON, K_RUT, K_TELEFONO, NS, Company, CompanyInvalida,
                     SinEmpresa, esta_aprobada, estado_de)
from . import rut as rut_mod

logger = logging.getLogger("ventu-b2b.company")

# Historial de cambios hechos por el staff (nivel de precio, condición de pago,
# datos de la empresa). Privado: revela condiciones comerciales.
K_LOG = f"{NS}.company_log"
# Cuándo se dio de alta la empresa (UTC). La fecha de la cuenta no basta: quien
# se registró sin empresa la completa después en `/empresa`, y el staff revisa
# por orden de llegada de la empresa, no de la cuenta.
K_ALTA = f"{NS}.alta"

# Campo de la Company → clave. Todo cambio va a la privada, que es la que
# manda; la identidad además al índice público (ver `actualizar`). El RUT no
# está: es la identidad de la empresa, y cambiarlo sería otra empresa.
_EDITABLES: Dict[str, str] = {
    "razon_social": K_RAZON,
    "giro": K_GIRO,
    "telefono": K_TELEFONO,
    "nivel_precio": K_NIVEL,
    "condicion_pago": K_CONDICION,
}

# Claves de identidad, en el orden en que se congelan en la privada.
_IDENTIDAD = (("rut", K_RUT), ("razon_social", K_RAZON),
              ("giro", K_GIRO), ("telefono", K_TELEFONO))

# Se piden varios y no el primero: la pública la escribe el cliente, así que
# cualquiera puede poner un RUT ajeno en la suya. Cada resultado se confirma
# contra la copia privada (ver `buscar_por_rut`).
_BUSCAR_POR_RUT = """
query($key: String!, $value: String!) {
  customers(first: 100, filter: {metadata: [{key: $key, value: $value}]}) {
    edges { node { id email metadata { key value } privateMetadata { key value } } }
  }
}
"""

_USUARIO = """
query($id: ID!) {
  user(id: $id) { id email firstName metadata { key value } privateMetadata { key value } }
}
"""

# Saleor no deja pedir más de 100 por página; el tope de páginas evita que un
# filtro que dejó de filtrar (clave mal escrita, espejo roto) recorra la base de
# clientes entera en una sola petición del staff.
POR_PAGINA = 100
MAX_PAGINAS = 10

# Las más antiguas primero: son las que llevan más tiempo esperando, y si la
# lista se trunca, lo que queda afuera es lo más reciente.
_PENDIENTES = """
query($key: String!, $value: String!, $first: Int!, $after: String) {
  customers(first: $first, after: $after,
            filter: {metadata: [{key: $key, value: $value}]},
            sortBy: {field: CREATED_AT, direction: ASC}) {
    pageInfo { hasNextPage endCursor }
    edges { node {
      id email firstName lastName isActive isConfirmed dateJoined
      metadata { key value } privateMetadata { key value }
    } }
  }
}
"""

_ESCRIBIR_META = """
mutation($id: ID!, $input: [MetadataInput!]!) {
  updateMetadata(id: $id, input: $input) {
    errors { field message code }
  }
}
"""

_ESCRIBIR_PRIVADA = """
mutation($id: ID!, $input: [MetadataInput!]!) {
  updatePrivateMetadata(id: $id, input: $input) {
    errors { field message code }
  }
}
"""


class EmpresaYaRegistrada(RuntimeError):
    """El RUT ya pertenece a otro usuario.

    Es el caso frecuente del colega de la misma empresa. En el modelo 1 usuario =
    1 empresa no hay resolución automática, así que se distingue del resto de los
    errores para poder responderle algo digno en vez de un fallo genérico.
    """

    def __init__(self, rut: str, email: str = ""):
        self.rut = rut
        self.email = email
        super().__init__(f"el RUT {rut} ya está registrado")


@dataclasses.dataclass(frozen=True)
class Actualizacion:
    """Resultado de `actualizar`: la empresa y lo que hace falta para avisar."""
    company: Company
    # El PATCH la dejó habilitada para comprar y antes no lo estaba.
    recien_aprobada: bool
    email: Optional[str]
    nombre: Optional[str]


def _pares_a_dict(pares) -> dict:
    return {p["key"]: p["value"] for p in (pares or [])}


def buscar_por_rut(rut_libre: str) -> Optional[Tuple[str, Company]]:
    """Devuelve `(user_id, Company)` si el RUT ya está registrado.

    Normaliza antes de buscar: sin eso `76.543.210-3` y `765432103` no se
    encontrarían entre sí y la misma empresa se registraría dos veces.

    Saleor solo filtra por la metadata pública, que el cliente puede escribir:
    el filtro trae candidatos y cuenta solo el que tiene ese RUT en su copia
    privada. Sin esto, cualquiera ocuparía el RUT de otra empresa poniéndolo en
    su metadata, y el alta de la empresa real chocaría con él.
    """
    rut = rut_mod.normalizar(rut_libre)
    body = gql(_BUSCAR_POR_RUT, {"key": K_RUT, "value": rut})
    if data_errors(body):
        raise SaleorRespuestaError(f"búsqueda por RUT: {data_errors(body)}")

    edges = ((payload(body).get("customers") or {}).get("edges")) or []
    for arista in edges:
        nodo = arista.get("node") or {}
        try:
            company = Company.from_metadata(_pares_a_dict(nodo.get("metadata")),
                                            _pares_a_dict(nodo.get("privateMetadata")))
        except ValueError:  # sin empresa de verdad, o ilegible: no ocupa el RUT
            continue
        if company.rut == rut:
            return nodo["id"], company
    return None


def _leer_usuario(user_id: str) -> Optional[dict]:
    body = gql(_USUARIO, {"id": user_id})
    if data_errors(body):
        raise SaleorRespuestaError(f"lectura de usuario: {data_errors(body)}")
    return payload(body).get("user")


def _escribir(user_id: str, query: str, datos: Dict[str, str], etiqueta: str) -> None:
    if not datos:
        return
    entrada = [{"key": k, "value": v} for k, v in datos.items()]
    res = gql(query, {"id": user_id, "input": entrada})
    if data_errors(res):
        raise SaleorRespuestaError(f"{etiqueta}: {data_errors(res)}")
    clave = "updateMetadata" if "updateMetadata" in query else "updatePrivateMetadata"
    errs = (payload(res).get(clave) or {}).get("errors") or []
    if errs:
        raise SaleorRespuestaError(f"{etiqueta}: {errs}")


def obtener_de_usuario(user_id: str) -> Optional[Company]:
    """Company asociada al usuario, o `None` si todavía no tiene."""
    nodo = _leer_usuario(user_id)
    if not nodo:
        return None
    try:
        return Company.from_metadata(_pares_a_dict(nodo.get("metadata")),
                                     _pares_a_dict(nodo.get("privateMetadata")))
    except SinEmpresa:
        return None
    except ValueError as exc:  # CompanyInvalida o RutInvalido
        # Un dato ilegible no debe tumbar el catálogo ni el pedido con un 500:
        # para la app no hay empresa, y queda rastro para corregirla.
        logger.warning("(b2b) empresa ilegible (%s): %s", user_id, exc)
        return None


def registrar(user_id: str, company: Company) -> Company:
    """Asocia la empresa al usuario.

    Verifica primero que el RUT no pertenezca a otro usuario. La comprobación no
    es transaccional —Saleor no ofrece unicidad sobre metadata— pero al volumen
    del MVP la carrera es improbable y el costo de detectarla aquí es nulo.
    """
    existente = buscar_por_rut(company.rut)
    if existente and existente[0] != user_id:
        raise EmpresaYaRegistrada(company.rut)

    # La pública primero: si fallara la privada, lo escrito es solo índice
    # —sin la copia privada no hay empresa— y el alta se reintenta sin más. Al
    # revés, quedaría una empresa válida sin índice, invisible para el control
    # de RUT duplicado.
    _escribir(user_id, _ESCRIBIR_META, company.to_metadata(), "metadata")
    _escribir(user_id, _ESCRIBIR_PRIVADA,
              {**company.to_private_metadata(), K_ALTA: auditoria.ahora_utc()},
              "privateMetadata")
    return company


def actualizar(user_id: str, cambios: Dict[str, str], *, actor: str,
               ahora: str) -> Optional[Actualizacion]:
    """Aplica cambios del staff a la empresa del usuario y deja registro.

    Devuelve la empresa resultante y si el cambio la aprobó (ver
    `Actualizacion`), o `None` si el usuario no tiene empresa. La validación
    de cada valor la hace `Company` al reconstruirse: así un cambio no puede
    dejar una empresa que el resto de la app no sabría leer.

    Solo se escriben las claves que cambian. Reescribir la empresa entera
    —como hace el alta— pisaría el estado de crédito si una solicitud se
    resolvió entre la lectura y la escritura.

    Si el cambio toca `nivel_precio`, además se pone al día el espejo público
    del estado (`K_ESTADO`), aunque el nivel no cambie: reenviar el nivel
    vigente es la forma de reparar una empresa anterior al espejo, o uno que
    quedó atrás por una escritura a medias.

    Cualquier PATCH, además, repara la identidad: la congela en la privada si
    la empresa es anterior a esa copia, y rehace el índice público si el
    cliente lo alteró. Ninguna de las dos cosas va al historial.
    """
    desconocidos = set(cambios) - set(_EDITABLES)
    if desconocidos:
        raise CompanyInvalida(f"campos no editables: {sorted(desconocidos)}")

    nodo = _leer_usuario(user_id)
    if not nodo:
        return None
    meta = _pares_a_dict(nodo.get("metadata"))
    privada = _pares_a_dict(nodo.get("privateMetadata"))
    try:
        actual = Company.from_metadata(meta, privada)
    except SinEmpresa:
        return None
    except ValueError as exc:  # CompanyInvalida o RutInvalido
        raise CompanyInvalida(f"la empresa guardada no se puede leer: {exc}") from exc

    nueva = dataclasses.replace(actual, **cambios)
    diferencias = {campo: [getattr(actual, campo), getattr(nueva, campo)]
                   for campo in cambios
                   if getattr(actual, campo) != getattr(nueva, campo)}

    publica: Dict[str, str] = {}
    oculta: Dict[str, str] = {}
    for campo in diferencias:
        oculta[_EDITABLES[campo]] = getattr(nueva, campo)
    congelar = not privada.get(K_RUT)
    for campo, clave in _IDENTIDAD:
        valor = getattr(nueva, campo)
        if congelar and valor:
            # Empresa anterior a la copia privada: desde aquí manda la privada
            # y el cliente ya no puede cambiar su identidad.
            oculta[clave] = valor
        if meta.get(clave, "") != valor:
            # El índice sigue a la privada: sea el cambio del staff o una
            # alteración del cliente, queda igual a lo que vale.
            publica[clave] = valor
    if "nivel_precio" in cambios and meta.get(K_ESTADO) != estado_de(nueva):
        publica[K_ESTADO] = estado_de(nueva)
    # Recién aprobada: el nivel pasa a B2B, o ya lo era pero el espejo seguía
    # «pendiente» —una escritura a medias que el staff repara reenviando el
    # nivel, y cuyo aviso no alcanzó a salir—. Una empresa antigua sin espejo
    # que ya compraba no cuenta: reparar su espejo no es aprobarla.
    resultado = Actualizacion(
        company=nueva,
        recien_aprobada=esta_aprobada(nueva) and (
            not esta_aprobada(actual) or meta.get(K_ESTADO) == ESTADO_PENDIENTE),
        email=nodo.get("email"), nombre=nodo.get("firstName"))
    if not publica and not oculta:
        return resultado
    if diferencias:
        # Reparar el espejo no es un cambio de la empresa: no va al historial.
        oculta[K_LOG] = auditoria.anexar(privada.get(K_LOG, ""), {
            "ts": ahora, "actor": actor, "cambios": diferencias})

    # La privada primero: el nivel es la fuente de verdad y el estado solo su
    # reflejo. Si fallara la pública, la empresa ya compra como corresponde y
    # el espejo se repara reenviando el PATCH. Al revés, un espejo «aprobada»
    # sobre un nivel que no se alcanzó a escribir escondería de `/pendientes`
    # a una empresa que sigue esperando.
    _escribir(user_id, _ESCRIBIR_PRIVADA, oculta, "privateMetadata")
    _escribir(user_id, _ESCRIBIR_META, publica, "metadata")
    return resultado


def pendientes(max_paginas: Optional[int] = None) -> Tuple[List[dict], bool]:
    """Empresas que esperan la revisión del staff, las más antiguas primero.

    Devuelve `(empresas, truncado)`; `truncado` avisa que quedaron páginas sin
    leer por el tope, para que nadie tome la lista por completa.

    Filtra por el espejo público (`K_ESTADO = pendiente`) porque Saleor no
    filtra por `privateMetadata`, donde vive el nivel. Consecuencia: una empresa
    registrada antes del espejo **no aparece** hasta que un PATCH con su nivel
    lo escriba. Y como el espejo puede quedar atrás del nivel, cada resultado se
    confirma contra el nivel antes de listarlo.
    """
    empresas: List[dict] = []
    cursor: Optional[str] = None
    for _ in range(max_paginas or MAX_PAGINAS):
        body = gql(_PENDIENTES, {"key": K_ESTADO, "value": ESTADO_PENDIENTE,
                                 "first": POR_PAGINA, "after": cursor})
        if data_errors(body):
            raise SaleorRespuestaError(f"empresas pendientes: {data_errors(body)}")
        conexion = payload(body).get("customers") or {}
        for arista in conexion.get("edges") or []:
            fila = _fila_pendiente(arista.get("node") or {})
            if fila:
                empresas.append(fila)
        pagina = conexion.get("pageInfo") or {}
        if not pagina.get("hasNextPage"):
            return empresas, False
        cursor = pagina.get("endCursor")
        if not cursor:
            # Sin cursor no hay cómo seguir; mejor avisar que repetir la página.
            return empresas, True
    return empresas, True


def _fila_pendiente(nodo: dict) -> Optional[dict]:
    meta = _pares_a_dict(nodo.get("metadata"))
    privada = _pares_a_dict(nodo.get("privateMetadata"))
    try:
        company = Company.from_metadata(meta, privada)
    except ValueError as exc:  # CompanyInvalida o RutInvalido
        # Una empresa ilegible no se puede aprobar desde aquí; que no tape a
        # las demás, pero que quede rastro para corregirla.
        logger.warning("(b2b) empresa pendiente ilegible (%s): %s", nodo.get("id"), exc)
        return None
    if esta_aprobada(company):
        # Espejo atrasado: el nivel ya es B2B. No está pendiente, se liste o no.
        return None
    nombre = " ".join(p for p in (nodo.get("firstName"), nodo.get("lastName")) if p)
    return {
        "user_id": nodo.get("id"),
        "email": nodo.get("email"),
        "nombre": nombre,
        "rut": company.rut,
        "razon_social": company.razon_social,
        "giro": company.giro,
        "telefono": company.telefono,
        "nivel_precio": company.nivel_precio,
        "cuenta_creada": nodo.get("dateJoined"),
        # `None` en empresas anteriores a este registro: no se inventa la fecha.
        "empresa_registrada": privada.get(K_ALTA),
        "correo_confirmado": nodo.get("isConfirmed"),
        "activa": nodo.get("isActive"),
    }
