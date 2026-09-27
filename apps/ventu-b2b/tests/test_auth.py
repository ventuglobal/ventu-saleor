"""Acceso a la API: quién puede llamar qué.

El servicio es alcanzable desde internet y actúa con permisos de app sobre
Saleor. Estos tests fijan la matriz completa para que una ruta nueva no nazca
abierta por olvido.
"""

from __future__ import annotations

import pytest
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient

from ventu_b2b import config, main
from ventu_b2b.company.models import Company

USUARIO = "VXNlcjo1"
SERVICIO = "tok-servicio-de-prueba"
STAFF = "tok-staff-de-prueba"


@pytest.fixture
def cliente():
    return TestClient(main.app)


@pytest.fixture(autouse=True)
def _sin_saleor(monkeypatch):
    """Las rutas que se ejercitan responden sin tocar Saleor."""
    monkeypatch.setattr(main.company_svc, "obtener_de_usuario",
                        lambda uid: Company(rut="76.543.210-3", razon_social="Comercial Ventu SpA"))
    monkeypatch.setattr(main.company_svc, "buscar_por_rut", lambda rut: None)


def _tokens(monkeypatch, servicio="", staff="", abierta=False):
    monkeypatch.setattr(config, "SERVICE_TOKEN", servicio)
    monkeypatch.setattr(config, "STAFF_TOKEN", staff)
    monkeypatch.setattr(config, "AUTH_ABIERTA", abierta)


def _bearer(token):
    return {"Authorization": f"Bearer {token}"}


def _ruta_cliente(cliente, headers=None):
    return cliente.get(f"/company/de-usuario/{USUARIO}", headers=headers or {})


def _ruta_staff(cliente, headers=None):
    return cliente.get("/company/por-rut/76543210-3", headers=headers or {})


# ───────────────── sin tokens: cerrado salvo que se pida ─────────────────

def test_sin_tokens_todo_queda_cerrado(monkeypatch, cliente):
    """Un entorno nuevo, un servicio clonado o una variable renombrada no
    deben dejar la API abierta en silencio."""
    _tokens(monkeypatch)
    for r in (_ruta_cliente(cliente), _ruta_staff(cliente),
              cliente.patch(f"/company/{USUARIO}", json={"nivel_precio": "b2b-cl"})):
        assert r.status_code == 503
        assert r.json()["detail"] == "la API no tiene credenciales configuradas"


def test_sin_tokens_no_se_publica_la_documentacion(monkeypatch, cliente):
    _tokens(monkeypatch)
    assert cliente.get("/openapi.json").status_code == 404


def test_sin_tokens_y_con_b2b_auth_abierta_queda_abierto(monkeypatch, cliente):
    """Solo para desarrollo local, y hay que pedirlo."""
    _tokens(monkeypatch, abierta=True)
    assert _ruta_cliente(cliente).status_code == 200
    assert _ruta_staff(cliente).status_code == 200
    assert cliente.get("/openapi.json").status_code == 200


def test_con_tokens_b2b_auth_abierta_no_abre_nada(monkeypatch, cliente):
    _tokens(monkeypatch, servicio=SERVICIO, staff=STAFF, abierta=True)
    assert _ruta_cliente(cliente).status_code == 401
    assert _ruta_staff(cliente).status_code == 401
    assert cliente.get("/openapi.json").status_code == 404


# ───────────────── rutas del cliente ─────────────────

def test_ruta_de_cliente_sin_token_es_401(monkeypatch, cliente):
    _tokens(monkeypatch, servicio=SERVICIO, staff=STAFF)
    r = _ruta_cliente(cliente)
    assert r.status_code == 401
    assert r.json()["detail"] == "token de acceso inválido o ausente"
    assert r.headers["www-authenticate"] == "Bearer"


def test_ruta_de_cliente_con_el_token_de_servicio(monkeypatch, cliente):
    _tokens(monkeypatch, servicio=SERVICIO, staff=STAFF)
    assert _ruta_cliente(cliente, _bearer(SERVICIO)).status_code == 200


def test_el_esquema_bearer_no_distingue_mayusculas(monkeypatch, cliente):
    _tokens(monkeypatch, servicio=SERVICIO)
    r = _ruta_cliente(cliente, {"Authorization": f"bearer {SERVICIO}"})
    assert r.status_code == 200


@pytest.mark.parametrize("encabezado", [
    f"Bearer {SERVICIO}x",
    f"Bearer {SERVICIO[:-1]}",
    SERVICIO,  # sin esquema
    "Bearer ",
    "Basic dXNlcjpwYXNz",
])
def test_ruta_de_cliente_con_token_incorrecto_es_401(monkeypatch, cliente, encabezado):
    _tokens(monkeypatch, servicio=SERVICIO, staff=STAFF)
    assert _ruta_cliente(cliente, {"Authorization": encabezado}).status_code == 401


def test_el_staff_tambien_puede_usar_las_rutas_del_cliente(monkeypatch, cliente):
    _tokens(monkeypatch, servicio=SERVICIO, staff=STAFF)
    assert _ruta_cliente(cliente, _bearer(STAFF)).status_code == 200


def test_solo_con_token_de_staff_la_ruta_de_cliente_lo_exige(monkeypatch, cliente):
    _tokens(monkeypatch, staff=STAFF)
    assert _ruta_cliente(cliente).status_code == 401
    assert _ruta_cliente(cliente, _bearer(STAFF)).status_code == 200


# ───────────────── rutas de staff ─────────────────

