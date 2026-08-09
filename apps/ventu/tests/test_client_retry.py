"""El cliente no debe reintentar errores permanentes (4xx salvo 429).

Un 400 (documento GraphQL inválido, permisos) no cambia por reintentarlo, y el
backoff exponencial bloqueaba al llamador ~63 s por petición — suficiente para
dejar sin responder a toda la app.
"""

from __future__ import annotations

import pytest

from ventu import saleor_client as sc


class _Resp:
    def __init__(self, code, text="boom"):
        self.status_code = code
        self.text = text

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"status {self.status_code}")

    def json(self):
        return {"data": {}}


@pytest.fixture(autouse=True)
def _cfg(monkeypatch):
    monkeypatch.setattr(sc.config, "SALEOR_API_URL", "http://saleor/graphql/")
    monkeypatch.setattr(sc.config, "SALEOR_AUTH_TOKEN", "tok")
    monkeypatch.setattr(sc.time, "sleep", lambda *_: None)


def test_400_no_reintenta(monkeypatch):
    calls = []
    monkeypatch.setattr(sc.httpx, "post", lambda *a, **k: (calls.append(1), _Resp(400))[1])
    with pytest.raises(sc.SaleorQueryError):
        sc.gql("query { x }")
    assert len(calls) == 1        # una sola vez, sin backoff


def test_429_si_reintenta(monkeypatch):
    calls = []
    monkeypatch.setattr(sc.httpx, "post", lambda *a, **k: (calls.append(1), _Resp(429))[1])
    with pytest.raises(sc.SaleorTransportError):
        sc.gql("query { x }")
    assert len(calls) == sc.MAX_RETRIES


def test_503_si_reintenta(monkeypatch):
    calls = []
    monkeypatch.setattr(sc.httpx, "post", lambda *a, **k: (calls.append(1), _Resp(503))[1])
    with pytest.raises(sc.SaleorTransportError):
        sc.gql("query { x }")
    assert len(calls) == sc.MAX_RETRIES
