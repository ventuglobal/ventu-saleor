"""Tests del flujo de pago (Webpay y Saleor mockeados, sin red)."""

from __future__ import annotations

import pytest

from ventu_pagos import config, handlers, store, webpay_client


@pytest.fixture(autouse=True)
def retail_channel():
    config.WEBPAY_CHANNELS = {"retail-cl"}
    config.WEBPAY_CURRENCY = "CLP"
    yield


def _init_payload(channel="retail-cl", amount=13150, currency="CLP", tx_id="VHJhbnM6MQ=="):
    return {
        "action": {"amount": amount, "currency": currency, "actionType": "CHARGE"},
        "transaction": {"id": tx_id},
        "sourceObject": {
            "__typename": "Checkout",
            "id": "Q2hlY2tvdXQ6MQ==",
            "channel": {"slug": channel, "currencyCode": currency},
        },
    }


def _process_payload(token, tx_id="VHJhbnM6MQ=="):
    return {
        "action": {"amount": 13150, "currency": "CLP"},
        "transaction": {"id": tx_id},
        "data": {"token_ws": token},
    }


def _mock_saleor(monkeypatch):
    monkeypatch.setattr("ventu_pagos.saleor_client.update_metadata", lambda **k: None)
    monkeypatch.setattr("ventu_pagos.saleor_client.report_transaction_event", lambda **k: None)


# ───────────────────────────── initialize ─────────────────────────────

def test_initialize_retail_creates_tx_and_action_required(monkeypatch):
    monkeypatch.setattr(
        webpay_client, "create",
        lambda **k: {"token": "TOK1", "url": "https://wp/redirect"},
    )
    resp = handlers.handle_transaction_initialize(_init_payload())
    assert resp["result"] == "CHARGE_ACTION_REQUIRED"
    assert resp["data"]["webpayUrl"] == "https://wp/redirect"
    assert resp["data"]["token"] == "TOK1"
    tx = store.get_tx("TOK1")
    assert tx is not None and tx.amount == 13150 and tx.channel_slug == "retail-cl"


def test_initialize_rejects_channel_outside_list(monkeypatch):
    called = {"create": False}
    monkeypatch.setattr(webpay_client, "create",
                        lambda **k: called.__setitem__("create", True) or {"token": "x", "url": "y"})
    # retail-ar no está en WEBPAY_CHANNELS (el fixture solo habilita retail-cl).
    resp = handlers.handle_transaction_initialize(_init_payload(channel="retail-ar"))
    assert resp["result"] == "CHARGE_FAILURE"
    assert called["create"] is False  # nunca llamó a Webpay


def test_initialize_accepts_b2b_channel(monkeypatch):
    # B2B paga por Webpay sobre la orden: el canal b2b-cl debe aceptarse igual.
    config.WEBPAY_CHANNELS = {"retail-cl", "b2b-cl"}
    monkeypatch.setattr(
        webpay_client, "create",
        lambda **k: {"token": "TOKB2B", "url": "https://wp/redirect"},
    )
    resp = handlers.handle_transaction_initialize(_init_payload(channel="b2b-cl"))
    assert resp["result"] == "CHARGE_ACTION_REQUIRED"
    tx = store.get_tx("TOKB2B")
    assert tx is not None and tx.channel_slug == "b2b-cl"


def test_initialize_accepts_order_source_object(monkeypatch):
    # Orden-primero: el sourceObject es una Order, no un Checkout. La pasarela es
    # agnóstica: lee canal y persiste el id de la fuente sea cual sea su tipo.
    config.WEBPAY_CHANNELS = {"retail-cl", "b2b-cl"}
    monkeypatch.setattr(
        webpay_client, "create",
        lambda **k: {"token": "TOKORD", "url": "https://wp/redirect"},
    )
    payload = _init_payload(channel="b2b-cl")
    payload["sourceObject"] = {
        "__typename": "Order",
        "id": "T3JkZXI6MQ==",
        "channel": {"slug": "b2b-cl", "currencyCode": "CLP"},
    }
    resp = handlers.handle_transaction_initialize(payload)
    assert resp["result"] == "CHARGE_ACTION_REQUIRED"
    tx = store.get_tx("TOKORD")
    assert tx is not None and tx.checkout_id == "T3JkZXI6MQ=="


def test_initialize_rejects_non_clp_currency(monkeypatch):
    monkeypatch.setattr(webpay_client, "create", lambda **k: {"token": "x", "url": "y"})
    resp = handlers.handle_transaction_initialize(_init_payload(currency="USD"))
    assert resp["result"] == "CHARGE_FAILURE"


