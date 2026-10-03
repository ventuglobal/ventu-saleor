"""El carrito se cierra como orden, y el pedido B2B nace por pagar."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from ventu_b2b import main
from ventu_b2b.cart import reprecio
from ventu_b2b.company.models import Company
from ventu_b2b.pedido import medios, service as pedido_svc

CHECKOUT = "Q2hlY2tvdXQ6MQ=="
USUARIO = "VXNlcjo1"


@pytest.fixture
def cliente():
    return TestClient(main.app)


@pytest.fixture
def carrito(monkeypatch):
    """Un carrito B2B propio, con facturación y sin líneas por reprecificar:
    aísla estos tests de la creación de la orden. El flujo completo (dueño,
    canal, reprecio, facturación) se prueba en test_pedido_flujo."""
    monkeypatch.setattr(reprecio, "gql", lambda q, v=None, **kw: {"data": {"checkout": {
        "id": CHECKOUT, "channel": {"slug": "b2b-cl"}, "user": {"id": USUARIO},
        "billingAddress": {"id": "QWRkcmVzczox"}, "shippingAddress": None, "lines": [],
    }}})


def _company(**kw):
    base = dict(rut="76.543.210-3", razon_social="Comercial Ventu SpA",
                nivel_precio="b2b-cl")
    base.update(kw)
    return Company(**base)


def _con_credito():
    return _company(condicion_pago="credito_30", credito_estado="aprobada")


def _saleor_ok(capturado=None):
    def gql(query, variables=None, **kw):
        if capturado is not None:
            capturado.append(variables)
        return {"data": {"orderCreateFromCheckout": {
            "order": {"id": "T3JkZXI6MQ==", "number": 1042, "status": "UNFULFILLED",
                      "total": {"gross": {"amount": 133512.0, "currency": "CLP"}}},
            "errors": [],
        }}}
    return gql


# ───────────────── la vitrina de medios ─────────────────

def test_se_ofrecen_los_cuatro_medios():
    codigos = [m["codigo"] for m in medios.disponibles(tiene_credito=False, aprobada=True)]
    assert codigos == [medios.TARJETA_CREDITO, medios.TARJETA_DEBITO,
                       medios.TRANSFERENCIA, medios.MAXXA_30]


def test_maxxa_se_muestra_aunque_no_haya_credito():
    """Esconderlo le oculta a la empresa justamente la razón para solicitarlo."""
    vitrina = {m["codigo"]: m for m in medios.disponibles(tiene_credito=False, aprobada=True)}
    assert vitrina[medios.MAXXA_30]["habilitado"] is False
    assert vitrina[medios.MAXXA_30]["motivo"] == "sin_credito"


def test_con_credito_aprobado_maxxa_queda_habilitado():
    vitrina = {m["codigo"]: m for m in medios.disponibles(tiene_credito=True, aprobada=True)}
    assert vitrina[medios.MAXXA_30]["habilitado"] is True


def test_las_tarjetas_estan_habilitadas():
    """Con Webpay conectado la tarjeta es un medio B2B más: la empresa aprobada
    puede elegirla sin crédito (el cobro va por la pasarela, no a 30 días)."""
    vitrina = {m["codigo"]: m for m in medios.disponibles(tiene_credito=False, aprobada=True)}
    for tarjeta in (medios.TARJETA_CREDITO, medios.TARJETA_DEBITO):
        assert vitrina[tarjeta]["habilitado"] is True
        assert "motivo" not in vitrina[tarjeta]
        assert vitrina[tarjeta]["diferido"] is False


def test_empresa_en_revision_ve_todos_los_medios_deshabilitados():
    """Se muestran igual —para que sepa qué va a poder usar— pero ninguno
    habilitado, y todos con el mismo motivo: el que importa es la revisión."""
    for tiene_credito in (False, True):
        vitrina = medios.disponibles(tiene_credito=tiene_credito, aprobada=False)
        assert len(vitrina) == 4
        for m in vitrina:
            assert m["habilitado"] is False
            assert m["motivo"] == medios.PENDIENTE_APROBACION == "pendiente_aprobacion"


def test_aprobada_es_obligatorio():
    """Olvidarlo tiene que fallar, no dejar los medios abiertos a una empresa
    en revisión."""
    with pytest.raises(TypeError):
        medios.disponibles(tiene_credito=True)


# ───────────────── validación del medio ─────────────────

def test_medio_desconocido_se_rechaza():
    with pytest.raises(medios.MedioNoDisponible):
        medios.validar("bitcoin", tiene_credito=True)


def test_maxxa_sin_credito_se_rechaza():
    with pytest.raises(medios.MedioNoDisponible, match="crédito"):
        medios.validar(medios.MAXXA_30, tiene_credito=False)


def test_tarjeta_es_un_medio_valido():
    """Con Webpay conectado `validar()` acepta la tarjeta: nace por pagar y la
    pasarela la cobra sobre la orden."""
    medio = medios.validar(medios.TARJETA_CREDITO, tiene_credito=False)
    assert medio.codigo == medios.TARJETA_CREDITO
    assert medio.operativo is True
    assert medio.diferido is False


# ───────────────── creación de la orden ─────────────────

def test_transferencia_cierra_el_pedido(monkeypatch):
    monkeypatch.setattr(pedido_svc, "gql", _saleor_ok())
    p = pedido_svc.crear(CHECKOUT, medios.TRANSFERENCIA, tiene_credito=False)
    assert p.numero == "1042"
    assert p.total == 133512.0
    assert p.metodo_pago == medios.TRANSFERENCIA


def test_el_pedido_nace_por_pagar(monkeypatch):
    capturado = []
    monkeypatch.setattr(pedido_svc, "gql", _saleor_ok(capturado))
    pedido_svc.crear(CHECKOUT, medios.TRANSFERENCIA, tiene_credito=False)

    meta = {e["key"]: e["value"] for e in capturado[0]["metadata"]}
    assert meta[medios.K_ESTADO] == medios.PENDIENTE
    assert meta[medios.K_METODO] == medios.TRANSFERENCIA


def test_tarjeta_tambien_nace_por_pagar(monkeypatch):
    """Orden-primero: la orden de tarjeta se crea por pagar igual que la
    diferida; Webpay la cobra después sobre la orden ya creada."""
    capturado = []
    monkeypatch.setattr(pedido_svc, "gql", _saleor_ok(capturado))
    p = pedido_svc.crear(CHECKOUT, medios.TARJETA_CREDITO, tiene_credito=False)

    assert p.metodo_pago == medios.TARJETA_CREDITO
    meta = {e["key"]: e["value"] for e in capturado[0]["metadata"]}
    assert meta[medios.K_ESTADO] == medios.PENDIENTE
    assert meta[medios.K_METODO] == medios.TARJETA_CREDITO


def test_la_identidad_tributaria_viaja_a_la_orden(monkeypatch):
    """Sin esto la orden no se puede facturar."""
    capturado = []
    monkeypatch.setattr(pedido_svc, "gql", _saleor_ok(capturado))
    pedido_svc.crear(CHECKOUT, medios.TRANSFERENCIA, tiene_credito=False,
                     extra_metadata=_company().para_orden(company_id=USUARIO))

    meta = {e["key"]: e["value"] for e in capturado[0]["metadata"]}
    assert "76543210-3" in meta.values()


def test_un_medio_invalido_no_toca_saleor(monkeypatch):
    """Si el medio no corresponde, el carrito debe quedar intacto para que el
    cliente elija otro."""
    def explota(*a, **kw):
        raise AssertionError("no debió llamarse a Saleor")

    monkeypatch.setattr(pedido_svc, "gql", explota)
    with pytest.raises(medios.MedioNoDisponible):
        pedido_svc.crear(CHECKOUT, medios.MAXXA_30, tiene_credito=False)


def test_error_de_saleor_se_propaga(monkeypatch):
    def gql(query, variables=None, **kw):
        return {"data": {"orderCreateFromCheckout": {
            "order": None,
            "errors": [{"field": "lines", "message": "insufficient stock",
                        "code": "INSUFFICIENT_STOCK"}]}}}

    monkeypatch.setattr(pedido_svc, "gql", gql)
    with pytest.raises(pedido_svc.PedidoError, match="stock"):
        pedido_svc.crear(CHECKOUT, medios.TRANSFERENCIA, tiene_credito=False)


def test_el_rechazo_de_la_orden_conserva_el_codigo(monkeypatch):
    """El endpoint traduce por código; el mensaje crudo solo sirve para el log."""
    errores = [{"field": "lines", "message": "insufficient stock",
                "code": "INSUFFICIENT_STOCK"}]
    monkeypatch.setattr(pedido_svc, "gql", lambda q, v=None, **kw: {"data": {
        "orderCreateFromCheckout": {"order": None, "errors": errores}}})
    with pytest.raises(pedido_svc.OrdenRechazada) as info:
        pedido_svc.crear(CHECKOUT, medios.TRANSFERENCIA, tiene_credito=False)
    assert info.value.codigo == "INSUFFICIENT_STOCK"
    assert info.value.errores == errores


def test_sin_orden_ni_errores_es_una_respuesta_rota(monkeypatch):
    from ventu_b2b.saleor_client import SaleorRespuestaError

    monkeypatch.setattr(pedido_svc, "gql", lambda q, v=None, **kw: {"data": {
        "orderCreateFromCheckout": {"order": None, "errors": []}}})
    with pytest.raises(SaleorRespuestaError):
        pedido_svc.crear(CHECKOUT, medios.TRANSFERENCIA, tiene_credito=False)


def test_explicar_distingue_conflicto_de_datos_faltantes():
    """409: el carrito está bien armado pero algo cambió (stock, canal).
    422: al carrito le falta algo que el cliente puede completar."""
    assert pedido_svc.explicar("INSUFFICIENT_STOCK")[0] == 409
    assert pedido_svc.explicar("SHIPPING_METHOD_NOT_SET")[0] == 422
    assert pedido_svc.explicar("NO_EXISTE")[0] == 422
    assert pedido_svc.explicar("")[0] == 422


# ───────────────── el endpoint ─────────────────

def test_endpoint_crea_el_pedido(monkeypatch, cliente, carrito):
    monkeypatch.setattr(main.company_svc, "obtener_de_usuario", lambda uid: _company())
    monkeypatch.setattr(pedido_svc, "gql", _saleor_ok())

    r = cliente.post("/pedido", json={"checkout_id": CHECKOUT, "user_id": USUARIO,
                                      "metodo_pago": medios.TRANSFERENCIA})
    assert r.status_code == 200
    d = r.json()
    assert d["numero"] == "1042"
    assert d["estado_pago"] == medios.PENDIENTE


def test_sin_empresa_no_se_puede_comprar_como_empresa(monkeypatch, cliente, carrito):
    monkeypatch.setattr(main.company_svc, "obtener_de_usuario", lambda uid: None)
    r = cliente.post("/pedido", json={"checkout_id": CHECKOUT, "user_id": USUARIO,
                                      "metodo_pago": medios.TRANSFERENCIA})
    assert r.status_code == 403


def test_maxxa_sin_credito_devuelve_409(monkeypatch, cliente, carrito):
    """409 y no 400: el medio es válido, lo que no corresponde es el estado de
    esta empresa."""
    monkeypatch.setattr(main.company_svc, "obtener_de_usuario", lambda uid: _company())
    r = cliente.post("/pedido", json={"checkout_id": CHECKOUT, "user_id": USUARIO,
                                      "metodo_pago": medios.MAXXA_30})
    assert r.status_code == 409


def test_maxxa_con_credito_aprobado_cierra(monkeypatch, cliente, carrito):
    monkeypatch.setattr(main.company_svc, "obtener_de_usuario", lambda uid: _con_credito())
    monkeypatch.setattr(pedido_svc, "gql", _saleor_ok())
    r = cliente.post("/pedido", json={"checkout_id": CHECKOUT, "user_id": USUARIO,
                                      "metodo_pago": medios.MAXXA_30})
    assert r.status_code == 200
    assert r.json()["metodo_pago"] == medios.MAXXA_30


# ───────────────── la empresa del usuario ─────────────────

def test_usuario_con_empresa(monkeypatch, cliente):
    monkeypatch.setattr(main.company_svc, "obtener_de_usuario", lambda uid: _company())
    d = cliente.get(f"/company/de-usuario/{USUARIO}").json()
    assert d["registrada"] is True
    assert d["rut"] == "76543210-3"  # normalizado
    assert d["nivel_precio"] == "b2b-cl"
    assert d["aprobada"] is True
    assert d["estado"] == "aprobada"
    assert len(d["medios_pago"]) == 4
    # Sin crédito: Maxxa queda fuera; tarjeta (Webpay) y transferencia habilitadas.
    assert {m["codigo"] for m in d["medios_pago"] if m["habilitado"]} == {
        medios.TARJETA_CREDITO, medios.TARJETA_DEBITO, medios.TRANSFERENCIA}


def test_empresa_en_revision_lo_dice_y_no_tiene_medios(monkeypatch, cliente):
    monkeypatch.setattr(main.company_svc, "obtener_de_usuario",
                        lambda uid: _company(nivel_precio="retail-cl"))
    d = cliente.get(f"/company/de-usuario/{USUARIO}").json()
    assert d["registrada"] is True
    assert d["aprobada"] is False
    assert d["estado"] == "pendiente"
    assert len(d["medios_pago"]) == 4
    assert all(m["habilitado"] is False and m["motivo"] == "pendiente_aprobacion"
               for m in d["medios_pago"])


def test_usuario_sin_empresa_no_es_un_error(monkeypatch, cliente):
    monkeypatch.setattr(main.company_svc, "obtener_de_usuario", lambda uid: None)
    r = cliente.get(f"/company/de-usuario/{USUARIO}")
    assert r.status_code == 200
    assert r.json() == {"registrada": False}
