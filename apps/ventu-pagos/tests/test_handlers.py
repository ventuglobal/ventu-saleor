"""Tests de los helpers puros de pagos (sin red)."""

from __future__ import annotations

from ventu_pagos import handlers


def test_to_amount_rounds_to_integer_clp():
    assert handlers.to_amount(13150.0) == 13150
    assert handlers.to_amount("999.6") == 1000


def test_buy_order_sanitizes_and_truncates_to_26():
    bo = handlers.webpay_buy_order("Txn:abc/123 def*456789012345678901234567890")
    assert len(bo) <= 26
    assert all(c.isalnum() or c in "_-" for c in bo)


def test_session_id_truncates_to_61():
    sid = handlers.webpay_session_id("x" * 100)
    assert len(sid) == 61


def test_commit_result_maps_authorized_zero_to_success():
    assert handlers.commit_result({"status": "AUTHORIZED", "response_code": 0}) == "CHARGE_SUCCESS"
    assert handlers.commit_result({"status": "AUTHORIZED", "response_code": -1}) == "CHARGE_FAILURE"
    assert handlers.commit_result({"status": "FAILED", "response_code": 0}) == "CHARGE_FAILURE"


def test_refund_result_maps_response_code():
    assert handlers.refund_result({"response_code": 0}) == "REFUND_SUCCESS"
    assert handlers.refund_result({"response_code": 1}) == "REFUND_FAILURE"


def test_action_required_response_shape():
    r = handlers.action_required_response(
        psp_reference="T1", amount=13150, webpay_url="https://wp/x", token="tok")
    assert r["result"] == "CHARGE_ACTION_REQUIRED"
    assert r["pspReference"] == "T1"
    assert r["data"]["webpayUrl"] == "https://wp/x" and r["data"]["token"] == "tok"


def test_handled_events_cover_payment_flow():
    for e in ("transaction_initialize_session", "transaction_refund_requested",
              "payment_gateway_initialize_session"):
        assert e in handlers.HANDLED_EVENTS
