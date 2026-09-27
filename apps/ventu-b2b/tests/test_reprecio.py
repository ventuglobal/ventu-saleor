"""El carrito cobra el precio del tramo, no el de catálogo.

Mostrar «12 unidades a $9.130» en la ficha y cobrar $11.126 en el carrito es
peor que no mostrar la tabla.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from ventu_b2b import main
from ventu_b2b.cart import precios, reprecio
from ventu_b2b.cart.service import MOTIVO_NEGOCIADO, MOTIVO_TRAMO
from ventu_b2b.company.models import Company
from ventu_b2b.saleor_client import SaleorTransportError

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


def _saleor(cantidad=12, tramos=TABLA, capturado=None, disponible=9999, lineas=None,
            usuario=USUARIO, canal="b2b-cl", canales_leidos=None, opciones=None):
    """Saleor falso: la consulta del carrito y la de la variante llegan por el
    mismo `gql`, así que se distinguen por el documento."""
    def gql(query, variables=None, **kw):
        if "checkout(" in query:
            return {"data": {"checkout": {
                "id": CHECKOUT,
                "channel": {"slug": canal},
                "user": {"id": usuario} if usuario else None,
                "lines": lineas if lineas is not None else [
                    {"id": "TGluZTox", "quantity": cantidad, "variant": {"id": VAR}}],
            }}}
        if "checkoutLinesUpdate" in query:
            if capturado is not None:
                capturado.append(variables)
            if opciones is not None:
                opciones.append(kw)
            return {"data": {"checkoutLinesUpdate": {
                "checkout": {"id": CHECKOUT, "totalPrice": {"gross": {"amount": 109560.0}}},
                "errors": []}}}
        if canales_leidos is not None:
            canales_leidos.append((variables or {}).get("channel"))
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
    assert capturado[0]["lines"][0]["priceOverrideReason"] == MOTIVO_TRAMO


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


def test_el_reprecio_no_toca_la_cantidad(monkeypatch):
    """Enviar `quantity` hace que Saleor revalide stock y disponibilidad: un
    producto agotado haría fallar el reprecio entero con un 502 que ningún
    reintento arregla, en vez de llegar al 409 legible del pedido."""
    capturado = []
    lineas = [
        {"id": "TGluZTox", "quantity": 12, "variant": {"id": VAR}},
        {"id": "tramo", "quantity": 12, "variant": {"id": VAR},
         "priceOverrideReason": MOTIVO_TRAMO},
    ]
    monkeypatch.setattr(reprecio, "gql", _saleor(capturado=capturado, lineas=lineas))
    monkeypatch.setattr(precios, "gql", _saleor())

    reprecio.aplicar(CHECKOUT)
    for linea in capturado[0]["lines"]:
        assert "quantity" not in linea


def test_el_stock_manda_tambien_aqui(monkeypatch):
    """Con 5 disponibles ni el tramo de 12 ni el de 6 son alcanzables: rige el
    base. Cobrar un tramo que la bodega no puede cumplir sería prometer algo que
    el despacho va a desmentir."""
    capturado = []
    monkeypatch.setattr(reprecio, "gql", _saleor(capturado=capturado))
    monkeypatch.setattr(precios, "gql", _saleor(disponible=5))

    reprecio.aplicar(CHECKOUT)
    assert capturado[0]["lines"][0]["price"] == 11130.0


def test_linea_que_ya_no_alcanza_tramo_vuelve_al_precio_de_lista(monkeypatch):
    """Si la escalera desaparece (o el stock baja del mínimo), el precio por
    volumen que se fijó antes ya no corresponde: se borra, no se conserva."""
    capturado = []
    lineas = [{"id": "TGluZTox", "quantity": 12, "variant": {"id": VAR},
               "priceOverrideReason": MOTIVO_TRAMO}]
    monkeypatch.setattr(reprecio, "gql", _saleor(capturado=capturado, lineas=lineas))
    monkeypatch.setattr(precios, "gql", _saleor(tramos=""))

    r = reprecio.aplicar(CHECKOUT)

    linea = capturado[0]["lines"][0]
    assert linea["price"] is None
    assert "priceOverrideReason" not in linea, "Saleor no admite motivo sin precio"
    assert r["restablecidas"] == 1


def test_precio_negociado_no_se_recalcula(monkeypatch):
    """El precio que fijó el ejecutivo es un acuerdo, no un tramo."""
    def explota(*a, **kw):
        raise AssertionError("no debió tocarse la línea negociada")

    lineas = [{"id": "TGluZTox", "quantity": 12, "variant": {"id": VAR},
               "priceOverrideReason": MOTIVO_NEGOCIADO}]
    base = _saleor(lineas=lineas)

    def gql(query, variables=None, **kw):
        if "checkout(" in query:
            return base(query, variables, **kw)
        return explota()

    monkeypatch.setattr(reprecio, "gql", gql)
    monkeypatch.setattr(precios, "gql", explota)
    assert reprecio.aplicar(CHECKOUT)["aplicado"] is False


@pytest.mark.parametrize("motivo", [
    "Precio por tramo de cantidad (B2B)",  # el de una versión anterior de la app
    "Ajuste comercial acordado por teléfono",
])
@pytest.mark.parametrize("tramos", [TABLA, ""])
def test_un_motivo_que_no_es_el_del_tramo_tampoco_se_toca(monkeypatch, motivo, tramos):
    """Solo el motivo del tramo es nuestro. Cualquier otro lo fijó alguien con
    intención: ni se recalcula si hay tramo ni se borra si no lo hay."""
    def explota(*a, **kw):
        raise AssertionError("no debió tocarse una línea con otro motivo")

    lineas = [{"id": "TGluZTox", "quantity": 12, "variant": {"id": VAR},
               "priceOverrideReason": motivo}]
    base = _saleor(lineas=lineas, tramos=tramos)

    def gql(query, variables=None, **kw):
        if "checkout(" in query:
            return base(query, variables, **kw)
        return explota()

    monkeypatch.setattr(reprecio, "gql", gql)
    monkeypatch.setattr(precios, "gql", explota)
    r = reprecio.aplicar(CHECKOUT)
    assert r["aplicado"] is False
    assert r["lineas"] == 0


def test_carrito_mixto_solo_restablece_los_tramos_que_ya_no_aplican(monkeypatch):
    """Sin escalera: el tramo vencido vuelve a lista, el negociado se queda
    como está y la línea a precio de lista no se marca como fijada."""
    capturado = []
    lineas = [
        {"id": "negociada", "quantity": 12, "variant": {"id": VAR},
         "priceOverrideReason": MOTIVO_NEGOCIADO},
        {"id": "tramo", "quantity": 12, "variant": {"id": VAR},
         "priceOverrideReason": MOTIVO_TRAMO},
        {"id": "lista", "quantity": 12, "variant": {"id": VAR},
         "priceOverrideReason": None},
    ]
    monkeypatch.setattr(reprecio, "gql", _saleor(capturado=capturado, lineas=lineas))
    monkeypatch.setattr(precios, "gql", _saleor(tramos=""))

    r = reprecio.aplicar(CHECKOUT)

    assert capturado[0]["lines"] == [{"lineId": "tramo", "price": None}]
    assert r["restablecidas"] == 1
    assert r["lineas"] == 0


def test_carrito_mixto_con_tramo_fija_el_tramo_y_respeta_lo_negociado(monkeypatch):
    capturado = []
    lineas = [
        {"id": "negociada", "quantity": 12, "variant": {"id": VAR},
         "priceOverrideReason": MOTIVO_NEGOCIADO},
        {"id": "lista", "quantity": 12, "variant": {"id": VAR},
         "priceOverrideReason": None},
    ]
    monkeypatch.setattr(reprecio, "gql", _saleor(capturado=capturado, lineas=lineas))
    monkeypatch.setattr(precios, "gql", _saleor())

    reprecio.aplicar(CHECKOUT)

    tocadas = capturado[0]["lines"]
    assert [l["lineId"] for l in tocadas] == ["lista"]
    assert tocadas[0]["price"] == 9130.0
    assert tocadas[0]["priceOverrideReason"] == MOTIVO_TRAMO


def test_escalera_invalida_restablece_la_linea_y_lo_informa(monkeypatch):
    capturado = []
    lineas = [{"id": "TGluZTox", "quantity": 12, "variant": {"id": VAR},
               "priceOverrideReason": MOTIVO_TRAMO}]
    monkeypatch.setattr(reprecio, "gql", _saleor(capturado=capturado, lineas=lineas))
    monkeypatch.setattr(precios, "gql", _saleor(tramos="esto no es una escalera"))

    r = reprecio.aplicar(CHECKOUT)
    assert capturado[0]["lines"][0]["price"] is None
    assert r["fallidas"] == [VAR]


def test_se_usa_el_canal_del_carrito(monkeypatch):
    """El precio sale del canal del checkout, no del nivel de la empresa:
    mezclar la escalera de un canal con la lista de otro cobra un precio que
    ninguno publica."""
    leidos = []
    monkeypatch.setattr(reprecio, "gql", _saleor(canal="b2b-cl"))
    monkeypatch.setattr(precios, "gql", _saleor(canales_leidos=leidos))

    reprecio.aplicar(CHECKOUT)
    assert leidos == ["b2b-cl"]


def test_la_actualizacion_de_lineas_no_se_reintenta(monkeypatch):
    opciones = []
    monkeypatch.setattr(reprecio, "gql", _saleor(opciones=opciones))
    monkeypatch.setattr(precios, "gql", _saleor())

    reprecio.aplicar(CHECKOUT)
    assert opciones == [{"reintentar": False}]


def test_un_fallo_al_leer_la_variante_se_propaga(monkeypatch):
    """Antes se tragaba y la línea quedaba con el precio anterior; ahora el
    pedido puede negarse a cerrar con un precio que no se pudo confirmar."""
    def explota(*a, **kw):
        raise SaleorTransportError("Saleor no responde")

    monkeypatch.setattr(reprecio, "gql", _saleor())
    monkeypatch.setattr(precios, "gql", explota)
    with pytest.raises(SaleorTransportError):
        reprecio.aplicar(CHECKOUT)


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


def test_endpoint_usa_el_canal_del_carrito_y_no_el_nivel_de_la_empresa(monkeypatch, cliente):
    """La empresa está en retail-cl pero el carrito vive en b2b-cl: manda el
    carrito."""
    leidos = []
    monkeypatch.setattr(main.company_svc, "obtener_de_usuario",
                        lambda uid: _company(nivel_precio="retail-cl"))
    monkeypatch.setattr(reprecio, "gql", _saleor(canal="b2b-cl"))
    monkeypatch.setattr(precios, "gql", _saleor(canales_leidos=leidos))

    r = cliente.post("/cart/reprecio", json={"checkout_id": CHECKOUT, "user_id": USUARIO})
    assert r.status_code == 200
    assert leidos == ["b2b-cl"]


def test_endpoint_no_toca_lo_negociado_y_restablece_el_tramo_vencido(monkeypatch, cliente):
    capturado = []
    lineas = [
        {"id": "negociada", "quantity": 3, "variant": {"id": VAR},
         "priceOverrideReason": MOTIVO_NEGOCIADO},
        {"id": "tramo", "quantity": 3, "variant": {"id": VAR},
         "priceOverrideReason": MOTIVO_TRAMO},
    ]
    monkeypatch.setattr(main.company_svc, "obtener_de_usuario", lambda uid: _company())
    monkeypatch.setattr(reprecio, "gql", _saleor(capturado=capturado, lineas=lineas))
    monkeypatch.setattr(precios, "gql", _saleor(tramos=""))

    r = cliente.post("/cart/reprecio", json={"checkout_id": CHECKOUT, "user_id": USUARIO})
    assert r.status_code == 200
    assert capturado[0]["lines"] == [{"lineId": "tramo", "price": None}]


def test_carrito_de_un_canal_no_b2b_no_se_reprecifica(monkeypatch, cliente):
    """El canal sale del carrito en Saleor y no de quien llama: un carrito
    retail se paga por la pasarela retail, sin pasar por /pedido, así que un
    precio por volumen fijado ahí se cobraría tal cual."""
    def explota(*a, **kw):
        raise AssertionError("no debió leerse ninguna variante")

    capturado = []
    monkeypatch.setattr(main.company_svc, "obtener_de_usuario", lambda uid: _company())
    monkeypatch.setattr(reprecio, "gql", _saleor(canal="retail-cl", capturado=capturado))
    monkeypatch.setattr(precios, "gql", explota)

    r = cliente.post("/cart/reprecio", json={"checkout_id": CHECKOUT, "user_id": USUARIO})
    assert r.status_code == 200
    assert r.json() == {"aplicado": False, "motivo": "canal_no_b2b"}
    assert capturado == []


@pytest.mark.parametrize("dueno", ["VXNlcjo5OTk=", None])
def test_carrito_ajeno_no_se_reprecifica(monkeypatch, cliente, dueno):
    """Conocer un checkout_id no basta para tocarlo."""
    def explota(*a, **kw):
        raise AssertionError("no debió leerse ninguna variante")

    monkeypatch.setattr(main.company_svc, "obtener_de_usuario", lambda uid: _company())
    monkeypatch.setattr(reprecio, "gql", _saleor(usuario=dueno))
    monkeypatch.setattr(precios, "gql", explota)

    r = cliente.post("/cart/reprecio", json={"checkout_id": CHECKOUT, "user_id": USUARIO})
    assert r.status_code == 403


def test_endpoint_carrito_inexistente(monkeypatch, cliente):
    monkeypatch.setattr(main.company_svc, "obtener_de_usuario", lambda uid: _company())
    monkeypatch.setattr(reprecio, "gql", lambda *a, **kw: {"data": {"checkout": None}})
    r = cliente.post("/cart/reprecio", json={"checkout_id": CHECKOUT, "user_id": USUARIO})
    assert r.status_code == 404


def test_sin_empresa_no_se_aplican_tramos(monkeypatch, cliente):
    """Los tramos son el precio de la empresa, no el de cualquiera que entre al
    canal."""
    monkeypatch.setattr(main.company_svc, "obtener_de_usuario", lambda uid: None)
    d = cliente.post("/cart/reprecio",
                     json={"checkout_id": CHECKOUT, "user_id": USUARIO}).json()
    assert d == {"aplicado": False, "motivo": "sin_empresa"}


def test_un_fallo_se_informa_al_storefront(monkeypatch, cliente):
    """Antes se respondía `aplicado: false` con 200 y el storefront mostraba un
    total que quizás no era el que se cobraría. Ahora el fallo se ve; el pedido
    reprecifica de nuevo antes de crearse."""
    def explota(*a, **kw):
        raise SaleorTransportError("Saleor no responde")

    monkeypatch.setattr(main.company_svc, "obtener_de_usuario", lambda uid: _company())
    monkeypatch.setattr(reprecio, "gql", explota)

    r = cliente.post("/cart/reprecio", json={"checkout_id": CHECKOUT, "user_id": USUARIO})
    assert r.status_code == 502


def test_error_de_saleor_al_actualizar_lineas_es_502(monkeypatch, cliente):
    base = _saleor()

    def gql(query, variables=None, **kw):
        if "checkoutLinesUpdate" in query:
            return {"data": {"checkoutLinesUpdate": {
                "checkout": None,
                "errors": [{"field": "lines", "message": "nope", "code": "INVALID"}]}}}
        return base(query, variables, **kw)

    monkeypatch.setattr(main.company_svc, "obtener_de_usuario", lambda uid: _company())
    monkeypatch.setattr(reprecio, "gql", gql)
    monkeypatch.setattr(precios, "gql", _saleor())

    r = cliente.post("/cart/reprecio", json={"checkout_id": CHECKOUT, "user_id": USUARIO})
    assert r.status_code == 502
