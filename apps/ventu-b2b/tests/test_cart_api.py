"""Carritos armados por el staff para enviar por WhatsApp."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from ventu_b2b import config, main
from ventu_b2b.cart import link as link_mod
from ventu_b2b.cart import service as cart
from ventu_b2b.saleor_client import SaleorRespuestaError, SaleorTransportError

VAR = "UHJvZHVjdFZhcmlhbnQ6MQ=="
USUARIO = "VXNlcjo1"
ENLACE = link_mod.generar()
BAJO = {"costo": 9000, "precio": 9100, "markup_real": 0.0111,
        "markup_minimo": 0.3, "comision_pct": 0.0}


@pytest.fixture
def cliente():
    return TestClient(main.app)


@pytest.fixture
def creados(monkeypatch):
    """Sustituye la creación en Saleor y devuelve las líneas que recibió."""
    lineas = []

    def crear(ls, **kw):
        lineas.extend(ls)
        return cart.Carrito(link_id=ENLACE, checkout_id="Q2hlY2tvdXQ6MQ==",
                            token="t")
    monkeypatch.setattr(main.cart, "crear", crear)
    monkeypatch.setattr(main.cart, "adjuntar_cliente", lambda cid, uid: None)
    monkeypatch.setattr(main.company_svc, "obtener_de_usuario", lambda uid: None)
    return lineas


def _negociado(precio=9100, **kw):
    return {"lineas": [{"variant_id": VAR, "cantidad": 10, "precio_unitario": precio}], **kw}


# ───────────────── margen mínimo ─────────────────

def test_precio_bajo_el_margen_se_rechaza_sin_confirmacion(monkeypatch, cliente, creados):
    monkeypatch.setattr(config, "MARKUP_MINIMO", 0.3)
    monkeypatch.setattr(main.precios_mod, "revisar_negociado", lambda *a, **kw: dict(BAJO))

    r = cliente.post("/cart", json=_negociado())
    assert r.status_code == 422
    detalle = r.json()["detail"]
    assert detalle["avisos_margen"][0]["variant_id"] == VAR
    assert "forzar" in detalle["mensaje"]
    assert creados == [], "no debió crearse el carrito"


def test_con_forzar_se_crea_y_se_informa(monkeypatch, cliente, creados):
    monkeypatch.setattr(config, "MARKUP_MINIMO", 0.3)
    monkeypatch.setattr(main.precios_mod, "revisar_negociado", lambda *a, **kw: dict(BAJO))

    r = cliente.post("/cart", json=_negociado(forzar=True))
    assert r.status_code == 200
    assert r.json()["avisos_margen"][0]["markup_real"] == BAJO["markup_real"]
    assert creados[0].precio_unitario == 9100


def test_sin_margen_minimo_no_se_revisa(monkeypatch, cliente, creados):
    """`revisar_negociado` no mira el costo sin piso configurado."""
    def no_debe_leer_costo(*a, **kw):
        raise AssertionError("sin piso no hay nada que leer")

    monkeypatch.setattr(main.precios_mod, "costo_de", no_debe_leer_costo)
    r = cliente.post("/cart", json=_negociado())
    assert r.status_code == 200
    assert "avisos_margen" not in r.json()


def test_si_no_se_puede_leer_el_costo_el_carrito_no_se_crea(monkeypatch, cliente, creados):
    """Antes el error se tragaba y el carrito salía sin revisión de margen."""
    def caido(*a, **kw):
        raise SaleorTransportError("caído")

    monkeypatch.setattr(config, "MARKUP_MINIMO", 0.3)
    monkeypatch.setattr(main.precios_mod, "revisar_negociado", caido)
    assert cliente.post("/cart", json=_negociado()).status_code == 502
    assert creados == []


# ───────────────── motivo de cada línea ─────────────────

def test_las_lineas_por_tramo_quedan_marcadas_como_recalculables(monkeypatch, cliente, creados):
    monkeypatch.setattr(main.precios_mod, "resolver_precio", lambda *a, **kw: 7900.0)
    r = cliente.post("/cart", json={"lineas": [{"variant_id": VAR, "cantidad": 12}]})
    assert r.status_code == 200
    assert creados[0].motivo == cart.MOTIVO_TRAMO
    assert creados[0].to_input()["priceOverrideReason"] == cart.MOTIVO_TRAMO


def test_las_lineas_negociadas_quedan_marcadas_como_negociadas(cliente, creados):
    cliente.post("/cart", json=_negociado())
    # Explícito en la línea, no solo por omisión de `Linea.to_input`: la marca
    # es lo que impide que el reprecio pise el precio acordado.
    assert creados[0].motivo == cart.MOTIVO_NEGOCIADO
    motivo = creados[0].to_input()["priceOverrideReason"]
    # Con la cantidad acordada: el precio vale para esa cantidad y no otra.
    assert motivo == cart.motivo_negociado(creados[0].cantidad)
    assert cart.cantidad_negociada(motivo) == creados[0].cantidad
    assert cart.MOTIVO_NEGOCIADO != cart.MOTIVO_TRAMO


# ───────────────── asociación al cliente ─────────────────

@pytest.mark.parametrize("falla", [cart.CarritoError("sin permiso"),
                                   SaleorRespuestaError("IMPERSONATE_USER")])
def test_si_no_se_puede_asociar_al_cliente_igual_se_entrega_el_enlace(
        monkeypatch, cliente, creados, falla):
    """El carrito ya existe: fallar aquí perdería el enlace y dejaría un
    checkout huérfano."""
    def adjuntar(cid, uid):
        raise falla

    monkeypatch.setattr(main.cart, "adjuntar_cliente", adjuntar)
    r = cliente.post("/cart", json=_negociado(user_id=USUARIO))
    assert r.status_code == 200
    d = r.json()
    assert d["link_id"] == ENLACE
    assert "no quedó asociado" in d["aviso"]


def test_sin_fallo_no_hay_aviso(cliente, creados):
    d = cliente.post("/cart", json=_negociado(user_id=USUARIO)).json()
    assert "aviso" not in d


def test_carrito_sin_lineas_es_422(cliente, creados):
    assert cliente.post("/cart", json={"lineas": []}).status_code == 422
