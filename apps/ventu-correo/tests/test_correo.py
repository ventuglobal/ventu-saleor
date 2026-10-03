import base64
import json

import httpx
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient
from jwt import api_jws
from jwt.algorithms import RSAAlgorithm

from ventu_correo import config, main, plantillas, resend, saleor_firma

_CLAVE = rsa.generate_private_key(public_exponent=65537, key_size=2048)
_OTRA = rsa.generate_private_key(public_exponent=65537, key_size=2048)


def _jwks(clave=_CLAVE, kid="k1"):
    jwk = json.loads(RSAAlgorithm.to_jwk(clave.public_key()))
    jwk["kid"] = kid
    return {"keys": [jwk]}


def _firmar(cuerpo: bytes, clave=_CLAVE, kid="k1") -> str:
    # Igual que saleor/core/jwt_manager.py: jws_encode.
    return api_jws.encode(cuerpo, key=clave, algorithm="RS256",
                          headers={"kid": kid, "crit": ["b64"]}, is_payload_detached=True)


@pytest.fixture(autouse=True)
def _config(monkeypatch):
    monkeypatch.setattr(config, "RESEND_API_KEY", "re_prueba")
    monkeypatch.setattr(config, "MAIL_FROM", "Tienda <no-responder@ejemplo.cl>")
    monkeypatch.setattr(config, "MAIL_REPLY_TO", "")
    monkeypatch.setattr(config, "SERVICE_TOKEN", "secreto")
    monkeypatch.setattr(config, "AUTH_ABIERTA", False)
    monkeypatch.setattr(saleor_firma, "claves", saleor_firma.ClavesSaleor(obtener=_jwks))


@pytest.fixture
def enviados(monkeypatch):
    """Reemplaza el envío real: guarda lo que se habría mandado."""
    lista = []

    def falso(correo, clave_idempotencia=None, cliente=None):
        lista.append((correo, clave_idempotencia))
        return resend.Resultado(True, id="msg_1")

    monkeypatch.setattr(resend, "enviar", falso)
    return lista


cliente = TestClient(main.app)


# ── resend ──

def _transporte(respuesta, capturas):
    def manejar(req):
        capturas.append(req)
        return respuesta
    return httpx.Client(transport=httpx.MockTransport(manejar))


def test_resend_envia_cuerpo_y_cabeceras():
    capturas = []
    c = _transporte(httpx.Response(200, json={"id": "abc"}), capturas)
    correo = resend.Correo(para=["a@b.cl"], asunto="Hola", html="<p>x</p>", texto="x",
                           adjuntos=[resend.Adjunto("f.pdf", b"%PDF", "application/pdf")],
                           etiqueta="pedido b2b")
    r = resend.enviar(correo, clave_idempotencia="k-1", cliente=c)
    assert r.enviado and r.id == "abc"
    req = capturas[0]
    assert req.headers["authorization"] == "Bearer re_prueba"
    assert req.headers["idempotency-key"] == "k-1"
    cuerpo = json.loads(req.content)
    assert cuerpo["from"] == config.MAIL_FROM and cuerpo["to"] == ["a@b.cl"]
    assert cuerpo["attachments"][0]["content"] == base64.b64encode(b"%PDF").decode()
    assert cuerpo["tags"] == [{"name": "tipo", "value": "pedido_b2b"}]
    assert "reply_to" not in cuerpo


def test_resend_no_lanza_ante_error_ni_red():
    c = _transporte(httpx.Response(422, json={"message": "dominio no verificado"}), [])
    r = resend.enviar(resend.Correo(["a@b.cl"], "x", "y"), cliente=c)
    assert not r.enviado and "422" in r.error and r.configurado

    def caer(req):
        raise httpx.ConnectError("sin red")
    c = httpx.Client(transport=httpx.MockTransport(caer))
    r = resend.enviar(resend.Correo(["a@b.cl"], "x", "y"), cliente=c)
    assert not r.enviado and r.error.startswith("red")


def test_resend_sin_configurar_no_llama(monkeypatch):
    monkeypatch.setattr(config, "MAIL_FROM", "")
    capturas = []
    r = resend.enviar(resend.Correo(["a@b.cl"], "x", "y"),
                      cliente=_transporte(httpx.Response(200), capturas))
    assert not r.enviado and not r.configurado and capturas == []


