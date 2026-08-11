"""El carrito cobra el precio del tramo, no el de catálogo.

Mostrar «12 unidades a $9.130» en la ficha y cobrar $11.126 en el carrito es
peor que no mostrar la tabla.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from ventu_b2b import main
from ventu_b2b.cart import precios, reprecio
from ventu_b2b.company.models import Company

CHECKOUT = "Q2hlY2tvdXQ6MQ=="
VAR = "UHJvZHVjdFZhcmlhbnQ6NDE5"
USUARIO = "VXNlcjo1"
TABLA = "1=11130,6=10020,12=9130,24=8350"


@pytest.fixture
def cliente():
    return TestClient(main.app)


def _company(**kw):
    base = dict(rut="76.543.210-3", razon_social="Comercial Ventu SpA",
                nivel_precio="b2b-cl")
    base.update(kw)
    return Company(**base)


def _saleor(cantidad=12, tramos=TABLA, capturado=None, disponible=9999, lineas=None):
    """Saleor falso: la consulta del carrito y la de la variante llegan por el
    mismo `gql`, así que se distinguen por el documento."""
    def gql(query, variables=None, **kw):
        if "checkout(" in query:
            return {"data": {"checkout": {
                "id": CHECKOUT,
                "channel": {"slug": "b2b-cl"},
                "lines": lineas if lineas is not None else [
                    {"id": "TGluZTox", "quantity": cantidad, "variant": {"id": VAR}}],
            }}}
        if "checkoutLinesUpdate" in query:
            if capturado is not None:
                capturado.append(variables)
            return {"data": {"checkoutLinesUpdate": {
                "checkout": {"id": CHECKOUT, "totalPrice": {"gross": {"amount": 109560.0}}},
                "errors": []}}}
        return {"data": {"productVariant": {
            "id": VAR,
            "quantityAvailable": disponible,
            "pricing": {"price": {"gross": {"amount": 11126.0}}},
            "privateMetadata": [],
            "product": {"privateMetadata": (
                [{"key": precios.K_TRAMOS, "value": tramos}] if tramos else [])},
        }}}
    return gql


# ───────────────── el precio que se fija ─────────────────

def test_la_cantidad_del_carrito_fija_el_precio(monkeypatch):
    capturado = []
    monkeypatch.setattr(reprecio, "gql", _saleor(capturado=capturado))
    monkeypatch.setattr(precios, "gql", _saleor())

    r = reprecio.aplicar(CHECKOUT)

    assert r["aplicado"] is True
    linea = capturado[0]["lines"][0]
    assert linea["price"] == 9130.0, "12 unidades caen en el tramo de 12"
    assert linea["lineId"] == "TGluZTox"


def test_queda_registrado_el_motivo(monkeypatch):
    """El precio distinto del de lista viaja a la orden con su razón."""
    capturado = []
    monkeypatch.setattr(reprecio, "gql", _saleor(capturado=capturado))
    monkeypatch.setattr(precios, "gql", _saleor())

    reprecio.aplicar(CHECKOUT)
    assert capturado[0]["lines"][0]["priceOverrideReason"] == reprecio.MOTIVO


def test_una_unidad_paga_el_tramo_base(monkeypatch):
    capturado = []
    monkeypatch.setattr(reprecio, "gql", _saleor(cantidad=1, capturado=capturado))
    monkeypatch.setattr(precios, "gql", _saleor(cantidad=1))

    reprecio.aplicar(CHECKOUT)
    assert capturado[0]["lines"][0]["price"] == 11130.0


def test_producto_sin_tramos_no_se_toca(monkeypatch):
    """Sobreescribir con el precio de catálogo marcaría la línea como negociada
    sin que nadie haya negociado nada, y esa marca llega a la orden."""
    def explota(*a, **kw):
        raise AssertionError("no debió actualizarse ninguna línea")

    monkeypatch.setattr(precios, "gql", _saleor(tramos=""))

    def gql(query, variables=None, **kw):
        if "checkout(" in query:
            return _saleor(tramos="")(query, variables, **kw)
        return explota()

    monkeypatch.setattr(reprecio, "gql", gql)
    assert reprecio.aplicar(CHECKOUT) == {"aplicado": False, "lineas": 0}


def test_se_recalcula_el_carrito_entero(monkeypatch):
    """Un carrito a medio reprecificar cobra mal sin que nada falle."""
    capturado = []
    lineas = [
        {"id": "TGluZTox", "quantity": 12, "variant": {"id": VAR}},
        {"id": "TGluZToy", "quantity": 6, "variant": {"id": VAR}},
    ]
    monkeypatch.setattr(reprecio, "gql", _saleor(capturado=capturado, lineas=lineas))
    monkeypatch.setattr(precios, "gql", _saleor())

    reprecio.aplicar(CHECKOUT)
    precios_fijados = [l["price"] for l in capturado[0]["lines"]]
    assert precios_fijados == [9130.0, 10020.0]


def test_el_stock_manda_tambien_aqui(monkeypatch):
    """Con 5 disponibles ni el tramo de 12 ni el de 6 son alcanzables: rige el
    base. Cobrar un tramo que la bodega no puede cumplir sería prometer algo que
    el despacho va a desmentir."""
    capturado = []
    monkeypatch.setattr(reprecio, "gql", _saleor(capturado=capturado))
    monkeypatch.setattr(precios, "gql", _saleor(disponible=5))

    reprecio.aplicar(CHECKOUT)
    assert capturado[0]["lines"][0]["price"] == 11130.0


def test_carrito_inexistente(monkeypatch):
    monkeypatch.setattr(reprecio, "gql", lambda *a, **kw: {"data": {"checkout": None}})
    with pytest.raises(reprecio.ReprecioError):
        reprecio.aplicar(CHECKOUT)


# ───────────────── el endpoint ─────────────────

def test_endpoint_reprecifica(monkeypatch, cliente):
    monkeypatch.setattr(main.company_svc, "obtener_de_usuario", lambda uid: _company())
    monkeypatch.setattr(reprecio, "gql", _saleor())
    monkeypatch.setattr(precios, "gql", _saleor())

    r = cliente.post("/cart/reprecio", json={"checkout_id": CHECKOUT, "user_id": USUARIO})
    assert r.status_code == 200
    assert r.json()["aplicado"] is True


def test_sin_empresa_no_se_aplican_tramos(monkeypatch, cliente):
    """Los tramos son el precio de la empresa, no el de cualquiera que entre al
    canal."""
    monkeypatch.setattr(main.company_svc, "obtener_de_usuario", lambda uid: None)
    d = cliente.post("/cart/reprecio",
                     json={"checkout_id": CHECKOUT, "user_id": USUARIO}).json()
    assert d == {"aplicado": False, "motivo": "sin_empresa"}


def test_un_fallo_no_rompe_el_carrito(monkeypatch, cliente):
    """Sin reprecio se cobra el de catálogo: más caro, pero no es un cobro
    indebido. Dejar el carrito inutilizable sí sería peor."""
    def explota(*a, **kw):
        raise RuntimeError("Saleor no responde")

    monkeypatch.setattr(main.company_svc, "obtener_de_usuario", lambda uid: _company())
    monkeypatch.setattr(reprecio, "gql", explota)

    r = cliente.post("/cart/reprecio", json={"checkout_id": CHECKOUT, "user_id": USUARIO})
    assert r.status_code == 200
    assert r.json()["aplicado"] is False
