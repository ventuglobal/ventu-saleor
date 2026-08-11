"""El carrito se cierra como orden, y el pedido B2B nace por pagar."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from ventu_b2b import main
from ventu_b2b.company.models import Company
from ventu_b2b.pedido import medios, service as pedido_svc

CHECKOUT = "Q2hlY2tvdXQ6MQ=="
USUARIO = "VXNlcjo1"


@pytest.fixture
def cliente():
    return TestClient(main.app)


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
    codigos = [m["codigo"] for m in medios.disponibles(tiene_credito=False)]
    assert codigos == [medios.TARJETA_CREDITO, medios.TARJETA_DEBITO,
                       medios.TRANSFERENCIA, medios.MAXXA_30]


def test_maxxa_se_muestra_aunque_no_haya_credito():
    """Esconderlo le oculta a la empresa justamente la razón para solicitarlo."""
    vitrina = {m["codigo"]: m for m in medios.disponibles(tiene_credito=False)}
    assert vitrina[medios.MAXXA_30]["habilitado"] is False
    assert vitrina[medios.MAXXA_30]["motivo"] == "sin_credito"


def test_con_credito_aprobado_maxxa_queda_habilitado():
    vitrina = {m["codigo"]: m for m in medios.disponibles(tiene_credito=True)}
    assert vitrina[medios.MAXXA_30]["habilitado"] is True


def test_las_tarjetas_se_ofrecen_pero_no_estan_conectadas():
    vitrina = {m["codigo"]: m for m in medios.disponibles(tiene_credito=True)}
    for tarjeta in (medios.TARJETA_CREDITO, medios.TARJETA_DEBITO):
        assert vitrina[tarjeta]["habilitado"] is False
        assert vitrina[tarjeta]["motivo"] == "no_operativo"


# ───────────────── validación del medio ─────────────────

def test_medio_desconocido_se_rechaza():
    with pytest.raises(medios.MedioNoDisponible):
        medios.validar("bitcoin", tiene_credito=True)


def test_maxxa_sin_credito_se_rechaza():
    with pytest.raises(medios.MedioNoDisponible, match="crédito"):
        medios.validar(medios.MAXXA_30, tiene_credito=False)


def test_tarjeta_no_conectada_se_rechaza():
    """Cerrar el pedido con una tarjeta sin pasarela sería dar por cobrado algo
    que nadie cobró."""
    with pytest.raises(medios.MedioNoDisponible, match="conectado"):
        medios.validar(medios.TARJETA_CREDITO, tiene_credito=True)


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


# ───────────────── el endpoint ─────────────────

def test_endpoint_crea_el_pedido(monkeypatch, cliente):
    monkeypatch.setattr(main.company_svc, "obtener_de_usuario", lambda uid: _company())
    monkeypatch.setattr(pedido_svc, "gql", _saleor_ok())

    r = cliente.post("/pedido", json={"checkout_id": CHECKOUT, "user_id": USUARIO,
                                      "metodo_pago": medios.TRANSFERENCIA})
    assert r.status_code == 200
    d = r.json()
    assert d["numero"] == "1042"
    assert d["estado_pago"] == medios.PENDIENTE


def test_sin_empresa_no_se_puede_comprar_como_empresa(monkeypatch, cliente):
    monkeypatch.setattr(main.company_svc, "obtener_de_usuario", lambda uid: None)
    r = cliente.post("/pedido", json={"checkout_id": CHECKOUT, "user_id": USUARIO,
                                      "metodo_pago": medios.TRANSFERENCIA})
    assert r.status_code == 403


def test_maxxa_sin_credito_devuelve_409(monkeypatch, cliente):
    """409 y no 400: el medio es válido, lo que no corresponde es el estado de
    esta empresa."""
    monkeypatch.setattr(main.company_svc, "obtener_de_usuario", lambda uid: _company())
    r = cliente.post("/pedido", json={"checkout_id": CHECKOUT, "user_id": USUARIO,
                                      "metodo_pago": medios.MAXXA_30})
    assert r.status_code == 409


def test_maxxa_con_credito_aprobado_cierra(monkeypatch, cliente):
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
    assert len(d["medios_pago"]) == 4


def test_usuario_sin_empresa_no_es_un_error(monkeypatch, cliente):
    monkeypatch.setattr(main.company_svc, "obtener_de_usuario", lambda uid: None)
    r = cliente.get(f"/company/de-usuario/{USUARIO}")
    assert r.status_code == 200
    assert r.json() == {"registrada": False}
