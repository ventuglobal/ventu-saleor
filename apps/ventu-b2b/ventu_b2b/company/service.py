"""Alta y consulta de empresas contra Saleor.

La Company vive en la metadata del usuario; este módulo la escribe y la lee. No
calcula precios ni decide condiciones de crédito: solo persiste identidad.
"""

from __future__ import annotations

from typing import Optional, Tuple

from ..saleor_client import data_errors, gql, payload
from .models import K_RUT, Company, CompanyInvalida
from . import rut as rut_mod

_BUSCAR_POR_RUT = """
query($key: String!, $value: String!) {
  customers(first: 2, filter: {metadata: [{key: $key, value: $value}]}) {
    edges { node { id email metadata { key value } privateMetadata { key value } } }
  }
}
"""

_USUARIO = """
query($id: ID!) {
  user(id: $id) { id email metadata { key value } privateMetadata { key value } }
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


def _pares_a_dict(pares) -> dict:
    return {p["key"]: p["value"] for p in (pares or [])}


def buscar_por_rut(rut_libre: str) -> Optional[Tuple[str, Company]]:
    """Devuelve `(user_id, Company)` si el RUT ya está registrado.

    Normaliza antes de buscar: sin eso `76.543.210-3` y `765432103` no se
    encontrarían entre sí y la misma empresa se registraría dos veces.
    """
    rut = rut_mod.normalizar(rut_libre)
    body = gql(_BUSCAR_POR_RUT, {"key": K_RUT, "value": rut})
    if data_errors(body):
        raise RuntimeError(f"búsqueda por RUT: {data_errors(body)}")

    edges = ((payload(body).get("customers") or {}).get("edges")) or []
    if not edges:
        return None

    nodo = edges[0]["node"]
    company = Company.from_metadata(_pares_a_dict(nodo.get("metadata")),
                                    _pares_a_dict(nodo.get("privateMetadata")))
    return nodo["id"], company


def obtener_de_usuario(user_id: str) -> Optional[Company]:
    """Company asociada al usuario, o `None` si todavía no tiene."""
    body = gql(_USUARIO, {"id": user_id})
    if data_errors(body):
        raise RuntimeError(f"lectura de usuario: {data_errors(body)}")

    nodo = payload(body).get("user")
    if not nodo:
        return None
    try:
        return Company.from_metadata(_pares_a_dict(nodo.get("metadata")),
                                     _pares_a_dict(nodo.get("privateMetadata")))
    except CompanyInvalida:
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

    def _escribir(query: str, datos: dict, etiqueta: str) -> None:
        if not datos:
            return
        entrada = [{"key": k, "value": v} for k, v in datos.items()]
        res = gql(query, {"id": user_id, "input": entrada})
        if data_errors(res):
            raise RuntimeError(f"{etiqueta}: {data_errors(res)}")
        clave = "updateMetadata" if "updateMetadata" in query else "updatePrivateMetadata"
        errs = (payload(res).get(clave) or {}).get("errors") or []
        if errs:
            raise RuntimeError(f"{etiqueta}: {errs}")

    # La metadata buscable primero: si fallara la privada, la empresa queda
    # localizable por RUT y el registro se puede reintentar sin duplicar.
    _escribir(_ESCRIBIR_META, company.to_metadata(), "metadata")
    _escribir(_ESCRIBIR_PRIVADA, company.to_private_metadata(), "privateMetadata")
    return company
