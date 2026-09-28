"""Fallos de Saleor: cómo se reintentan y cómo se responden.

Una lectura puede repetirse; una mutación no, porque tras un timeout no se sabe
si ocurrió. Y un fallo de Saleor es un 502/504 con detalle en castellano, no un
500 con la traza.
"""

from __future__ import annotations

import httpx
import pytest
from fastapi.testclient import TestClient

from ventu_b2b import config, main, saleor_client
from ventu_b2b.company import service as company_service
from ventu_b2b.pedido import medios, service as pedido_svc
from ventu_b2b.saleor_client import (SaleorQueryError, SaleorRespuestaError,
                                     SaleorTimeoutError, SaleorTransportError)

URL = "https://saleor.invalid/graphql/"


@pytest.fixture
def cliente():
    # Sin `raise_server_exceptions` un 500 llega como respuesta y el test lo ve.
    return TestClient(main.app, raise_server_exceptions=False)


@pytest.fixture
def red(monkeypatch):
    """Sustituye la red por una secuencia de respuestas o excepciones."""
    monkeypatch.setattr(config, "SALEOR_API_URL", URL)
    monkeypatch.setattr(config, "SALEOR_AUTH_TOKEN", "tok-app-de-prueba")
    monkeypatch.setattr(saleor_client.time, "sleep", lambda s: None)

    def instalar(*resultados):
        llamadas = []

        def post(url, **kw):
            llamadas.append(kw)
            r = resultados[min(len(llamadas), len(resultados)) - 1]
            if isinstance(r, Exception):
                raise r
            return r
        monkeypatch.setattr(saleor_client.httpx, "post", post)
        return llamadas
    return instalar


def _resp(status, cuerpo=None):
    return httpx.Response(status, json=cuerpo if cuerpo is not None else {},
                          request=httpx.Request("POST", URL))


_TIMEOUT = httpx.ReadTimeout("lento")


# ───────────────── reintentos del cliente ─────────────────

def test_una_lectura_se_reintenta_dos_veces(red):
    llamadas = red(_TIMEOUT)
    with pytest.raises(SaleorTimeoutError):
        saleor_client.gql("query { shop { name } }")
    assert len(llamadas) == 1 + saleor_client.MAX_RETRIES == 3


def test_una_lectura_se_recupera_si_el_reintento_funciona(red):
    llamadas = red(_resp(503), _resp(200, {"data": {"shop": {"name": "Ventu"}}}))
    assert saleor_client.gql("query { shop { name } }")["data"]["shop"]["name"] == "Ventu"
    assert len(llamadas) == 2


def test_una_mutacion_no_se_reintenta(red):
    llamadas = red(_TIMEOUT)
    with pytest.raises(SaleorTimeoutError):
        saleor_client.gql("mutation { tokenRefresh { token } }")
    assert len(llamadas) == 1


def test_crear_la_orden_nunca_se_reintenta(red):
    """Repetir `orderCreateFromCheckout` tras un timeout puede cerrar dos
    pedidos por el mismo carrito."""
    llamadas = red(_TIMEOUT)
    with pytest.raises(SaleorTimeoutError):
        pedido_svc.crear("Q2hlY2tvdXQ6MQ==", medios.TRANSFERENCIA, tiene_credito=False)
    assert len(llamadas) == 1


def test_crear_la_orden_no_se_reintenta_ni_ante_un_503(red):
    llamadas = red(_resp(503))
    with pytest.raises(SaleorTransportError):
        pedido_svc.crear("Q2hlY2tvdXQ6MQ==", medios.TRANSFERENCIA, tiene_credito=False)
    assert len(llamadas) == 1


def test_la_mutacion_se_detecta_aunque_el_documento_empiece_con_saltos(red):
    llamadas = red(_TIMEOUT)
    with pytest.raises(SaleorTimeoutError):
        saleor_client.gql("\n   mutation($id: ID!) { x(id: $id) { id } }", {"id": "1"})
    assert len(llamadas) == 1


