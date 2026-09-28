"""Manifest y registro de la Saleor App.

Detrás del proxy de Railway el proceso ve http; Saleor no instala una app que
se anuncia sin TLS.
"""

from __future__ import annotations

import logging

import pytest
from fastapi.testclient import TestClient

from ventu_b2b import config, main


@pytest.fixture
def cliente():
    return TestClient(main.app)


def test_detras_del_proxy_se_anuncia_https(cliente):
    d = cliente.get("/manifest", headers={"X-Forwarded-Proto": "https",
                                          "X-Forwarded-Host": "b2b.ejemplo.cl"}).json()
    assert d["appUrl"] == "https://b2b.ejemplo.cl"
    assert d["tokenTargetUrl"] == "https://b2b.ejemplo.cl/register"


def test_encabezados_con_varios_saltos_usan_el_primero(cliente):
    d = cliente.get("/manifest", headers={"X-Forwarded-Proto": "https, http",
                                          "X-Forwarded-Host": "b2b.ejemplo.cl, interno"}).json()
    assert d["appUrl"] == "https://b2b.ejemplo.cl"


def test_la_url_publica_configurada_manda(monkeypatch, cliente):
    monkeypatch.setattr(config, "PUBLIC_URL", "https://b2b.ventu.cl")
    d = cliente.get("/manifest", headers={"X-Forwarded-Proto": "http",
                                          "X-Forwarded-Host": "otro.cl"}).json()
    assert d["appUrl"] == "https://b2b.ventu.cl"
    assert d["tokenTargetUrl"] == "https://b2b.ventu.cl/register"


def test_sin_proxy_un_host_publico_es_https(cliente):
    d = cliente.get("/manifest", headers={"Host": "b2b.ejemplo.cl"}).json()
    assert d["appUrl"] == "https://b2b.ejemplo.cl"


def test_en_local_se_mantiene_http():
    local = TestClient(main.app, base_url="http://localhost:8000")
    assert local.get("/manifest").json()["appUrl"] == "http://localhost:8000"


def test_un_proto_desconocido_no_se_copia(cliente):
    d = cliente.get("/manifest", headers={"X-Forwarded-Proto": "javascript",
                                          "Host": "b2b.ejemplo.cl"}).json()
    assert d["appUrl"] == "https://b2b.ejemplo.cl"


def test_el_manifest_declara_impersonate_user(cliente):
    """`checkoutCustomerAttach` lo exige para asociar un carrito a un cliente."""
    permisos = cliente.get("/manifest").json()["permissions"]
    assert "IMPERSONATE_USER" in permisos
    assert {"MANAGE_USERS", "HANDLE_CHECKOUTS"} <= set(permisos)


def test_register_no_registra_el_token(cliente, caplog):
    caplog.set_level(logging.DEBUG)
    token = "tok-instalacion-de-prueba-123456"
    r = cliente.post("/register", json={"auth_token": token})
    assert r.status_code == 200
    assert token not in caplog.text
    assert token[:8] not in caplog.text
    assert "registrada" in caplog.text


def test_register_sin_token_es_400(cliente):
    assert cliente.post("/register", json={}).status_code == 400
