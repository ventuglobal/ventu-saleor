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


# ─────────────────── errores de Transbank legibles ───────────────────

class _Resp:
    def __init__(self, code, body, text=""):
        self.status_code = code
        self._body = body
        self.text = text

    def json(self):
        if self._body is None:
            raise ValueError("no json")
        return self._body


def test_error_de_transbank_conserva_el_motivo():
    """Un 422 debe decir POR QUE lo rechaza Transbank, no solo el codigo."""
    from ventu_pagos import webpay_client
    import pytest
    with pytest.raises(webpay_client.WebpayError) as e:
        webpay_client._check(_Resp(422, {"error_message": "Invalid value for parameter: amount"}), "create")
    assert "422" in str(e.value)
    assert "Invalid value for parameter: amount" in str(e.value)


def test_error_no_json_no_rompe():
    """Si Transbank responde algo que no es JSON, igual se reporta."""
    from ventu_pagos import webpay_client
    import pytest
    with pytest.raises(webpay_client.WebpayError) as e:
        webpay_client._check(_Resp(503, None, text="<html>Service Unavailable</html>"), "commit")
    assert "503" in str(e.value)


def test_respuesta_ok_devuelve_json():
    from ventu_pagos import webpay_client
    assert webpay_client._check(_Resp(200, {"token": "t", "url": "u"}), "create") == {"token": "t", "url": "u"}