# ───────────────────────── process (los retornos) ─────────────────────────

def _seed_tx(token="TOK1", amount=13150):
    store.create_tx(token=token, buy_order="VR1", session_id="s1", amount=amount,
                    saleor_transaction_id="VHJhbnM6MQ==", channel_slug="retail-cl")


def test_process_approved(monkeypatch):
    _mock_saleor(monkeypatch)
    _seed_tx()
    monkeypatch.setattr(webpay_client, "commit",
                        lambda t: {"status": "AUTHORIZED", "response_code": 0, "amount": 13150})
    resp = handlers.handle_transaction_process(_process_payload("TOK1"))
    assert resp["result"] == "CHARGE_SUCCESS"
    assert store.get_tx("TOK1").status == "AUTHORIZED"


def test_process_rejected(monkeypatch):
    _mock_saleor(monkeypatch)
    _seed_tx()
    monkeypatch.setattr(webpay_client, "commit",
                        lambda t: {"status": "FAILED", "response_code": -1, "amount": 13150})
    resp = handlers.handle_transaction_process(_process_payload("TOK1"))
    assert resp["result"] == "CHARGE_FAILURE"
    assert store.get_tx("TOK1").status == "FAILED"


def test_process_without_token_is_failure_no_commit(monkeypatch):
    # Cliente anuló en Webpay o venció el formulario: no hay token_ws.
    called = {"commit": False}
    monkeypatch.setattr(webpay_client, "commit",
                        lambda t: called.__setitem__("commit", True) or {})
    resp = handlers.handle_transaction_process({"transaction": {"id": "T1"}, "data": {}})
    assert resp["result"] == "CHARGE_FAILURE"
    assert called["commit"] is False


def test_process_is_idempotent(monkeypatch):
    _mock_saleor(monkeypatch)
    _seed_tx()
    calls = {"n": 0}

    def _commit(t):
        calls["n"] += 1
        return {"status": "AUTHORIZED", "response_code": 0, "amount": 13150}

    monkeypatch.setattr(webpay_client, "commit", _commit)
    r1 = handlers.handle_transaction_process(_process_payload("TOK1"))
    r2 = handlers.handle_transaction_process(_process_payload("TOK1"))
    assert r1["result"] == r2["result"] == "CHARGE_SUCCESS"
    assert calls["n"] == 1  # segundo retorno no reconfirma


def test_amount_mismatch_triggers_refund(monkeypatch):
    _mock_saleor(monkeypatch)
    _seed_tx(amount=13150)
    refunded = {"called": False}
    monkeypatch.setattr(webpay_client, "commit",
                        lambda t: {"status": "AUTHORIZED", "response_code": 0, "amount": 99999})
    monkeypatch.setattr(webpay_client, "refund",
                        lambda t, a: refunded.__setitem__("called", True) or {"type": "REVERSED"})
    resp = handlers.handle_transaction_process(_process_payload("TOK1"))
    assert resp["result"] == "CHARGE_FAILURE"
    assert refunded["called"] is True


# ───────────────────────────── refund / cancel ─────────────────────────────

def test_refund_success(monkeypatch):
    _seed_tx()
    monkeypatch.setattr(webpay_client, "refund",
                        lambda t, a: {"type": "NULLIFIED", "response_code": 0})
    payload = {"transaction": {"pspReference": "TOK1"}, "action": {"amount": 13150}}
    resp = handlers.handle_refund(payload)
    assert resp["result"] == "REFUND_SUCCESS"


def test_refund_error_from_transbank(monkeypatch):
    _seed_tx()
    def _boom(t, a):
        raise webpay_client.WebpayError("Transbank 422: periodo excedido", status_code=422)
    monkeypatch.setattr(webpay_client, "refund", _boom)
    payload = {"transaction": {"pspReference": "TOK1"}, "action": {"amount": 13150}}
    resp = handlers.handle_refund(payload)
    assert resp["result"] == "REFUND_FAILURE"


# ───────────────────────────── reconciliador ─────────────────────────────

def test_reconcile_closes_orphan_authorized(monkeypatch):
    _mock_saleor(monkeypatch)
    _seed_tx()
    config.RECONCILE_AFTER_MIN = -1  # toda tx INITIALIZED cuenta como vieja
    monkeypatch.setattr(webpay_client, "status",
                        lambda t: {"status": "AUTHORIZED", "response_code": 0, "amount": 13150})
    res = handlers.reconcile()
    assert res["revisadas"] == 1
    assert res["autorizadas_sin_cierre"] == 1
    assert store.get_tx("TOK1").status == "AUTHORIZED"
