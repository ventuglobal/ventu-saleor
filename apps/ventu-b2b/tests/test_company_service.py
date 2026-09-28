"""Tests del servicio de empresas: sin red, con un Saleor falso."""

from __future__ import annotations

import pytest

from ventu_b2b.company import service
from ventu_b2b.company.models import K_ESTADO, K_NIVEL, K_RAZON, K_RUT, Company

RUT = "76.543.210-3"
RUT_CANON = "76543210-3"


def _company(**kw):
    base = dict(rut=RUT, razon_social="Comercial Ventu SpA")
    base.update(kw)
    return Company(**base)


def _nodo(user_id="VXNlcjo1", rut=RUT_CANON, razon="Comercial Ventu SpA", priv=None,
          publica=None):
    """Un usuario con empresa: la identidad en la privada (la que vale) y su
    índice en la pública. `publica` sobrescribe el índice, como lo haría el
    cliente; `priv` sobrescribe o agrega claves privadas."""
    meta = {K_RUT: rut, K_RAZON: razon, **(publica or {})}
    privada = {K_RUT: rut, K_RAZON: razon, **(priv or {})}
    return {
        "id": user_id,
        "email": "compras@empresa.cl",
        "metadata": [{"key": k, "value": v} for k, v in meta.items()],
        "privateMetadata": [{"key": k, "value": v} for k, v in privada.items() if v is not None],
    }


def _router(*, encontrado=None, capturas=None, antes=()):
    """Saleor falso. `capturas` recoge lo que se intentó escribir; `antes` son
    otros clientes que el filtro trae antes que `encontrado`."""
    def gql(query, variables=None, **kw):
        variables = variables or {}
        if "customers(" in query:
            edges = [{"node": n} for n in antes] + ([{"node": encontrado}] if encontrado else [])
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


def test_el_rut_puesto_a_mano_en_la_publica_no_ocupa_el_rut(monkeypatch):
    """La pública la escribe el cliente: poner un RUT ajeno en la propia no
    debe bastar para que la empresa real quede fuera del alta."""
    sin_alta = _nodo(user_id="VXNlcjo7", priv={K_RUT: None, K_RAZON: None})
    otro_rut = _nodo(user_id="VXNlcjo8", priv={K_RUT: "11111111-1"})
    monkeypatch.setattr(service, "gql", _router(antes=[sin_alta, otro_rut]))
    assert service.buscar_por_rut(RUT) is None


def test_encuentra_la_empresa_real_detras_de_un_impostor(monkeypatch):
    impostor = _nodo(user_id="VXNlcjo8", priv={K_RUT: "11111111-1"})
    monkeypatch.setattr(service, "gql",
                        _router(encontrado=_nodo(user_id="VXNlcjo1"), antes=[impostor]))
    user_id, company = service.buscar_por_rut(RUT)
    assert user_id == "VXNlcjo1"
    assert company.rut == RUT_CANON


def test_la_busqueda_pide_mas_de_un_candidato(monkeypatch):
    vistas = []

    def gql(query, variables=None, **kw):
        vistas.append(query)
        return {"data": {"customers": {"edges": []}}}

    monkeypatch.setattr(service, "gql", gql)
    service.buscar_por_rut(RUT)
    assert "first: 100" in vistas[0]


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
    assert {K_RUT, K_RAZON} <= claves_priv, "la identidad que vale es la privada"


@pytest.mark.parametrize("nivel,estado", [("retail-cl", "pendiente"),
                                          ("b2b-cl", "aprobada")])
def test_el_alta_escribe_el_estado_publico_y_la_fecha(monkeypatch, nivel, estado):
    """El estado va del lado buscable para poder listar las pendientes; la
    fecha de alta, para revisarlas por orden de llegada."""
    capturas = []
    monkeypatch.setattr(service, "gql", _router(capturas=capturas))
    service.registrar("VXNlcjo1", _company(nivel_precio=nivel))

    meta = {p["key"]: p["value"] for p in capturas[0][1]}
    priv = {p["key"]: p["value"] for p in capturas[1][1]}
    assert meta[K_ESTADO] == estado
    assert K_ESTADO not in priv
    assert priv[service.K_ALTA].endswith("Z")


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


def test_empresa_inventada_en_la_publica_no_existe(monkeypatch):
    """Sin alta no hay empresa, aunque el cliente escriba las claves a mano."""
    monkeypatch.setattr(service, "gql", _router(
        encontrado=_nodo(priv={K_RUT: None, K_RAZON: None})))
    assert service.obtener_de_usuario("VXNlcjo1") is None


def test_rut_publico_alterado_no_cambia_la_empresa(monkeypatch):
    monkeypatch.setattr(service, "gql", _router(encontrado=_nodo(
        publica={K_RUT: "11111111-1", K_RAZON: "Otra SpA"},
        priv={K_NIVEL: "b2b-cl"})))
    company = service.obtener_de_usuario("VXNlcjo1")
    assert company.rut == RUT_CANON
    assert company.razon_social == "Comercial Ventu SpA"


def test_rut_ilegible_no_es_un_500(monkeypatch, caplog):
    """RutInvalido no es CompanyInvalida: sin capturarlo, un RUT roto en una
    empresa antigua tumbaría el catálogo y el pedido."""
    antigua = _nodo(rut="x", priv={K_RUT: None, K_RAZON: None, K_NIVEL: "b2b-cl"})
    monkeypatch.setattr(service, "gql", _router(encontrado=antigua))
    assert service.obtener_de_usuario("VXNlcjo1") is None
    assert "ilegible" in caplog.text
