"""Tests de la lógica pura de facturación (sin red, sin Playwright)."""

from __future__ import annotations

from ventu_facturacion import handlers


def test_rut_valid():
    assert handlers.rut_is_valid("77844948-K")
    assert handlers.rut_is_valid("11.111.111-1")
    assert not handlers.rut_is_valid("77844948-0")
    assert not handlers.rut_is_valid("")


def test_decide_factura_when_valid_rut_and_razon():
    r = {"rut": "77844948-K", "razon_social": "ACME SPA"}
    assert handlers.decide_document_type(r) == "factura"


def test_decide_boleta_without_rut_or_razon():
    assert handlers.decide_document_type({"rut": "", "razon_social": ""}) == "boleta"
    assert handlers.decide_document_type({"rut": "77844948-K", "razon_social": ""}) == "boleta"
    assert handlers.decide_document_type({"rut": "1-9", "razon_social": "X"}) == "boleta"  # rut inválido


def test_extract_receptor_from_metadata_list():
    order = {"metadata": [
        {"key": "ventu.rut", "value": "77844948-K"},
        {"key": "ventu.razon_social", "value": "ACME SPA"},
        {"key": "ventu.giro", "value": "COMERCIO"},
    ]}
    r = handlers.extract_receptor(order)
    assert r["rut"] == "77844948-K" and r["razon_social"] == "ACME SPA" and r["giro"] == "COMERCIO"


def test_already_invoiced_idempotency():
    assert handlers.already_invoiced({"metadata": [{"key": "ventu.dte.folio", "value": "1024"}]})
    assert not handlers.already_invoiced({"metadata": []})


def test_factura_items_net_from_gross():
    order = {"lines": [
        {"quantity": 2, "product_name": "Cable", "unit_price_gross_amount": "11900"},
    ]}
    items = handlers.order_to_factura_items(order)
    # 11900 bruto → neto 11900/1.19 = 10000
    assert items == [{"nombre": "Cable", "cantidad": 2, "precio_neto": 10000}]


def test_boleta_items_keep_gross():
    order = {"lines": [
        {"quantity": 1, "productName": "Mouse", "unitPrice": {"gross": {"amount": "9990"}}},
    ]}
    items = handlers.order_to_boleta_items(order)
    assert items == [{"nombre": "Mouse", "cantidad": 1, "precio": 9990}]
