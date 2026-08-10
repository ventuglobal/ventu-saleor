"""Tests del carrito de WhatsApp: sin red, con un Saleor falso."""

from __future__ import annotations

import pytest

from ventu_b2b.cart import service
from ventu_b2b.cart.service import Carrito, CarritoError, Linea

VAR = "UHJvZHVjdFZhcmlhbnQ6MQ=="


def _router(*, capturas=None, encontrado=None, errores=None):
    def gql(query, variables=None, **kw):
        variables = variables or {}
        if "checkoutCreate" in query:
            if capturas is not None:
                capturas.append(variables["input"])
            if errores:
                return {"data": {"checkoutCreate": {"checkout": None, "errors": errores}}}
            return {"data": {"checkoutCreate": {
                "checkout": {"id": "Q2hlY2tvdXQ6MQ==", "token": "tok-1"}, "errors": []}}}
        if "checkouts(" in query:
            edges = [{"node": encontrado}] if encontrado else []
            return {"data": {"checkouts": {"edges": edges}}}
        if "checkoutCustomerAttach" in query:
            return {"data": {"checkoutCustomerAttach": {"errors": errores or []}}}
        raise AssertionError(f"query inesperada: {query[:50]}")
    return gql


# ───────────────────────── líneas ─────────────────────────

def test_linea_sin_precio_usa_el_del_canal():
    entrada = Linea(VAR, 3).to_input()
    assert entrada == {"variantId": VAR, "quantity": 3}
    assert "price" not in entrada


def test_linea_con_precio_negociado_lo_declara():
    """Saleor exige explicar por qué se sobrescribe el precio de lista; queda
    como rastro comercial en el checkout."""
    entrada = Linea(VAR, 10, precio_unitario=900.0).to_input()
    assert entrada["price"] == 900.0
    assert entrada["priceOverrideReason"]


# ───────────────────────── creación ─────────────────────────

def test_crea_en_el_canal_b2b_y_marca_el_origen(monkeypatch):
    capturas = []
    monkeypatch.setattr(service, "gql", _router(capturas=capturas))
    carrito = service.crear([Linea(VAR, 5)])

    entrada = capturas[0]
    assert entrada["channel"] == "b2b-cl"
    meta = {p["key"]: p["value"] for p in entrada["metadata"]}
    assert meta[service.K_ORIGEN] == "whatsapp"
    assert meta[service.K_LINK] == carrito.link_id


def test_el_enlace_queda_en_la_metadata_para_poder_resolverlo(monkeypatch):
    """Sin esta clave el carrito existiría pero sería irrecuperable."""
    capturas = []
    monkeypatch.setattr(service, "gql", _router(capturas=capturas))
    carrito = service.crear([Linea(VAR, 1)])
    meta = {p["key"]: p["value"] for p in capturas[0]["metadata"]}
    assert meta[service.K_LINK] == carrito.link_id


def test_carrito_vacio_se_rechaza(monkeypatch):
    monkeypatch.setattr(service, "gql", _router())
    with pytest.raises(CarritoError, match="sin líneas"):
        service.crear([])


def test_error_de_saleor_al_crear_no_pasa_inadvertido(monkeypatch):
    monkeypatch.setattr(service, "gql", _router(
        errores=[{"field": "lines", "message": "sin stock", "code": "INSUFFICIENT_STOCK"}]))
    with pytest.raises(CarritoError, match="sin stock"):
        service.crear([Linea(VAR, 999)])


def test_metadata_extra_se_agrega(monkeypatch):
    """Permite colgar la identidad de la empresa al armar el carrito."""
    capturas = []
    monkeypatch.setattr(service, "gql", _router(capturas=capturas))
    service.crear([Linea(VAR, 1)], extra_metadata={"ventu.b2b.rut": "76543210-3"})
    meta = {p["key"]: p["value"] for p in capturas[0]["metadata"]}
    assert meta["ventu.b2b.rut"] == "76543210-3"


# ───────────────────────── resolución ─────────────────────────

def test_resuelve_el_carrito_vigente(monkeypatch):
    nodo = {"id": "Q2hlY2tvdXQ6MQ==", "token": "tok-1",
            "channel": {"slug": "b2b-cl"}, "lines": []}
    monkeypatch.setattr(service, "gql", _router(encontrado=nodo))
    assert service.resolver("a" * 22)["id"] == "Q2hlY2tvdXQ6MQ=="


def test_enlace_sin_carrito_devuelve_none(monkeypatch):
    monkeypatch.setattr(service, "gql", _router())
    assert service.resolver("a" * 22) is None


def test_enlace_manipulado_no_llega_a_saleor(monkeypatch):
    """Se valida la forma antes de consultar: una URL inventada no debe
    convertirse en tráfico contra la API."""
    def explota(*a, **kw):
        raise AssertionError("no debió consultarse Saleor")

    monkeypatch.setattr(service, "gql", explota)
    with pytest.raises(Exception):
        service.resolver("../../etc/passwd")


# ───────────────────────── rehacer (canal inmutable) ─────────────────────────

def test_rehacer_conserva_el_enlace(monkeypatch):
    """El canal de un checkout es inmutable en Saleor, así que cambiar de canal
    obliga a crear otro. Reusar el enlace es lo que evita invalidar el que el
    cliente ya tiene en su teléfono."""
    capturas = []
    monkeypatch.setattr(service, "gql", _router(capturas=capturas))
    lid = "b" * 22
    carrito = service.rehacer(lid, [Linea(VAR, 5)], canal="b2b-cl")

    assert carrito.link_id == lid
    meta = {p["key"]: p["value"] for p in capturas[0]["metadata"]}
    assert meta[service.K_LINK] == lid
    assert capturas[0]["channel"] == "b2b-cl"


def test_rehacer_preserva_el_precio_negociado(monkeypatch):
    """Rehacer no debe perder la condición acordada con el cliente."""
    capturas = []
    monkeypatch.setattr(service, "gql", _router(capturas=capturas))
    service.rehacer("c" * 22, [Linea(VAR, 10, precio_unitario=900.0)], canal="b2b-cl")
    assert capturas[0]["lines"][0]["price"] == 900.0


def test_rehacer_con_enlace_invalido_falla(monkeypatch):
    monkeypatch.setattr(service, "gql", _router())
    with pytest.raises(Exception):
        service.rehacer("corto", [Linea(VAR, 1)], canal="b2b-cl")


# ───────────────────────── adjuntar cliente ─────────────────────────

def test_adjunta_cliente_al_identificarse(monkeypatch):
    monkeypatch.setattr(service, "gql", _router())
    service.adjuntar_cliente("Q2hlY2tvdXQ6MQ==", "VXNlcjo1")  # no lanza


def test_error_al_adjuntar_no_pasa_inadvertido(monkeypatch):
    monkeypatch.setattr(service, "gql", _router(
        errores=[{"field": "customerId", "message": "no existe", "code": "NOT_FOUND"}]))
    with pytest.raises(CarritoError, match="no existe"):
        service.adjuntar_cliente("Q2hlY2tvdXQ6MQ==", "VXNlcjo5")


# ───────────────────────── URL ─────────────────────────

def test_url_del_carrito(monkeypatch):
    monkeypatch.setattr(service.config, "STOREFRONT_URL", "https://ventu.cl")
    carrito = Carrito(link_id="d" * 22, checkout_id="x", token="t")
    assert carrito.url() == "https://ventu.cl/c/" + "d" * 22
