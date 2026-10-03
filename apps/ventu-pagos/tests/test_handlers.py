"""Tests de los helpers puros de pagos (sin red)."""

from __future__ import annotations

from ventu_pagos import handlers


def test_to_amount_rounds_to_integer_clp():
    assert handlers.to_amount(13150.0) == 13150
    assert handlers.to_amount("999.6") == 1000


def test_new_buy_order_is_unique_short_and_valid():
    a = handlers.new_buy_order()
    b = handlers.new_buy_order()
    assert a != b  # un buy_order nuevo por cada intento
    assert len(a) <= 26
    assert a.startswith("VR")
    # charset Webpay permitido (sin acentos ni espacios)
    assert all(c.isalnum() or c in "|_=&%.,~:/?[+!@()>-" for c in a)


def test_session_id_truncates_to_61():
    sid = handlers.webpay_session_id("x" * 100)
    assert len(sid) == 61


def test_commit_authorized_requires_authorized_and_zero():
    assert handlers.commit_authorized({"status": "AUTHORIZED", "response_code": 0})
    assert not handlers.commit_authorized({"status": "AUTHORIZED", "response_code": -1})
    assert not handlers.commit_authorized({"status": "FAILED", "response_code": 0})


def test_commit_result_maps_authorized_zero_to_success():
    assert handlers.commit_result({"status": "AUTHORIZED", "response_code": 0}) == "CHARGE_SUCCESS"
    assert handlers.commit_result({"status": "AUTHORIZED", "response_code": -1}) == "CHARGE_FAILURE"
    assert handlers.commit_result({"status": "FAILED", "response_code": 0}) == "CHARGE_FAILURE"


def test_refund_result_maps_response_code():
    assert handlers.refund_result({"type": "NULLIFIED", "response_code": 0}) == "REFUND_SUCCESS"
    assert handlers.refund_result({"type": "REVERSED"}) == "REFUND_SUCCESS"
    assert handlers.refund_result({"response_code": 1}) == "REFUND_FAILURE"


def test_payment_metadata_extracts_webpay_fields():
    meta = handlers.payment_metadata({
        "authorization_code": "1213",
        "payment_type_code": "VD",
        "installments_number": 0,
        "card_detail": {"card_number": "6623"},
    })
    assert meta["ventu.pago.metodo"] == "webpay"
    assert meta["ventu.pago.authorization_code"] == "1213"
    assert meta["ventu.pago.payment_type_code"] == "VD"
    assert meta["ventu.pago.card_last4"] == "6623"


def test_action_required_response_shape():
    r = handlers.action_required_response(
        psp_reference="tok", amount=13150, webpay_url="https://wp/x", token="tok")
    assert r["result"] == "CHARGE_ACTION_REQUIRED"
    assert r["pspReference"] == "tok"
    assert r["data"]["webpayUrl"] == "https://wp/x" and r["data"]["token"] == "tok"


def test_handled_events_cover_payment_flow():
    for e in ("transaction_initialize_session", "transaction_process_session",
              "transaction_refund_requested", "transaction_cancelation_requested",
              "payment_gateway_initialize_session"):
        assert e in handlers.HANDLED_EVENTS
