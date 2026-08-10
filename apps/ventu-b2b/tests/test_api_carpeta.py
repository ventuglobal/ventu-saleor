"""Tests del endpoint que recibe la Carpeta Tributaria.

Usan el cliente de pruebas de FastAPI, así que ejercitan la ruta completa
—validación, códigos de estado y forma de la respuesta— sin salir a la red.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from ventu_b2b import main
from ventu_b2b.company.models import Company
from ventu_b2b.credito import estados as st

AHORA = "2026-08-10T04:00:00Z"


@pytest.fixture
def cliente():
    return TestClient(main.app)


def _company(**kw):
    base = dict(rut="76.543.210-3", razon_social="Comercial Ventu SpA")
    base.update(kw)
    return Company(**base)


class _Maxxa:
    """Doble del cliente de Maxxa: registra lo que recibiría."""

    def __init__(self, referencia="MX-1", falla=False):
        self.referencia = referencia
        self.falla = falla
        self.recibido = []

    def enviar_carpeta(self, rut, documento):
        if self.falla:
            raise ConnectionError("timeout")
        self.recibido.append((rut, len(documento)))
        return self.referencia


def _archivo(contenido=b"%PDF-carpeta-tributaria"):
    return {"archivo": ("carpeta.pdf", contenido, "application/pdf")}


def _datos():
    return {"user_id": "VXNlcjo1", "ahora": AHORA}


# ───────────────────────── camino feliz ─────────────────────────

def test_entrega_la_carpeta_y_devuelve_la_referencia(monkeypatch, cliente):
    maxxa = _Maxxa()
    monkeypatch.setattr(main, "maxxa", maxxa)
    monkeypatch.setattr(main.company_svc, "obtener_de_usuario",
                        lambda uid: _company(credito_estado=st.PENDIENTE))

    r = cliente.post("/credito/carpeta", data=_datos(), files=_archivo())
    assert r.status_code == 200
    assert r.json()["referencia"] == "MX-1"
    # El RUT llega normalizado, no como lo escribió el cliente.
    assert maxxa.recibido == [("76543210-3", len(b"%PDF-carpeta-tributaria"))]


# ───────────────────────── casos que protegen el dato ─────────────────────────

def test_sin_solicitud_en_curso_no_se_acepta(monkeypatch, cliente):
    """Aceptar un historial tributario sin solicitud abierta significaría
    custodiarlo sin motivo."""
    maxxa = _Maxxa()
    monkeypatch.setattr(main, "maxxa", maxxa)
    monkeypatch.setattr(main.company_svc, "obtener_de_usuario",
                        lambda uid: _company(credito_estado=st.SIN_SOLICITUD))

    r = cliente.post("/credito/carpeta", data=_datos(), files=_archivo())
    assert r.status_code == 409
    assert maxxa.recibido == [], "no debe haber salido nada"


def test_sin_integracion_configurada_se_rechaza(monkeypatch, cliente):
    """Recibir un documento que no se puede entregar sería custodiarlo sin
    propósito, así que el endpoint se declara no disponible."""
    monkeypatch.setattr(main, "maxxa", None)
    monkeypatch.setattr(main.company_svc, "obtener_de_usuario",
                        lambda uid: _company(credito_estado=st.PENDIENTE))

    r = cliente.post("/credito/carpeta", data=_datos(), files=_archivo())
    assert r.status_code == 503


def test_carpeta_demasiado_grande(monkeypatch, cliente):
    monkeypatch.setattr(main, "maxxa", _Maxxa())
    monkeypatch.setattr(main.config, "CARPETA_MAX_BYTES", 10)
    monkeypatch.setattr(main.company_svc, "obtener_de_usuario",
                        lambda uid: _company(credito_estado=st.PENDIENTE))

    r = cliente.post("/credito/carpeta", data=_datos(), files=_archivo(b"x" * 500))
    assert r.status_code == 413


def test_usuario_sin_empresa(monkeypatch, cliente):
    monkeypatch.setattr(main, "maxxa", _Maxxa())
    monkeypatch.setattr(main.company_svc, "obtener_de_usuario", lambda uid: None)

    r = cliente.post("/credito/carpeta", data=_datos(), files=_archivo())
    assert r.status_code == 404


def test_fallo_de_maxxa_se_distingue_de_un_error_del_cliente(monkeypatch, cliente):
    """502 y no 4xx: el fallo es del tercero. El cliente debe saber que puede
    reintentar sin cambiar nada de lo que envió."""
    monkeypatch.setattr(main, "maxxa", _Maxxa(falla=True))
    monkeypatch.setattr(main.company_svc, "obtener_de_usuario",
                        lambda uid: _company(credito_estado=st.PENDIENTE))

    r = cliente.post("/credito/carpeta", data=_datos(), files=_archivo())
    assert r.status_code == 502


def test_carpeta_vacia(monkeypatch, cliente):
    monkeypatch.setattr(main, "maxxa", _Maxxa())
    monkeypatch.setattr(main.company_svc, "obtener_de_usuario",
                        lambda uid: _company(credito_estado=st.PENDIENTE))

    r = cliente.post("/credito/carpeta", data=_datos(), files=_archivo(b""))
    assert r.status_code == 422
