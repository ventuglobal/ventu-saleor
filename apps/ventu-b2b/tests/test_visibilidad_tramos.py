"""La tabla de tramos solo es visible para empresas registradas.

Es información comercial reservada: revela la política de descuentos por volumen
y, con ella, el margen.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from ventu_b2b import main
from ventu_b2b.cart import precios
from ventu_b2b.company.models import Company

VAR = "UHJvZHVjdFZhcmlhbnQ6MQ=="
TABLA = "1=13240,4=8900,6=8400"


@pytest.fixture
def cliente():
    return TestClient(main.app)


def _company(**kw):
    base = dict(rut="76.543.210-3", razon_social="Comercial Ventu SpA",
                nivel_precio="b2b-cl")
    base.update(kw)
    return Company(**base)


def _router(tramos=TABLA, disponible=9999, neto=13240.0, bruto=13240.0,
            muestra_bruto=None):
    """Saleor falso. Por omisión, neto = bruto; con IVA, el channel de §d
    (precios ingresados sin IVA). `muestra_bruto` es `displayGrossPrices`:
    `None` lo omite, como una respuesta sin el dato."""
    impuestos = {"pricesEnteredWithTax": False}
    if muestra_bruto is not None:
        impuestos["displayGrossPrices"] = muestra_bruto

    def gql(query, variables=None, **kw):
        return {"data": {
            "productVariant": {
                "id": VAR,
                "quantityAvailable": disponible,
                "pricing": {"price": {"net": {"amount": neto}, "gross": {"amount": bruto}}},
                "privateMetadata": [],
                "product": {"privateMetadata": (
                    [{"key": precios.K_TRAMOS, "value": tramos}] if tramos else [])},
            },
            "channel": {"taxConfiguration": impuestos},
        }}
    return gql


# ───────────────── quién ve la tabla ─────────────────

def test_empresa_registrada_ve_la_tabla(monkeypatch, cliente):
    monkeypatch.setattr(main.company_svc, "obtener_de_usuario", lambda uid: _company())
    monkeypatch.setattr(precios, "gql", _router())

    r = cliente.get(f"/tramos/{VAR}", params={"user_id": "VXNlcjo1"})
    assert r.status_code == 200
    d = r.json()
    assert d["visible"] is True
    assert d["tramos"] == [
        {"desde": 1, "precio_unitario": 13240.0},
        {"desde": 4, "precio_unitario": 8900.0},
        {"desde": 6, "precio_unitario": 8400.0},
    ]


def test_usuario_sin_empresa_no_ve_nada(monkeypatch, cliente):
    """Un cliente retail autenticado no debe ver la tabla mayorista."""
    monkeypatch.setattr(main.company_svc, "obtener_de_usuario", lambda uid: None)
    monkeypatch.setattr(precios, "gql", _router())

    d = cliente.get(f"/tramos/{VAR}", params={"user_id": "VXNlcjo5"}).json()
    assert d["visible"] is False
    assert d["motivo"] == "sin_empresa"
    assert "tramos" not in d, "no debe filtrarse ninguna cifra"


def test_anonimo_no_ve_nada(monkeypatch, cliente):
    monkeypatch.setattr(precios, "gql", _router())
    d = cliente.get(f"/tramos/{VAR}").json()
    assert d["visible"] is False
    assert d["motivo"] == "sin_identificar"
    assert "tramos" not in d


def test_no_se_responde_403(monkeypatch, cliente):
    """Que un retail sepa que *existe* una tabla que no puede ver no aporta nada
    y sí invita a buscarla."""
    monkeypatch.setattr(main.company_svc, "obtener_de_usuario", lambda uid: None)
    r = cliente.get(f"/tramos/{VAR}", params={"user_id": "VXNlcjo5"})
    assert r.status_code == 200


# ───────────────── qué se entrega ─────────────────

def test_la_tabla_no_incluye_costo_ni_margen(monkeypatch, cliente):
    """Ni siquiera a una empresa registrada: el costo no sale de la app."""
    monkeypatch.setattr(main.company_svc, "obtener_de_usuario", lambda uid: _company())
    monkeypatch.setattr(precios, "gql", _router())

    crudo = cliente.get(f"/tramos/{VAR}", params={"user_id": "VXNlcjo1"}).text
    for prohibido in ("costo", "margen", "markup"):
        assert prohibido not in crudo.lower()


def test_empresa_en_revision_igual_ve_la_tabla(monkeypatch, cliente):
    """La revisión frena la compra, no la cotización: una empresa recién
    registrada ya es un cliente identificado, y ver el precio por volumen es
    justamente lo que la trae a pedir la aprobación."""
    monkeypatch.setattr(main.company_svc, "obtener_de_usuario",
                        lambda uid: _company(nivel_precio="retail-cl"))
    monkeypatch.setattr(precios, "gql", _router())
    d = cliente.get(f"/tramos/{VAR}",
                    params={"user_id": "VXNlcjo1", "canal": "b2b-cl"}).json()
    assert d["visible"] is True
    assert d["canal"] == "b2b-cl"


def test_usa_el_canal_de_la_empresa(monkeypatch, cliente):
    monkeypatch.setattr(main.company_svc, "obtener_de_usuario",
                        lambda uid: _company(nivel_precio="b2b-cl"))
    monkeypatch.setattr(precios, "gql", _router())
    d = cliente.get(f"/tramos/{VAR}", params={"user_id": "VXNlcjo1"}).json()
    assert d["canal"] == "b2b-cl"


def test_el_canal_pedido_manda_sobre_el_de_la_empresa(monkeypatch, cliente):
    """La tabla tiene que coincidir con lo que cobra el reprecio, que usa el
    canal del carrito y no el nivel de la empresa."""
    leidos = []
    base = _router()

    def gql(query, variables=None, **kw):
        leidos.append((variables or {}).get("channel"))
        return base(query, variables, **kw)

    monkeypatch.setattr(main.company_svc, "obtener_de_usuario",
                        lambda uid: _company(nivel_precio="retail-cl"))
    monkeypatch.setattr(precios, "gql", gql)
    d = cliente.get(f"/tramos/{VAR}", params={"user_id": "VXNlcjo1", "canal": "b2b-cl"}).json()
    assert d["canal"] == "b2b-cl"
    assert leidos == ["b2b-cl"]


def test_fuera_de_un_canal_b2b_no_hay_tabla(monkeypatch, cliente):
    """El carrito retail cobra precio de lista: mostrarle la tabla a una
    empresa en retail-cl sería prometer un precio que no se cobra."""
    def explota(*a, **kw):
        raise AssertionError("no debió leerse la escalera")

    monkeypatch.setattr(main.company_svc, "obtener_de_usuario", lambda uid: _company())
    monkeypatch.setattr(precios, "gql", explota)
    d = cliente.get(f"/tramos/{VAR}",
                    params={"user_id": "VXNlcjo1", "canal": "retail-cl"}).json()
    assert d == {"visible": False, "motivo": "canal_no_b2b"}


def test_empresa_en_revision_sin_canal_cae_a_retail(monkeypatch, cliente):
    """Sin canal se usa el nivel de la empresa; una en revisión está en
    retail-cl y ahí no hay tabla."""
    monkeypatch.setattr(main.company_svc, "obtener_de_usuario",
                        lambda uid: _company(nivel_precio="retail-cl"))
    monkeypatch.setattr(precios, "gql", _router())
    d = cliente.get(f"/tramos/{VAR}", params={"user_id": "VXNlcjo1"}).json()
    assert d["motivo"] == "canal_no_b2b"


def test_en_b2b_la_tabla_se_muestra_neta_como_la_ficha(monkeypatch, cliente):
    """b2b-cl ingresa y muestra precios sin IVA (§d): la ficha pinta el neto y
    el IVA se desglosa en el carrito, así que la tabla también va neta."""
    monkeypatch.setattr(main.company_svc, "obtener_de_usuario", lambda uid: _company())
    monkeypatch.setattr(precios, "gql",
                        _router(tramos="1:1.0,10:0.9", neto=10000.0, bruto=11900.0,
                                muestra_bruto=False))
    d = cliente.get(f"/tramos/{VAR}", params={"user_id": "VXNlcjo1"}).json()
    assert d["tramos"] == [{"desde": 1, "precio_unitario": 10000.0},
                           {"desde": 10, "precio_unitario": 9000.0}]


@pytest.mark.parametrize("muestra_bruto", [True, None])
def test_si_el_channel_muestra_con_iva_la_tabla_va_con_iva(monkeypatch, cliente,
                                                           muestra_bruto):
    """Con `displayGrossPrices` activo —o sin el dato, que es lo que Saleor usa
    por omisión— la tabla se lee con IVA, como el precio de al lado."""
    monkeypatch.setattr(main.company_svc, "obtener_de_usuario", lambda uid: _company())
    monkeypatch.setattr(precios, "gql",
                        _router(tramos="1:1.0,10:0.9", neto=10000.0, bruto=11900.0,
                                muestra_bruto=muestra_bruto))
    d = cliente.get(f"/tramos/{VAR}", params={"user_id": "VXNlcjo1"}).json()
    assert d["tramos"] == [{"desde": 1, "precio_unitario": 11900.0},
                           {"desde": 10, "precio_unitario": 10710.0}]


# ───────────────── el stock condiciona la tabla ─────────────────

def test_sin_stock_no_se_publica_tabla(monkeypatch, cliente):
    monkeypatch.setattr(main.company_svc, "obtener_de_usuario", lambda uid: _company())
    monkeypatch.setattr(precios, "gql", _router(disponible=0))
    d = cliente.get(f"/tramos/{VAR}", params={"user_id": "VXNlcjo1"}).json()
    assert d["visible"] is False
    assert d["motivo"] == "sin_tramos"


def test_el_stock_recorta_los_tramos(monkeypatch, cliente):
    """Con 5 disponibles no se ofrece el tramo de 6."""
    monkeypatch.setattr(main.company_svc, "obtener_de_usuario", lambda uid: _company())
    monkeypatch.setattr(precios, "gql", _router(disponible=5))
    d = cliente.get(f"/tramos/{VAR}", params={"user_id": "VXNlcjo1"}).json()
    assert [t["desde"] for t in d["tramos"]] == [1, 4]


def test_producto_sin_tramos(monkeypatch, cliente):
    monkeypatch.setattr(main.company_svc, "obtener_de_usuario", lambda uid: _company())
    monkeypatch.setattr(precios, "gql", _router(tramos=""))
    d = cliente.get(f"/tramos/{VAR}", params={"user_id": "VXNlcjo1"}).json()
    assert d["visible"] is False
    assert d["motivo"] == "sin_tramos"


def test_fallo_al_leer_no_filtra_el_error(monkeypatch, cliente):
    """Un fallo interno no debe convertirse en información para quien pregunta."""
    def explota(*a, **kw):
        raise RuntimeError("token vencido contra Saleor")

    monkeypatch.setattr(main.company_svc, "obtener_de_usuario", lambda uid: _company())
    monkeypatch.setattr(precios, "gql", explota)
    d = cliente.get(f"/tramos/{VAR}", params={"user_id": "VXNlcjo1"}).json()
    assert d["visible"] is False
    assert d["motivo"] == "no_disponible"
    assert "token" not in str(d)