def test_ruta_de_staff_rechaza_el_token_de_servicio(monkeypatch, cliente):
    """Filtrarse el token del storefront no debe permitir fijar condiciones
    comerciales ni aprobarse crédito."""
    _tokens(monkeypatch, servicio=SERVICIO, staff=STAFF)
    assert _ruta_staff(cliente, _bearer(SERVICIO)).status_code == 401


def test_ruta_de_staff_con_su_token(monkeypatch, cliente):
    _tokens(monkeypatch, servicio=SERVICIO, staff=STAFF)
    assert _ruta_staff(cliente, _bearer(STAFF)).status_code == 200


def test_con_solo_el_token_de_servicio_staff_queda_cerrado(monkeypatch, cliente):
    """Configurar solo uno no debe dejar el otro lado abierto por omisión."""
    _tokens(monkeypatch, servicio=SERVICIO)
    assert _ruta_staff(cliente).status_code == 401
    assert _ruta_staff(cliente, _bearer(SERVICIO)).status_code == 401
    assert _ruta_staff(cliente, {"Authorization": "Bearer "}).status_code == 401


def test_el_token_se_exige_antes_de_validar_el_cuerpo(monkeypatch, cliente):
    """Sin token no se responde 422: describir el cuerpo esperado a un anónimo
    es darle el formulario."""
    _tokens(monkeypatch, servicio=SERVICIO, staff=STAFF)
    assert cliente.patch(f"/company/{USUARIO}", json={"x": 1}).status_code == 401
    assert cliente.post("/pedido", json={}).status_code == 401


@pytest.mark.parametrize("metodo,ruta", [
    ("patch", f"/company/{USUARIO}"),
    ("post", "/credito/resolver"),
    ("post", "/cart"),
    ("get", "/company/por-rut/76543210-3"),
    ("get", "/company/pendientes"),
])
def test_rutas_de_staff_rechazan_el_token_de_servicio(monkeypatch, cliente, metodo, ruta):
    _tokens(monkeypatch, servicio=SERVICIO, staff=STAFF)
    r = getattr(cliente, metodo)(ruta, headers=_bearer(SERVICIO),
                                 **({} if metodo == "get" else {"json": {}}))
    assert r.status_code == 401


# ───────────────── lo que queda siempre abierto ─────────────────

@pytest.mark.parametrize("con_tokens", [True, False])
def test_health_manifest_y_register_quedan_abiertos(monkeypatch, cliente, con_tokens):
    """Saleor llama a manifest y register sin credenciales nuestras, y el
    healthcheck de Railway tampoco las tiene. Tampoco se cierran sin tokens:
    un healthcheck caído escondería la causa real."""
    if con_tokens:
        _tokens(monkeypatch, servicio=SERVICIO, staff=STAFF)
    else:
        _tokens(monkeypatch)
    assert cliente.get("/health").status_code == 200
    assert cliente.get("/manifest").status_code == 200
    assert cliente.post("/register", json={"auth_token": "tok-instalacion-de-prueba"}).status_code == 200


@pytest.mark.parametrize("ruta", ["/docs", "/redoc", "/openapi.json"])
def test_con_token_la_documentacion_no_se_publica(monkeypatch, cliente, ruta):
    _tokens(monkeypatch, servicio=SERVICIO)
    assert cliente.get(ruta).status_code == 404


# ───────────────── ninguna ruta nace abierta ─────────────────

_ABIERTAS = {"/health", "/manifest", "/register"}
_DE_STAFF = {
    ("GET", "/company/por-rut/{rut_libre}"),
    ("GET", "/company/pendientes"),
    ("PATCH", "/company/{user_id}"),
    ("POST", "/credito/resolver"),
    ("POST", "/cart"),
}


def _rutas_propias():
    for ruta in main.app.routes:
        if isinstance(ruta, APIRoute) and ruta.path not in _ABIERTAS:
            for metodo in ruta.methods:
                yield metodo, ruta


def test_toda_ruta_con_datos_exige_token():
    for metodo, ruta in _rutas_propias():
        guardias = {d.call for d in ruta.dependant.dependencies}
        esperado = (main._requiere_staff if (metodo, ruta.path) in _DE_STAFF
                    else main._requiere_servicio)
        assert esperado in guardias, f"{metodo} {ruta.path} no exige el token esperado"


def test_toda_ruta_que_llama_a_saleor_es_sincrona():
    """Con `async def` una consulta lenta a Saleor (httpx síncrono) congelaría
    el event loop y con él a todas las demás rutas, incluido /health."""
    import inspect

    for _, ruta in _rutas_propias():
        assert not inspect.iscoroutinefunction(ruta.endpoint), ruta.path


def test_abierta_a_pedido_se_avisa_al_arrancar(monkeypatch, caplog):
    _tokens(monkeypatch, abierta=True)
    main._avisar_si_abierto()
    assert "ABIERTA" in caplog.text


def test_sin_tokens_se_avisa_que_todo_responde_503(monkeypatch, caplog):
    _tokens(monkeypatch)
    main._avisar_si_abierto()
    assert "503" in caplog.text
    assert "ABIERTA" not in caplog.text


def test_sin_token_de_staff_se_avisa_que_esas_rutas_quedan_cerradas(monkeypatch, caplog):
    _tokens(monkeypatch, servicio=SERVICIO)
    main._avisar_si_abierto()
    assert "B2B_STAFF_TOKEN" in caplog.text
    assert SERVICIO not in caplog.text
