"""Configuración común de los tests.

Cada test parte con la API abierta a pedido (sin tokens y con
B2B_AUTH_ABIERTA) y con la red cortada: si un test olvida simular Saleor, falla
en vez de salir a internet. Los tests de acceso fijan su propia configuración.
"""

from __future__ import annotations

import pytest

from ventu_b2b import config, saleor_client


@pytest.fixture(autouse=True)
def _entorno_aislado(monkeypatch):
    monkeypatch.setattr(config, "SERVICE_TOKEN", "")
    monkeypatch.setattr(config, "STAFF_TOKEN", "")
    monkeypatch.setattr(config, "AUTH_ABIERTA", True)
    monkeypatch.setattr(config, "CANALES", ["b2b-cl"])
    monkeypatch.setattr(config, "NIVELES_PERMITIDOS", ["retail-cl", "b2b-cl"])
    monkeypatch.setattr(config, "INSTRUCCIONES_TRANSFERENCIA", None)
    monkeypatch.setattr(config, "PUBLIC_URL", "")
    monkeypatch.setattr(config, "MARKUP_MINIMO", 0.0)
    monkeypatch.setattr(config, "CORREO_URL", "")
    monkeypatch.setattr(config, "CORREO_SERVICE_TOKEN", "")

    def sin_red(*a, **kw):
        raise AssertionError("un test intentó salir a la red")

    # Es el mismo módulo httpx para Saleor y para Ventu Correo.
    monkeypatch.setattr(saleor_client.httpx, "post", sin_red)
