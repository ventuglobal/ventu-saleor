"""Solicitud y veredicto de crédito por la API: la hora y el autor los fija el
servidor, y un registro que no se guardó no se da por hecho."""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from ventu_b2b import main
from ventu_b2b.company.models import Company
from ventu_b2b.credito import estados as st
from ventu_b2b.credito import service as credito_service

USUARIO = "VXNlcjo1"
FECHA_INVENTADA = "2020-01-01T00:00:00Z"


@pytest.fixture
def cliente():
    return TestClient(main.app)


def _company(**kw):
    base = dict(rut="76.543.210-3", razon_social="Comercial Ventu SpA")
    base.update(kw)
    return Company(**base)


def _saleor(capturas, errores=None):
    def gql(query, variables=None, **kw):
        if "privateMetafield" in query:
            return {"data": {"user": {"privateMetafield": None}}}
        capturas.append({e["key"]: e["value"] for e in variables["input"]})
        return {"data": {"updatePrivateMetadata": {"errors": errores or []}}}
    return gql


def test_el_veredicto_ignora_la_hora_que_envia_quien_llama(monkeypatch, cliente):
    """Una hora provista por el cliente permitiría fechar una aprobación
    cuando convenga."""
    capturas = []
    monkeypatch.setattr(main.company_svc, "obtener_de_usuario",
                        lambda uid: _company(credito_estado=st.PENDIENTE))
    monkeypatch.setattr(credito_service, "gql", _saleor(capturas))

    r = cliente.post("/credito/resolver", json={
        "user_id": USUARIO, "veredicto": "aprobada", "referencia": "MX-42",
        "ahora": FECHA_INVENTADA, "actor": "staff@ejemplo.cl"})
    assert r.status_code == 200
    log = json.loads(capturas[0][credito_service.K_AUDIT])
    assert log[-1]["ts"] != FECHA_INVENTADA
    assert log[-1]["ts"].endswith("Z")
    assert log[-1]["actor"] == "staff@ejemplo.cl"


def test_la_solicitud_ignora_la_hora_y_registra_al_cliente(monkeypatch, cliente):
    capturas = []
    monkeypatch.setattr(main.company_svc, "obtener_de_usuario", lambda uid: _company())
    monkeypatch.setattr(credito_service, "gql", _saleor(capturas))

    r = cliente.post("/credito/solicitar", json={"user_id": USUARIO, "ahora": FECHA_INVENTADA})
    assert r.status_code == 200
    log = json.loads(capturas[0][credito_service.K_AUDIT])
    assert log[-1]["ts"] != FECHA_INVENTADA
    assert log[-1]["actor"] == "cliente"


def test_la_hora_ya_no_es_obligatoria(monkeypatch, cliente):
    capturas = []
    monkeypatch.setattr(main.company_svc, "obtener_de_usuario", lambda uid: _company())
    monkeypatch.setattr(credito_service, "gql", _saleor(capturas))
    assert cliente.post("/credito/solicitar", json={"user_id": USUARIO}).status_code == 200


def test_si_saleor_no_guarda_la_solicitud_es_502(monkeypatch, cliente):
    """Antes se respondía 422, como si la petición estuviera mal."""
    monkeypatch.setattr(main.company_svc, "obtener_de_usuario", lambda uid: _company())
    monkeypatch.setattr(credito_service, "gql", _saleor(
        [], errores=[{"field": "id", "message": "nope", "code": "NOT_FOUND"}]))
    r = cliente.post("/credito/solicitar", json={"user_id": USUARIO})
    assert r.status_code == 502


def test_si_saleor_no_guarda_el_veredicto_es_502(monkeypatch, cliente):
    monkeypatch.setattr(main.company_svc, "obtener_de_usuario",
                        lambda uid: _company(credito_estado=st.PENDIENTE))
    monkeypatch.setattr(credito_service, "gql", _saleor(
        [], errores=[{"field": "id", "message": "nope", "code": "NOT_FOUND"}]))
    r = cliente.post("/credito/resolver", json={"user_id": USUARIO, "veredicto": "aprobada"})
    assert r.status_code == 502


def test_solicitud_repetida_es_409(monkeypatch, cliente):
    monkeypatch.setattr(main.company_svc, "obtener_de_usuario",
                        lambda uid: _company(credito_estado=st.PENDIENTE))
    monkeypatch.setattr(credito_service, "gql", _saleor([]))
    assert cliente.post("/credito/solicitar", json={"user_id": USUARIO}).status_code == 409