def test_ocultar():
    assert resend.ocultar("ignacio@ejemplo.cl") == "ig***@ejemplo.cl"


# ── /enviar ──

def test_enviar_exige_token(enviados, monkeypatch):
    cuerpo = {"para": "a@b.cl", "asunto": "x", "html": "<p>y</p>"}
    assert cliente.post("/enviar", json=cuerpo).status_code == 401
    assert cliente.post("/enviar", json=cuerpo,
                        headers={"Authorization": "Bearer otro"}).status_code == 401
    monkeypatch.setattr(config, "SERVICE_TOKEN", "")
    assert cliente.post("/enviar", json=cuerpo,
                        headers={"Authorization": "Bearer "}).status_code == 503
    assert enviados == []


def test_enviar_ok(enviados):
    adj = base64.b64encode(b"hola").decode()
    r = cliente.post("/enviar", headers={"Authorization": "Bearer secreto"}, json={
        "para": "a@b.cl, c@d.cl", "asunto": "Pedido", "html": "<p>y</p>",
        "adjuntos": [{"nombre": "a.txt", "contenido_b64": adj}],
        "clave_idempotencia": "pedido-22"})
    assert r.status_code == 200 and r.json()["enviado"]
    correo, clave = enviados[0]
    assert correo.para == ["a@b.cl", "c@d.cl"] and correo.adjuntos[0].contenido == b"hola"
    assert clave == "pedido-22"


def test_enviar_valida(enviados):
    h = {"Authorization": "Bearer secreto"}
    assert cliente.post("/enviar", headers=h, json={
        "para": "sin-arroba", "asunto": "x", "html": "y"}).status_code == 422
    assert cliente.post("/enviar", headers=h, json={
        "para": "a@b.cl", "asunto": "x", "html": "y",
        "adjuntos": [{"nombre": "a", "contenido_b64": "no es base64!"}]}).status_code == 422
    assert enviados == []


def test_enviar_informa_fallo(monkeypatch):
    monkeypatch.setattr(resend, "enviar",
                        lambda *a, **k: resend.Resultado(False, error="no-configurado",
                                                         configurado=False))
    r = cliente.post("/enviar", headers={"Authorization": "Bearer secreto"},
                     json={"para": "a@b.cl", "asunto": "x", "html": "y"})
    assert r.status_code == 503 and r.json()["enviado"] is False


# ── firma de Saleor ──

def test_firma_valida_y_alterada():
    cuerpo = b'{"token":"t"}'
    firma = _firmar(cuerpo)
    assert saleor_firma.verificar(cuerpo, firma)
    assert not saleor_firma.verificar(b'{"token":"u"}', firma)
    assert not saleor_firma.verificar(cuerpo, None)
    assert not saleor_firma.verificar(cuerpo, "basura")


def test_firma_de_otra_instancia_no_verifica():
    cuerpo = b"{}"
    assert not saleor_firma.verificar(cuerpo, _firmar(cuerpo, clave=_OTRA))
    assert not saleor_firma.verificar(cuerpo, _firmar(cuerpo, clave=_OTRA, kid="otro"))


def test_claves_se_refrescan_al_rotar():
    estado = {"jwks": _jwks(kid="viejo")}
    almacen = saleor_firma.ClavesSaleor(obtener=lambda: estado["jwks"])
    assert saleor_firma.verificar(b"{}", _firmar(b"{}", kid="viejo"), almacen)
    estado["jwks"] = _jwks(kid="nuevo")
    almacen._ultima -= 3600  # pasó el freno de refresco
    assert saleor_firma.verificar(b"{}", _firmar(b"{}", kid="nuevo"), almacen)


# ── webhooks ──