def test_reintentar_explicito_manda(red):
    llamadas = red(_TIMEOUT)
    with pytest.raises(SaleorTimeoutError):
        saleor_client.gql("query { shop { name } }", reintentar=False)
    assert len(llamadas) == 1


def test_un_4xx_no_se_reintenta(red):
    """Documento inválido o permisos: repetirlo no cambia la respuesta."""
    llamadas = red(_resp(400, {"errors": [{"message": "bad"}]}))
    with pytest.raises(SaleorQueryError):
        saleor_client.gql("query { shop { name } }")
    assert len(llamadas) == 1


def test_un_429_si_se_reintenta(red):
    llamadas = red(_resp(429))
    with pytest.raises(SaleorTransportError):
        saleor_client.gql("query { shop { name } }")
    assert len(llamadas) == 3


def test_el_timeout_por_defecto_es_de_10_segundos(red):
    llamadas = red(_resp(200, {"data": {}}))
    saleor_client.gql("query { shop { name } }")
    assert llamadas[0]["timeout"] == 10


def test_un_error_de_conexion_no_es_timeout(red):
    red(httpx.ConnectError("rechazada"))
    with pytest.raises(SaleorTransportError) as info:
        saleor_client.gql("query { shop { name } }")
    assert not isinstance(info.value, SaleorTimeoutError)


# ───────────────── cómo se responde ─────────────────

def _usuario_falla(monkeypatch, exc):
    def gql(*a, **kw):
        raise exc
    monkeypatch.setattr(company_service, "gql", gql)


def test_saleor_caido_es_502_en_castellano(monkeypatch, cliente):
    _usuario_falla(monkeypatch, SaleorTransportError("connection refused 10.0.0.1"))
    r = cliente.get("/company/de-usuario/VXNlcjo1")
    assert r.status_code == 502
    assert r.json()["detail"].startswith("no se pudo completar la operación con Saleor")
    assert "10.0.0.1" not in r.text, "el detalle interno queda en el log"


def test_saleor_lento_es_504(monkeypatch, cliente):
    _usuario_falla(monkeypatch, SaleorTimeoutError("sin respuesta en 10s"))
    r = cliente.get("/company/de-usuario/VXNlcjo1")
    assert r.status_code == 504
    assert "no respondió a tiempo" in r.json()["detail"]


def test_errores_de_permisos_son_502_y_no_500(monkeypatch, cliente):
    """Antes un `errors` a nivel documento se trataba como «sin empresa»."""
    monkeypatch.setattr(company_service, "gql", lambda *a, **kw: {
        "errors": [{"message": "You need one of the following permissions: MANAGE_USERS"}],
        "data": {"user": None}})
    r = cliente.get("/company/de-usuario/VXNlcjo1")
    assert r.status_code == 502
    assert "MANAGE_USERS" not in r.text


def test_la_lectura_del_usuario_no_confunde_error_con_ausencia(monkeypatch):
    monkeypatch.setattr(company_service, "gql", lambda *a, **kw: {
        "errors": [{"message": "boom"}], "data": {"user": None}})
    with pytest.raises(SaleorRespuestaError):
        company_service.obtener_de_usuario("VXNlcjo1")


def test_el_log_no_lleva_el_user_id(monkeypatch, cliente, caplog):
    """Se registra la plantilla de la ruta, no la URL con el identificador."""
    _usuario_falla(monkeypatch, SaleorTransportError("caído"))
    cliente.get("/company/de-usuario/VXNlcjo1")
    assert "/company/de-usuario/{user_id}" in caplog.text
    assert "VXNlcjo1" not in caplog.text


def test_los_tests_no_salen_a_la_red():
    """Guardia de conftest: si algo llegara a httpx sin simular, falla fuerte."""
    with pytest.raises(AssertionError, match="red"):
        saleor_client.httpx.post(URL)
