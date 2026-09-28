"""El pedido de punta a punta: dueño, canal, reprecio, facturación y orden.

Un solo Saleor falso atiende a los tres módulos que lo llaman (lectura del
carrito y reprecio, precio de la variante, facturación y orden) y anota el
orden de las operaciones: la secuencia es parte del contrato.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from ventu_b2b import config, main
from ventu_b2b.cart import precios, reprecio
from ventu_b2b.cart import service as cart
from ventu_b2b.company.models import Company
from ventu_b2b.pedido import medios, service as pedido_svc
from ventu_b2b.saleor_client import SaleorTimeoutError, SaleorTransportError

CHECKOUT = "Q2hlY2tvdXQ6MQ=="
USUARIO = "VXNlcjo1"
VAR = "UHJvZHVjdFZhcmlhbnQ6MQ=="
TABLA = "1=13240,4=8900,6=8400,12=7900"

DESPACHO = {
    "firstName": "Ana", "lastName": "Pérez", "companyName": "Comercial Ventu SpA",
    "streetAddress1": "Av. Siempre Viva 742", "streetAddress2": "",
    "city": "SANTIAGO", "cityArea": "", "postalCode": "", "countryArea": "",
    "phone": "+56911112222", "country": {"code": "CL"},
}


@pytest.fixture
def cliente():
    return TestClient(main.app)


def _company(**kw):
    base = dict(rut="76.543.210-3", razon_social="Comercial Ventu SpA",
                nivel_precio="b2b-cl")
    base.update(kw)
    return Company(**base)


_IGUAL = object()


class _Saleor:
    """Saleor falso con registro de operaciones."""

    def __init__(self, *, dueno=USUARIO, canal="b2b-cl", facturacion=True,
                 despacho=True, falla_variante=None, errores_lineas=None,
                 falla_orden=None, errores_facturacion=None, errores_orden=None,
                 lineas=None, sin_orden=False, relectura=_IGUAL):
        self.ops = []
        self.variables = {}
        self.opciones = {}
        self.checkout = {
            "id": CHECKOUT,
            "channel": {"slug": canal},
            "user": {"id": dueno} if dueno else None,
            "billingAddress": {"id": "QWRkcmVzczox"} if facturacion else None,
            "shippingAddress": dict(DESPACHO) if despacho else None,
            "lines": lineas if lineas is not None else [
                {"id": "TGluZTox", "quantity": 12,
                 "priceOverrideReason": None, "variant": {"id": VAR}}],
        }
        self.falla_variante = falla_variante
        self.errores_lineas = errores_lineas or []
        self.falla_orden = falla_orden
        self.errores_facturacion = errores_facturacion or []
        self.errores_orden = errores_orden or []
        self.sin_orden = sin_orden
        # Lo que devuelve la segunda lectura del carrito, justo antes de la
        # orden. Por omisión, el mismo carrito.
        self.relectura = relectura

    def __call__(self, query, variables=None, **kw):
        if "orderCreateFromCheckout" in query:
            op = "orderCreateFromCheckout"
        elif "checkoutBillingAddressUpdate" in query:
            op = "checkoutBillingAddressUpdate"
        elif "checkoutLinesUpdate" in query:
            op = "checkoutLinesUpdate"
        elif "productVariant" in query:
            op = "productVariant"
        elif "checkout(" in query:
            op = "checkout"
        else:
            raise AssertionError(f"operación inesperada: {query[:60]}")
        self.ops.append(op)
        self.variables[op] = variables
        self.opciones[op] = kw

        if op == "checkout":
            if self.ops.count("checkout") > 1 and self.relectura is not _IGUAL:
                return {"data": {"checkout": self.relectura}}
            return {"data": {"checkout": self.checkout}}
        if op == "productVariant":
            if self.falla_variante:
                raise self.falla_variante
            return {"data": {"productVariant": {
                "id": VAR, "quantityAvailable": 9999,
                "pricing": {"price": {"gross": {"amount": 13240.0}}},
                "privateMetadata": [],
                "product": {"privateMetadata": [{"key": precios.K_TRAMOS, "value": TABLA}]},
            }}}
        if op == "checkoutLinesUpdate":
            return {"data": {"checkoutLinesUpdate": {
                "checkout": None if self.errores_lineas else
                {"id": CHECKOUT, "totalPrice": {"gross": {"amount": 94800.0}}},
                "errors": self.errores_lineas}}}
        if op == "checkoutBillingAddressUpdate":
            return {"data": {"checkoutBillingAddressUpdate": {
                "errors": self.errores_facturacion}}}
        if self.falla_orden:
            raise self.falla_orden
        if self.errores_orden or self.sin_orden:
            return {"data": {"orderCreateFromCheckout": {
                "order": None, "errors": self.errores_orden}}}
        return {"data": {"orderCreateFromCheckout": {
            "order": {"id": "T3JkZXI6MQ==", "number": 1042, "status": "UNFULFILLED",
                      "total": {"gross": {"amount": 94800.0, "currency": "CLP"}}},
            "errors": []}}}


@pytest.fixture
def saleor(monkeypatch):
    def instalar(**kw):
        falso = _Saleor(**kw)
        for modulo in (reprecio, precios, pedido_svc):
            monkeypatch.setattr(modulo, "gql", falso)
        return falso
    return instalar


def _pedir(cliente, metodo=medios.TRANSFERENCIA, user_id=USUARIO):
    return cliente.post("/pedido", json={"checkout_id": CHECKOUT, "user_id": user_id,
                                         "metodo_pago": metodo})


@pytest.fixture(autouse=True)
def _empresa(monkeypatch):
    monkeypatch.setattr(main.company_svc, "obtener_de_usuario", lambda uid: _company())


# ───────────────── camino feliz y secuencia ─────────────────

def test_secuencia_completa(saleor, cliente):
    """Primero se lee, después se reprecifica, se completa la facturación y
    recién al final se crea la orden."""
    falso = saleor(facturacion=False)
    r = _pedir(cliente)
    assert r.status_code == 200, r.text
    assert falso.ops == ["checkout", "productVariant", "checkoutLinesUpdate",
                         "checkoutBillingAddressUpdate", "checkout",
                         "orderCreateFromCheckout"]


def test_el_reprecio_fija_el_tramo_antes_de_crear_la_orden(saleor, cliente):
    falso = saleor()
    _pedir(cliente)
    linea = falso.variables["checkoutLinesUpdate"]["lines"][0]
    assert linea["price"] == 7900
    assert falso.ops.index("checkoutLinesUpdate") < falso.ops.index("orderCreateFromCheckout")


def test_con_facturacion_no_se_toca_la_direccion(saleor, cliente):
    falso = saleor(facturacion=True)
    assert _pedir(cliente).status_code == 200
    assert "checkoutBillingAddressUpdate" not in falso.ops


def test_la_facturacion_se_copia_del_despacho(saleor, cliente):
    """`orderCreateFromCheckout` rechaza un carrito sin facturación, y el
    checkout B2B solo pide despacho."""
    falso = saleor(facturacion=False)
    _pedir(cliente)
    direccion = falso.variables["checkoutBillingAddressUpdate"]["direccion"]
    assert direccion["streetAddress1"] == "Av. Siempre Viva 742"
    assert direccion["country"] == "CL", "en la escritura el país es un código"
    assert "streetAddress2" not in direccion, "los vacíos no se envían"


def test_sin_ninguna_direccion_es_422_y_no_se_crea_la_orden(saleor, cliente):
    falso = saleor(facturacion=False, despacho=False)
    r = _pedir(cliente)
    assert r.status_code == 422
    assert "dirección" in r.json()["detail"]
    assert r.json()["code"] == "SHIPPING_ADDRESS_NOT_SET"
    assert "orderCreateFromCheckout" not in falso.ops


def test_direccion_rechazada_por_saleor_es_422(saleor, cliente, caplog):
    falso = saleor(facturacion=False, errores_facturacion=[
        {"field": "postalCode", "message": "invalid", "code": "INVALID"}])
    r = _pedir(cliente)
    assert r.status_code == 422
    assert r.json()["code"] == "BILLING_ADDRESS_INVALID"
    # El error crudo de Saleor va al log, no a la respuesta.
    assert "postalCode" not in r.text
    assert "postalCode" in caplog.text
    assert "orderCreateFromCheckout" not in falso.ops


# ───────────────── rechazos antes de escribir ─────────────────

def test_empresa_en_revision_es_403_y_no_se_toca_el_carrito(monkeypatch, saleor, cliente):
    """Ni reprecio ni orden: el carrito queda tal cual para cuando el staff
    apruebe la empresa."""
    monkeypatch.setattr(main.company_svc, "obtener_de_usuario",
                        lambda uid: _company(nivel_precio="retail-cl"))
    falso = saleor(facturacion=False)
    r = _pedir(cliente)
    assert r.status_code == 403
    assert r.json() == {
        "detail": "Tu empresa está en revisión. Te avisaremos cuando esté "
                  "habilitada para comprar.",
        "code": "PENDIENTE_APROBACION"}
    assert falso.ops == ["checkout"]


def test_la_revision_se_decide_por_el_nivel_y_los_canales(monkeypatch, saleor, cliente):
    monkeypatch.setattr(config, "CANALES", ["b2b-cl", "b2b-norte"])
    monkeypatch.setattr(main.company_svc, "obtener_de_usuario",
                        lambda uid: _company(nivel_precio="b2b-norte"))
    saleor()
    assert _pedir(cliente).status_code == 200


def test_sin_empresa_es_403_con_codigo(monkeypatch, saleor, cliente):
    monkeypatch.setattr(main.company_svc, "obtener_de_usuario", lambda uid: None)
    falso = saleor()
    r = _pedir(cliente)
    assert r.status_code == 403
    assert r.json()["code"] == "SIN_EMPRESA"
    assert falso.ops == ["checkout"]

@pytest.mark.parametrize("dueno", ["VXNlcjo5OTk=", None])
def test_carrito_ajeno_es_403_y_no_se_escribe_nada(saleor, cliente, dueno):
    falso = saleor(dueno=dueno)
    r = _pedir(cliente)
    assert r.status_code == 403
    assert falso.ops == ["checkout"]


def test_carrito_inexistente_es_404(saleor, cliente):
    falso = saleor()
    falso.checkout = None
    assert _pedir(cliente).status_code == 404


def test_carrito_en_canal_retail_es_422(saleor, cliente):
    """Un pedido por pagar en retail sería una venta que nadie espera cobrar."""
    falso = saleor(canal="retail-cl")
    r = _pedir(cliente)
    assert r.status_code == 422
    assert r.json()["code"] == "CANAL_NO_B2B"
    assert falso.ops == ["checkout"]


def test_los_canales_b2b_vienen_de_la_configuracion(monkeypatch, saleor, cliente):
    monkeypatch.setattr(config, "CANALES", ["b2b-cl", "b2b-norte"])
    saleor(canal="b2b-norte")
    assert _pedir(cliente).status_code == 200


def test_medio_no_disponible_no_toca_el_carrito(saleor, cliente):
    falso = saleor()
    r = _pedir(cliente, metodo=medios.MAXXA_30)
    assert r.status_code == 409
    assert r.json()["code"] == "MEDIO_NO_DISPONIBLE"
    assert falso.ops == ["checkout"]


# ───────────────── precios negociados ─────────────────

def test_el_reprecio_del_pedido_no_toca_lo_negociado(saleor, cliente):
    """Un precio que acordó el staff se cobra tal cual, aunque la cantidad
    alcance un tramo."""
    falso = saleor(lineas=[{"id": "TGluZTox", "quantity": 12, "variant": {"id": VAR},
                            "priceOverrideReason": cart.motivo_negociado(12)}])
    assert _pedir(cliente).status_code == 200
    assert "productVariant" not in falso.ops
    assert "checkoutLinesUpdate" not in falso.ops


def test_negociado_con_otra_cantidad_es_409_y_no_se_toca_nada(saleor, cliente):
    """Saleor conserva el precio fijado cuando el cliente cambia solo la
    cantidad: 500 unidades a precio de volumen no pueden cerrarse como 1."""
    falso = saleor(lineas=[{"id": "TGluZTox", "quantity": 1, "variant": {"id": VAR},
                            "priceOverrideReason": cart.motivo_negociado(500)}])
    r = _pedir(cliente)
    assert r.status_code == 409
    assert r.json()["code"] == "CARRITO_MODIFICADO"
    assert falso.ops == ["checkout"]


def test_negociado_sin_cantidad_de_un_carrito_anterior_se_respeta(saleor, cliente):
    """Un carrito armado antes de que el motivo llevara la cantidad no se puede
    verificar: se respeta como antes, en vez de dejarlo sin poder comprarse."""
    falso = saleor(lineas=[{"id": "TGluZTox", "quantity": 3, "variant": {"id": VAR},
                            "priceOverrideReason": cart.MOTIVO_NEGOCIADO}])
    assert _pedir(cliente).status_code == 200
    assert "checkoutLinesUpdate" not in falso.ops


def test_si_la_cantidad_cambia_mientras_se_confirma_no_se_crea_la_orden(saleor, cliente):
    """El reprecio trabaja sobre la foto leída al comienzo; si otra pestaña
    cambió la cantidad entretanto, el tramo fijado ya no le corresponde."""
    alterado = _Saleor().checkout
    alterado["lines"] = [dict(alterado["lines"][0], quantity=1)]
    falso = saleor(relectura=alterado)
    r = _pedir(cliente)
    assert r.status_code == 409
    assert r.json()["code"] == "CARRITO_MODIFICADO"
    assert "orderCreateFromCheckout" not in falso.ops


def test_si_el_carrito_desaparece_mientras_se_confirma_no_se_crea_la_orden(saleor, cliente):
    falso = saleor(relectura=None)
    r = _pedir(cliente)
    assert r.status_code == 409
    assert r.json()["code"] == "CHECKOUT_NOT_FOUND"
    assert "orderCreateFromCheckout" not in falso.ops


def test_el_reprecio_del_pedido_borra_solo_el_tramo_vencido(saleor, cliente):
    falso = saleor(lineas=[
        {"id": "negociada", "quantity": 2, "variant": {"id": VAR},
         "priceOverrideReason": cart.MOTIVO_NEGOCIADO},
        # 2 unidades ya no alcanzan el tramo de 4: vuelve a lista.
        {"id": "tramo", "quantity": 2, "variant": {"id": VAR},
         "priceOverrideReason": cart.MOTIVO_TRAMO},
    ])
    assert _pedir(cliente).status_code == 200
    lineas = falso.variables["checkoutLinesUpdate"]["lines"]
    assert [l["lineId"] for l in lineas] == ["tramo"]


# ───────────────── Saleor rechaza la orden ─────────────────

@pytest.mark.parametrize("codigo,estado", [
    ("INSUFFICIENT_STOCK", 409),
    ("UNAVAILABLE_VARIANT_IN_CHANNEL", 409),
    ("CHECKOUT_NOT_FOUND", 409),
    ("SHIPPING_METHOD_NOT_SET", 422),
    ("EMAIL_NOT_SET", 422),
    ("NO_LINES", 422),
])
def test_los_rechazos_de_saleor_llegan_con_codigo_y_en_castellano(
        saleor, cliente, caplog, codigo, estado):
    saleor(errores_orden=[{"field": "lines", "message": "Insufficient product stock: X",
                           "code": codigo}])
    r = _pedir(cliente)
    assert r.status_code == estado
    d = r.json()
    assert d["code"] == codigo
    assert d["detail"] == pedido_svc.explicar(codigo)[1]
    # Lo crudo de Saleor (inglés, nombres de campos) solo al log.
    assert "Insufficient" not in r.text
    assert "Insufficient" in caplog.text


def test_un_codigo_desconocido_recibe_un_mensaje_generico(saleor, cliente):
    saleor(errores_orden=[{"field": None, "message": "boom", "code": "ALGO_NUEVO"}])
    r = _pedir(cliente)
    assert r.status_code == 422
    assert r.json()["code"] == "ALGO_NUEVO"
    assert "boom" not in r.text


def test_sin_codigo_se_usa_uno_propio(saleor, cliente):
    saleor(errores_orden=[{"field": None, "message": "boom", "code": None}])
    r = _pedir(cliente)
    assert r.status_code == 422
    assert r.json()["code"] == "ORDEN_RECHAZADA"


def test_todo_codigo_de_saleor_tiene_explicacion():
    """Los códigos de `OrderCreateFromCheckoutErrorCode` en Saleor 3.23. Uno sin
    entrada cae en el genérico: correcto, pero pierde la pista para el cliente."""
    esquema = {"CHECKOUT_NOT_FOUND", "CHANNEL_INACTIVE", "INSUFFICIENT_STOCK",
               "VOUCHER_NOT_APPLICABLE", "GIFT_CARD_NOT_APPLICABLE", "TAX_ERROR",
               "SHIPPING_METHOD_NOT_SET", "BILLING_ADDRESS_NOT_SET",
               "SHIPPING_ADDRESS_NOT_SET", "INVALID_SHIPPING_METHOD", "NO_LINES",
               "EMAIL_NOT_SET", "UNAVAILABLE_VARIANT_IN_CHANNEL"}
    for codigo in esquema:
        estado, mensaje = pedido_svc.explicar(codigo)
        assert estado in (409, 422)
        assert mensaje != pedido_svc.explicar("GRAPHQL_ERROR")[1], codigo


def test_sin_orden_y_sin_errores_es_502(saleor, cliente):
    """Una respuesta que Saleor no debería dar es un fallo de la integración,
    no algo que el cliente pueda corregir en su carrito."""
    saleor(sin_orden=True)
    assert _pedir(cliente).status_code == 502


# ───────────────── fallos de Saleor ─────────────────

def test_si_el_reprecio_falla_no_hay_pedido(saleor, cliente):
    """Crear la orden igual cobraría un precio que no se pudo confirmar."""
    falso = saleor(falla_variante=SaleorTransportError("caído"))
    r = _pedir(cliente)
    assert r.status_code == 502
    assert "no se creó" in r.json()["detail"]
    assert "orderCreateFromCheckout" not in falso.ops


def test_si_saleor_rechaza_el_reprecio_no_hay_pedido(saleor, cliente):
    falso = saleor(errores_lineas=[{"field": "price", "message": "no", "code": "INVALID"}])
    assert _pedir(cliente).status_code == 502
    assert "orderCreateFromCheckout" not in falso.ops


def test_timeout_al_crear_la_orden_es_504_y_no_se_repite(saleor, cliente):
    """Tras un timeout la orden pudo haberse creado: repetir duplicaría el
    pedido, así que se avisa al cliente que revise."""
    falso = saleor(falla_orden=SaleorTimeoutError("sin respuesta"))
    r = _pedir(cliente)
    assert r.status_code == 504
    assert "revisa tus pedidos" in r.json()["detail"]
    assert falso.ops.count("orderCreateFromCheckout") == 1


def test_las_escrituras_del_pedido_no_se_reintentan(saleor, cliente):
    falso = saleor(facturacion=False)
    _pedir(cliente)
    for op in ("checkoutLinesUpdate", "checkoutBillingAddressUpdate",
               "orderCreateFromCheckout"):
        assert falso.opciones[op].get("reintentar") is False, op


# ───────────────── instrucciones de pago ─────────────────

def test_transferencia_devuelve_las_instrucciones(monkeypatch, saleor, cliente):
    monkeypatch.setattr(config, "INSTRUCCIONES_TRANSFERENCIA",
                        "Banco de Prueba, cuenta corriente 000-000")
    saleor()
    d = _pedir(cliente).json()
    assert d["instrucciones_pago"] == "Banco de Prueba, cuenta corriente 000-000"
    assert d["numero"] == "1042"


def test_sin_instrucciones_configuradas_es_null(saleor, cliente):
    saleor()
    d = _pedir(cliente).json()
    assert "instrucciones_pago" in d
    assert d["instrucciones_pago"] is None


def test_otros_medios_no_llevan_instrucciones_de_transferencia(monkeypatch, saleor, cliente):
    monkeypatch.setattr(config, "INSTRUCCIONES_TRANSFERENCIA", "Banco de Prueba")
    monkeypatch.setattr(main.company_svc, "obtener_de_usuario",
                        lambda uid: _company(condicion_pago="credito_30",
                                             credito_estado="aprobada"))
    saleor()
    d = _pedir(cliente, metodo=medios.MAXXA_30).json()
    assert d["metodo_pago"] == medios.MAXXA_30
    assert d["instrucciones_pago"] is None