def _evento(tipo="account_confirmation_requested", **cambios):
    datos = {"redirectUrl": "https://tienda.cl/es/b2b-cl/login?modo=confirmar",
             "token": "tok-123", "user": {"email": "cliente@ejemplo.cl", "firstName": "Ana"},
             "channel": {"slug": "b2b-cl"}, "shop": {"name": "Ventu"}}
    datos.update(cambios)
    cuerpo = json.dumps(datos).encode()
    return cuerpo, {"Saleor-Event": tipo, "Saleor-Signature": _firmar(cuerpo),
                    "Content-Type": "application/json"}


def test_webhook_confirmacion(enviados):
    cuerpo, h = _evento()
    r = cliente.post("/webhooks/saleor", content=cuerpo, headers=h)
    assert r.status_code == 200 and r.json()["resultado"] == "enviado"
    correo, clave = enviados[0]
    assert correo.para == ["cliente@ejemplo.cl"]
    assert correo.asunto == "Confirma tu cuenta en Ventu"
    url = "https://tienda.cl/es/b2b-cl/login?modo=confirmar&amp;email=cliente%40ejemplo.cl&amp;token=tok-123"
    assert url in correo.html and "Hola Ana," in correo.html
    assert clave.startswith("confirmar-cuenta-") and "tok-123" not in clave


def test_webhook_clave_estable_entre_reintentos(enviados):
    for _ in range(2):
        cuerpo, h = _evento()
        cliente.post("/webhooks/saleor", content=cuerpo, headers=h)
    assert enviados[0][1] == enviados[1][1]


def test_webhook_contrasena(enviados):
    cuerpo, h = _evento("account_set_password_requested", shop={"name": ""})
    assert cliente.post("/webhooks/saleor", content=cuerpo, headers=h).status_code == 200
    assert enviados[0][0].asunto == "Crea tu contraseña en la tienda"


def test_webhook_sin_firma_o_alterado(enviados):
    cuerpo, h = _evento()
    sin = {k: v for k, v in h.items() if k != "Saleor-Signature"}
    assert cliente.post("/webhooks/saleor", content=cuerpo, headers=sin).status_code == 401
    assert cliente.post("/webhooks/saleor", content=cuerpo.replace(b"tok-123", b"tok-999"),
                        headers=h).status_code == 401
    assert enviados == []


def test_webhook_otro_evento_se_ignora(enviados):
    cuerpo, h = _evento("order_created")
    assert cliente.post("/webhooks/saleor", content=cuerpo, headers=h).json()["resultado"] == "ignorado"
    assert enviados == []


def test_webhook_incompleto_no_reintenta(enviados):
    cuerpo, h = _evento(token=None)
    r = cliente.post("/webhooks/saleor", content=cuerpo, headers=h)
    assert r.status_code == 200 and r.json()["resultado"] == "incompleto"


def test_webhook_fallo_de_envio_pide_reintento(monkeypatch):
    monkeypatch.setattr(resend, "enviar", lambda *a, **k: resend.Resultado(False, error="x"))
    cuerpo, h = _evento()
    assert cliente.post("/webhooks/saleor", content=cuerpo, headers=h).status_code == 503


# ── plantillas y manifest ──

def test_plantilla_escapa_datos_del_usuario():
    c = plantillas.confirmar_cuenta("https://t.cl/?a=1", "<script>x</script>", "T&C")
    assert "<script>" not in c.html and "&lt;script&gt;" in c.html
    assert "T&amp;C" in c.html and "https://t.cl/?a=1" in c.texto


def test_url_con_token_conserva_query():
    assert main.url_con_token("https://t.cl/x?a=1", "a+b@c.cl", "t/1") == \
        "https://t.cl/x?a=1&email=a%2Bb%40c.cl&token=t%2F1"


def test_manifest():
    m = cliente.get("/manifest", headers={"x-forwarded-proto": "https"}).json()
    assert m["permissions"] == ["MANAGE_USERS"]
    w = m["webhooks"][0]
    assert w["targetUrl"].startswith("https://") and w["targetUrl"].endswith("/webhooks/saleor")
    assert set(w["asyncEvents"]) == {"ACCOUNT_CONFIRMATION_REQUESTED",
                                     "ACCOUNT_SET_PASSWORD_REQUESTED"}
    assert "... on AccountConfirmationRequested" in w["query"]


def test_health_no_expone_valores():
    assert "re_prueba" not in cliente.get("/health").text
