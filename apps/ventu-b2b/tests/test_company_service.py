"""Tests del servicio de empresas: sin red, con un Saleor falso."""

from __future__ import annotations

import pytest

from ventu_b2b.company import service
from ventu_b2b.company.models import K_RAZON, K_RUT, Company

RUT = "76.543.210-3"
RUT_CANON = "76543210-3"


def _company(**kw):
    base = dict(rut=RUT, razon_social="Comercial Ventu SpA")
    base.update(kw)
    return Company(**base)


def _nodo(user_id="VXNlcjo1", rut=RUT_CANON, razon="Comercial Ventu SpA", priv=None):
    return {
        "id": user_id,
        "email": "compras@empresa.cl",
        "metadata": [{"key": K_RUT, "value": rut}, {"key": K_RAZON, "value": razon}],
        "privateMetadata": [{"key": k, "value": v} for k, v in (priv or {}).items()],
    }


def _router(*, encontrado=None, capturas=None):
    """Saleor falso. `capturas` recoge lo que se intentó escribir."""
    def gql(query, variables=None, **kw):
        variables = variables or {}
        if "customers(" in query:
            edges = [{"node": encontrado}] if encontrado else []
            return {"data": {"customers": {"edges": edges}}}
        if "user(id:" in query.replace(" ", "") or "user(id: $id)" in query:
            return {"data": {"user": encontrado}}
        if "updateMetadata" in query:
            if capturas is not None:
                capturas.append(("meta", variables.get("input")))
            return {"data": {"updateMetadata": {"errors": []}}}
        if "updatePrivateMetadata" in query:
            if capturas is not None:
                capturas.append(("privada", variables.get("input")))
            return {"data": {"updatePrivateMetadata": {"errors": []}}}
        raise AssertionError(f"query inesperada: {query[:50]}")
    return gql


# ───────────────────────── búsqueda por RUT ─────────────────────────

def test_busca_normalizando_el_rut(monkeypatch):
    """Sin normalizar, `76.543.210-3` y `765432103` no se encontrarían entre sí
    y la misma empresa se registraría dos veces."""
    vistos = {}

    def gql(query, variables=None, **kw):
        vistos.update(variables or {})
        return {"data": {"customers": {"edges": []}}}

    monkeypatch.setattr(service, "gql", gql)
    service.buscar_por_rut("76.543.210-3")
    assert vistos["value"] == RUT_CANON

    service.buscar_por_rut("765432103")
    assert vistos["value"] == RUT_CANON


def test_rut_no_registrado_devuelve_none(monkeypatch):
    monkeypatch.setattr(service, "gql", _router())
    assert service.buscar_por_rut(RUT) is None


def test_devuelve_usuario_y_empresa(monkeypatch):
    monkeypatch.setattr(service, "gql", _router(encontrado=_nodo()))
    user_id, company = service.buscar_por_rut(RUT)
    assert user_id == "VXNlcjo1"
    assert company.rut == RUT_CANON
    assert company.razon_social == "Comercial Ventu SpA"


# ───────────────────────── registro ─────────────────────────

def test_registra_escribiendo_ambas_metadatas(monkeypatch):
    capturas = []
    monkeypatch.setattr(service, "gql", _router(capturas=capturas))
    service.registrar("VXNlcjo1", _company(nivel_precio="b2b-cl"))

    tipos = [t for t, _ in capturas]
    assert tipos == ["meta", "privada"], "la metadata buscable se escribe primero"

    claves_meta = {p["key"] for p in capturas[0][1]}
    claves_priv = {p["key"] for p in capturas[1][1]}
    assert K_RUT in claves_meta
    assert "ventu.b2b.nivel_precio" in claves_priv
    assert "ventu.b2b.nivel_precio" not in claves_meta


def test_rut_de_otro_usuario_es_error_distinguible(monkeypatch):
    """El caso del colega de la misma empresa merece una respuesta propia, no un
    fallo genérico."""
    monkeypatch.setattr(service, "gql", _router(encontrado=_nodo(user_id="VXNlcjo5")))
    with pytest.raises(service.EmpresaYaRegistrada) as exc:
        service.registrar("VXNlcjo1", _company())
    assert exc.value.rut == RUT_CANON


def test_reregistrar_la_propia_empresa_no_falla(monkeypatch):
    """Actualizar los datos de la empresa propia debe seguir funcionando."""
    capturas = []
    monkeypatch.setattr(service, "gql",
                        _router(encontrado=_nodo(user_id="VXNlcjo1"), capturas=capturas))
    service.registrar("VXNlcjo1", _company(razon_social="Ventu SpA (nuevo)"))
    assert capturas, "debe haber escrito"


def test_error_de_saleor_al_escribir_no_pasa_inadvertido(monkeypatch):
    def gql(query, variables=None, **kw):
        if "customers(" in query:
            return {"data": {"customers": {"edges": []}}}
        return {"data": {"updateMetadata": {
            "errors": [{"field": "input", "message": "nope", "code": "INVALID"}]}}}

    monkeypatch.setattr(service, "gql", gql)
    with pytest.raises(RuntimeError, match="metadata"):
        service.registrar("VXNlcjo1", _company())


# ───────────────────────── lectura por usuario ─────────────────────────

def test_usuario_sin_empresa_devuelve_none(monkeypatch):
    monkeypatch.setattr(service, "gql", _router(encontrado={
        "id": "VXNlcjo1", "email": "x@y.cl", "metadata": [], "privateMetadata": []}))
    assert service.obtener_de_usuario("VXNlcjo1") is None


def test_usuario_con_empresa_la_devuelve(monkeypatch):
    monkeypatch.setattr(service, "gql", _router(
        encontrado=_nodo(priv={"ventu.b2b.nivel_precio": "b2b-cl"})))
    company = service.obtener_de_usuario("VXNlcjo1")
    assert company is not None
    assert company.nivel_precio == "b2b-cl"
