"""Alta y cambios de la empresa por la API.

El alta la hace el cliente y siempre en el nivel por defecto; las condiciones
comerciales las cambia el staff, con registro de quién y cuándo.
"""

from __future__ import annotations

import json

import httpx
import pytest
from fastapi.testclient import TestClient

from ventu_b2b import avisos, config, main
from ventu_b2b.company import models
from ventu_b2b.company import service as company_service
from ventu_b2b.company.models import Company

USUARIO = "VXNlcjo1"


@pytest.fixture
def cliente():
    return TestClient(main.app)


def _company(**kw):
    base = dict(rut="76.543.210-3", razon_social="Comercial Ventu SpA")
    base.update(kw)
    return Company(**base)


def _alta(**kw):
    datos = {"user_id": USUARIO, "rut": "76.543.210-3",
             "razon_social": "Comercial Ventu SpA"}
    datos.update(kw)
    return datos


# ───────────────────────── alta ─────────────────────────

def test_alta_ignora_el_nivel_de_precio_que_envia_el_cliente(monkeypatch, cliente):
    """Si lo eligiera quien se registra, cualquiera se asignaría precio
    mayorista."""
    registrada = []
    monkeypatch.setattr(main.company_svc, "obtener_de_usuario", lambda uid: None)
    monkeypatch.setattr(main.company_svc, "registrar",
                        lambda uid, c: registrada.append(c) or c)

    r = cliente.post("/company", json=_alta(nivel_precio="b2b-cl"))
    assert r.status_code == 200
    assert r.json()["nivel_precio"] == config.DEFAULT_NIVEL_PRECIO
    assert registrada[0].nivel_precio == config.DEFAULT_NIVEL_PRECIO != "b2b-cl"


def test_alta_nace_en_revision(monkeypatch, cliente):
    monkeypatch.setattr(config, "DEFAULT_NIVEL_PRECIO", "retail-cl")
    monkeypatch.setattr(main.company_svc, "obtener_de_usuario", lambda uid: None)
    monkeypatch.setattr(main.company_svc, "registrar", lambda uid, c: c)

    d = cliente.post("/company", json=_alta()).json()
    assert d["aprobada"] is False
    assert d["estado"] == "pendiente"


def test_alta_escribe_el_estado_pendiente_en_la_metadata_publica(monkeypatch, cliente):
    """De punta a punta por el servicio real: el espejo queda escrito en el
    alta y la empresa aparece de inmediato entre las pendientes."""
    monkeypatch.setattr(config, "DEFAULT_NIVEL_PRECIO", "retail-cl")
    capturas = []

    def gql(query, variables=None, **kw):
        if "customers(" in query:
            return {"data": {"customers": {"edges": []}}}
        if "user(id" in query:
            return {"data": {"user": {"id": USUARIO, "email": "compras@ejemplo.cl",
                                      "metadata": [], "privateMetadata": []}}}
        clave = "updatePrivateMetadata" if "updatePrivateMetadata" in query else "updateMetadata"
        capturas.append((clave, {e["key"]: e["value"] for e in variables["input"]}))
        return {"data": {clave: {"errors": []}}}

    monkeypatch.setattr(company_service, "gql", gql)
    assert cliente.post("/company", json=_alta()).status_code == 200
    publica = dict(capturas)["updateMetadata"]
    assert publica[models.K_ESTADO] == "pendiente"
    assert models.K_ESTADO not in dict(capturas)["updatePrivateMetadata"]


def test_alta_de_un_usuario_que_ya_tiene_empresa_es_409(monkeypatch, cliente):
    """Re-registrar reescribiría el nivel asignado y el crédito aprobado con los
    valores iniciales."""
    def no_debe_escribir(*a, **kw):
        raise AssertionError("no debió reescribirse la empresa")

    monkeypatch.setattr(main.company_svc, "obtener_de_usuario",
                        lambda uid: _company(nivel_precio="b2b-cl",
                                             condicion_pago="credito_30",
                                             credito_estado="aprobada"))
    monkeypatch.setattr(main.company_svc, "registrar", no_debe_escribir)

    r = cliente.post("/company", json=_alta())
    assert r.status_code == 409


def test_alta_con_rut_de_otro_usuario_es_409(monkeypatch, cliente):
    def ajeno(uid, c):
        raise main.company_svc.EmpresaYaRegistrada(c.rut)

    monkeypatch.setattr(main.company_svc, "obtener_de_usuario", lambda uid: None)
    monkeypatch.setattr(main.company_svc, "registrar", ajeno)
    assert cliente.post("/company", json=_alta()).status_code == 409


def test_alta_con_rut_invalido_es_422(monkeypatch, cliente):
    monkeypatch.setattr(main.company_svc, "obtener_de_usuario", lambda uid: None)
    assert cliente.post("/company", json=_alta(rut="76.543.210-9")).status_code == 422


# ───────────────────────── cambios del staff ─────────────────────────

def _saleor(meta=None, privada=None, existe=True, capturas=None, legado=False):
    """Saleor falso para `company.service`: un usuario y sus dos metadatas.

    Por omisión, una empresa actual: la identidad en la privada (la que vale)
    y su índice en la pública. `legado` es una empresa anterior a la copia
    privada: la identidad solo en la pública.
    """
    identidad = {models.K_RUT: "76543210-3", models.K_RAZON: "Comercial Ventu SpA"}
    meta = {**identidad, **(meta or {})}
    privada = {**({} if legado else identidad), **(privada or {})}

    def gql(query, variables=None, **kw):
        if "user(id" in query:
            if not existe:
                return {"data": {"user": None}}
            return {"data": {"user": {
                "id": USUARIO, "email": "compras@ejemplo.cl", "firstName": "Ana",
                "metadata": [{"key": k, "value": v} for k, v in meta.items()],
                "privateMetadata": [{"key": k, "value": v} for k, v in privada.items()],
            }}}
        clave = "updatePrivateMetadata" if "updatePrivateMetadata" in query else "updateMetadata"
        if capturas is not None:
            capturas.append((clave, {e["key"]: e["value"] for e in variables["input"]}))
        return {"data": {clave: {"errors": []}}}
    return gql


def _no_debe_llamar(*a, **kw):
    raise AssertionError("no debió llamarse a Saleor")


def test_el_staff_asigna_nivel_mayorista(monkeypatch, cliente):
    capturas = []
    monkeypatch.setattr(company_service, "gql", _saleor(capturas=capturas))

    r = cliente.patch(f"/company/{USUARIO}",
                      json={"nivel_precio": "b2b-cl", "actor": "staff@ejemplo.cl"})
    assert r.status_code == 200
    d = r.json()
    assert d["registrada"] is True
    assert d["nivel_precio"] == "b2b-cl"
    assert d["rut"] == "76543210-3"
    assert d["aprobada"] is True
    assert d["estado"] == "aprobada"
    assert "medios_pago" in d

    # El nivel (privado, la fuente de verdad) primero; después su espejo
    # público, y en la pública nada más que el espejo.
    assert [c[0] for c in capturas] == ["updatePrivateMetadata", "updateMetadata"]
    assert capturas[1][1] == {models.K_ESTADO: "aprobada"}
    escrito = capturas[0][1]
    assert escrito[models.K_NIVEL] == "b2b-cl"
    log = json.loads(escrito[company_service.K_LOG])
    assert log[-1]["actor"] == "staff@ejemplo.cl"
    assert log[-1]["cambios"] == {"nivel_precio": ["retail-cl", "b2b-cl"]}
    assert log[-1]["ts"].endswith("Z")


def test_el_cambio_se_anexa_al_historial_existente(monkeypatch, cliente):
    capturas = []
    previo = json.dumps([{"ts": "2026-08-01T00:00:00Z", "actor": "x", "cambios": {}}])
    monkeypatch.setattr(company_service, "gql",
                        _saleor(privada={company_service.K_LOG: previo}, capturas=capturas))

    cliente.patch(f"/company/{USUARIO}", json={"condicion_pago": "credito_30"})
    log = json.loads(capturas[0][1][company_service.K_LOG])
    assert len(log) == 2
    assert log[-1]["actor"] == "staff", "sin actor declarado queda como staff"


def test_cambiar_la_razon_social_escribe_la_metadata_publica(monkeypatch, cliente):
    capturas = []
    monkeypatch.setattr(company_service, "gql", _saleor(capturas=capturas))

    r = cliente.patch(f"/company/{USUARIO}", json={"razon_social": "  Ventu Norte SpA "})
    assert r.status_code == 200
    assert r.json()["razon_social"] == "Ventu Norte SpA"
    por_clave = dict(capturas)
    assert por_clave["updateMetadata"] == {models.K_RAZON: "Ventu Norte SpA"}
    # La privada es la que vale; el historial es privado aunque el dato
    # cambiado también esté en la pública.
    assert por_clave["updatePrivateMetadata"][models.K_RAZON] == "Ventu Norte SpA"
    assert company_service.K_LOG in por_clave["updatePrivateMetadata"]


def test_sin_diferencias_no_se_escribe_nada(monkeypatch, cliente):
    capturas = []
    monkeypatch.setattr(company_service, "gql",
                        _saleor(meta={models.K_ESTADO: "aprobada"},
                                privada={models.K_NIVEL: "b2b-cl"}, capturas=capturas))
    r = cliente.patch(f"/company/{USUARIO}", json={"nivel_precio": "b2b-cl"})
    assert r.status_code == 200
    assert capturas == []


def test_nivel_no_permitido_es_422(monkeypatch, cliente):
    """Un canal mal escrito dejaría a la empresa sin precio en ningún producto."""
    monkeypatch.setattr(company_service, "gql", _no_debe_llamar)
    r = cliente.patch(f"/company/{USUARIO}", json={"nivel_precio": "b2b-cI"})
    assert r.status_code == 422
    assert "no permitido" in r.json()["detail"]


def test_los_niveles_permitidos_vienen_de_la_configuracion(monkeypatch, cliente):
    monkeypatch.setattr(config, "NIVELES_PERMITIDOS", ["retail-cl"])
    monkeypatch.setattr(company_service, "gql", _no_debe_llamar)
    assert cliente.patch(f"/company/{USUARIO}", json={"nivel_precio": "b2b-cl"}).status_code == 422


def test_condicion_de_pago_desconocida_es_422(monkeypatch, cliente):
    monkeypatch.setattr(company_service, "gql", _no_debe_llamar)
    r = cliente.patch(f"/company/{USUARIO}", json={"condicion_pago": "credito_365"})
    assert r.status_code == 422


@pytest.mark.parametrize("cuerpo", [{}, {"actor": "staff@ejemplo.cl"}])
def test_sin_cambios_es_422(monkeypatch, cliente, cuerpo):
    monkeypatch.setattr(company_service, "gql", _no_debe_llamar)
    assert cliente.patch(f"/company/{USUARIO}", json=cuerpo).status_code == 422


def test_razon_social_vacia_es_422(monkeypatch, cliente):
    capturas = []
    monkeypatch.setattr(company_service, "gql", _saleor(capturas=capturas))
    assert cliente.patch(f"/company/{USUARIO}", json={"razon_social": "  "}).status_code == 422
    assert capturas == []


def test_el_rut_no_se_puede_cambiar(monkeypatch, cliente):
    """Cambiar el RUT sería otra empresa: el campo ni siquiera se acepta."""
    capturas = []
    monkeypatch.setattr(company_service, "gql", _saleor(capturas=capturas))
    r = cliente.patch(f"/company/{USUARIO}", json={"rut": "11.111.111-1"})
    assert r.status_code == 422
    assert capturas == []


@pytest.mark.parametrize("existe,meta", [
    (False, None),
    (True, {models.K_RUT: ""}),
    (True, None),  # identidad escrita a mano en la pública, sin alta
])
def test_usuario_sin_empresa_es_404(monkeypatch, cliente, existe, meta):
    capturas = []
    monkeypatch.setattr(company_service, "gql",
                        _saleor(meta=meta, existe=existe, capturas=capturas, legado=True))
    r = cliente.patch(f"/company/{USUARIO}", json={"nivel_precio": "b2b-cl"})
    assert r.status_code == 404
    assert capturas == []


def test_campos_no_editables_se_rechazan_en_el_servicio():
    with pytest.raises(models.CompanyInvalida, match="no editables"):
        company_service.actualizar(USUARIO, {"rut": "1-9"}, actor="x", ahora="t")



# ───────────────────────── aprobación ─────────────────────────

def test_volver_a_un_nivel_no_b2b_la_deja_otra_vez_en_revision(monkeypatch, cliente):
    capturas = []
    monkeypatch.setattr(company_service, "gql",
                        _saleor(meta={models.K_ESTADO: "aprobada"},
                                privada={models.K_NIVEL: "b2b-cl"}, capturas=capturas))

    r = cliente.patch(f"/company/{USUARIO}", json={"nivel_precio": "retail-cl"})
    assert r.status_code == 200
    d = r.json()
    assert d["aprobada"] is False
    assert d["estado"] == "pendiente"
    assert all(m["motivo"] == "pendiente_aprobacion" for m in d["medios_pago"])
    assert dict(capturas)["updateMetadata"] == {models.K_ESTADO: "pendiente"}
    assert dict(capturas)["updatePrivateMetadata"][models.K_NIVEL] == "retail-cl"


def test_reenviar_el_nivel_repara_el_espejo_de_una_empresa_antigua(monkeypatch, cliente):
    """Una empresa anterior al espejo no aparece en /pendientes ni se lista
    bien. Reenviar su nivel escribe solo el espejo: no es un cambio de la
    empresa, así que no va al historial."""
    capturas = []
    monkeypatch.setattr(company_service, "gql",
                        _saleor(privada={models.K_NIVEL: "retail-cl"}, capturas=capturas))

    r = cliente.patch(f"/company/{USUARIO}", json={"nivel_precio": "retail-cl"})
    assert r.status_code == 200
    assert capturas == [("updateMetadata", {models.K_ESTADO: "pendiente"})]


def test_el_patch_congela_la_identidad_de_una_empresa_antigua(monkeypatch, cliente):
    """Una empresa anterior a la copia privada se lee de la pública, que el
    cliente puede reescribir. El primer PATCH del staff la deja en la privada,
    y desde ahí manda esa. No es un cambio de la empresa: no va al historial."""
    capturas = []
    monkeypatch.setattr(company_service, "gql", _saleor(
        meta={models.K_GIRO: "Ferretería"}, privada={models.K_NIVEL: "retail-cl"},
        legado=True, capturas=capturas))

    r = cliente.patch(f"/company/{USUARIO}", json={"nivel_precio": "retail-cl"})
    assert r.status_code == 200
    privada = dict(capturas)["updatePrivateMetadata"]
    assert privada == {models.K_RUT: "76543210-3",
                       models.K_RAZON: "Comercial Ventu SpA",
                       models.K_GIRO: "Ferretería"}


def test_el_patch_rehace_el_indice_publico_alterado(monkeypatch, cliente):
    """Si el cliente cambió su RUT público, la búsqueda por RUT deja de
    encontrar a su empresa. Cualquier PATCH lo devuelve a lo que vale."""
    capturas = []
    monkeypatch.setattr(company_service, "gql", _saleor(
        meta={models.K_RUT: "11111111-1", models.K_ESTADO: "pendiente"},
        capturas=capturas))

    r = cliente.patch(f"/company/{USUARIO}", json={"condicion_pago": "credito_30"})
    assert r.status_code == 200
    assert r.json()["rut"] == "76543210-3"
    assert dict(capturas)["updateMetadata"] == {models.K_RUT: "76543210-3"}


def test_otros_cambios_no_escriben_el_espejo(monkeypatch, cliente):
    capturas = []
    monkeypatch.setattr(company_service, "gql", _saleor(capturas=capturas))
    cliente.patch(f"/company/{USUARIO}", json={"condicion_pago": "credito_30"})
    assert [c[0] for c in capturas] == ["updatePrivateMetadata"]


@pytest.mark.parametrize("privada,aprobada", [
    ({models.K_NIVEL: "b2b-cl"}, True),
    ({models.K_NIVEL: "retail-cl"}, False),
    ({}, False),  # sin nivel: el de omisión, retail
])
def test_empresa_sin_espejo_se_lee_por_su_nivel(monkeypatch, cliente, privada, aprobada):
    """Las empresas anteriores a `ventu.b2b.estado` siguen funcionando: la
    aprobación se deriva del nivel, nunca del espejo."""
    monkeypatch.setattr(company_service, "gql", _saleor(privada=privada))
    d = cliente.get(f"/company/de-usuario/{USUARIO}").json()
    assert d["aprobada"] is aprobada
    assert d["estado"] == ("aprobada" if aprobada else "pendiente")
    habilitados = [m for m in d["medios_pago"] if m["habilitado"]]
    assert bool(habilitados) is aprobada


def test_el_espejo_no_decide_la_aprobacion(monkeypatch, cliente):
    monkeypatch.setattr(company_service, "gql",
                        _saleor(meta={models.K_ESTADO: "aprobada"},
                                privada={models.K_NIVEL: "retail-cl"}))
    assert cliente.get(f"/company/de-usuario/{USUARIO}").json()["aprobada"] is False


# ───────────────────────── aviso de empresa aprobada ─────────────────────────

class _Correo:
    """Ventu Correo falso: guarda cada llamada y responde lo que se le pide.
    Una respuesta que es una excepción se lanza, como haría httpx."""

    def __init__(self, *respuestas):
        self.respuestas = list(respuestas) or [
            httpx.Response(200, json={"enviado": True, "id": "msg_1", "error": None})]
        self.llamadas = []

    def __call__(self, url, json, headers):
        self.llamadas.append((url, json, headers))
        r = self.respuestas.pop(0) if len(self.respuestas) > 1 else self.respuestas[0]
        if isinstance(r, Exception):
            raise r
        return r


@pytest.fixture
def correo(monkeypatch):
    monkeypatch.setattr(config, "CORREO_URL", "https://correo.test")
    monkeypatch.setattr(config, "CORREO_SERVICE_TOKEN", "tok")
    monkeypatch.setattr(config, "STOREFRONT_URL", "https://tienda.test")
    falso = _Correo()
    monkeypatch.setattr(avisos, "_publicar", falso)
    return falso


def _aprobar(monkeypatch, cliente, **saleor):
    saleor.setdefault("meta", {models.K_ESTADO: "pendiente"})
    saleor.setdefault("privada", {models.K_NIVEL: "retail-cl"})
    monkeypatch.setattr(company_service, "gql", _saleor(**saleor))
    return cliente.patch(f"/company/{USUARIO}", json={"nivel_precio": "b2b-cl"})


def test_aprobar_avisa_al_cliente(monkeypatch, cliente, correo):
    r = _aprobar(monkeypatch, cliente)
    assert r.status_code == 200
    assert r.json()["aviso_cliente"] == {"enviado": True, "id": "msg_1"}

    (url, cuerpo, cabeceras), = correo.llamadas
    assert url == "https://correo.test/enviar"
    assert cabeceras == {"Authorization": "Bearer tok"}
    assert cuerpo["para"] == "compras@ejemplo.cl"
    assert cuerpo["asunto"] == "Tu empresa ya puede comprar en Ventu"
    assert cuerpo["etiqueta"] == "empresa-aprobada"
    assert cuerpo["clave_idempotencia"].startswith("empresa-aprobada-")
    aviso = cuerpo["aviso"]
    assert aviso["nombre"] == "Ana"
    assert "Comercial Ventu SpA (RUT 76.543.210-3)" in aviso["parrafos"][0]
    assert aviso["boton"] == {"texto": "Ir a la tienda", "url": "https://tienda.test/es/b2b-cl"}


@pytest.mark.parametrize("meta,privada,cambio", [
    # ya aprobada: reenviar el nivel no es aprobarla otra vez
    ({models.K_ESTADO: "aprobada"}, {models.K_NIVEL: "b2b-cl"}, {"nivel_precio": "b2b-cl"}),
    # antigua sin espejo que ya compraba: reparar el espejo no es aprobarla
    ({}, {models.K_NIVEL: "b2b-cl"}, {"nivel_precio": "b2b-cl"}),
    # devolverla a revisión
    ({models.K_ESTADO: "aprobada"}, {models.K_NIVEL: "b2b-cl"}, {"nivel_precio": "retail-cl"}),
    # otro cambio sobre una pendiente
    ({models.K_ESTADO: "pendiente"}, {models.K_NIVEL: "retail-cl"}, {"condicion_pago": "credito_30"}),
    # otro cambio sobre una aprobada
    ({models.K_ESTADO: "aprobada"}, {models.K_NIVEL: "b2b-cl"}, {"condicion_pago": "credito_30"}),
])
def test_solo_se_avisa_al_aprobar(monkeypatch, cliente, correo, meta, privada, cambio):
    monkeypatch.setattr(company_service, "gql", _saleor(meta=meta, privada=privada))
    r = cliente.patch(f"/company/{USUARIO}", json=cambio)
    assert r.status_code == 200
    assert "aviso_cliente" not in r.json()
    assert correo.llamadas == []


def test_reenviar_el_nivel_tras_una_escritura_a_medias_avisa(monkeypatch, cliente, correo):
    """El nivel B2B alcanzó a escribirse pero el espejo no: el PATCH falló
    antes de avisar. Reenviar el nivel repara el espejo y manda el aviso."""
    r = _aprobar(monkeypatch, cliente, privada={models.K_NIVEL: "b2b-cl"})
    assert r.json()["aviso_cliente"]["enviado"] is True
    assert len(correo.llamadas) == 1


def test_si_falla_la_escritura_no_se_avisa(monkeypatch, cliente, correo):
    base = _saleor(meta={models.K_ESTADO: "pendiente"}, privada={models.K_NIVEL: "retail-cl"})

    def gql(query, variables=None, **kw):
        if "updatePrivateMetadata" in query:
            return {"data": {"updatePrivateMetadata": {"errors": [{"message": "no"}]}}}
        return base(query, variables, **kw)

    monkeypatch.setattr(company_service, "gql", gql)
    r = cliente.patch(f"/company/{USUARIO}", json={"nivel_precio": "b2b-cl"})
    assert r.status_code == 502
    assert correo.llamadas == []


def test_sin_correo_configurado_aprueba_igual(monkeypatch, cliente, correo):
    monkeypatch.setattr(config, "CORREO_SERVICE_TOKEN", "")
    r = _aprobar(monkeypatch, cliente)
    assert r.status_code == 200
    assert r.json()["aprobada"] is True
    assert r.json()["aviso_cliente"] == {"enviado": False, "motivo": "correo no configurado"}
    assert correo.llamadas == []


@pytest.mark.parametrize("respuesta,motivo", [
    (httpx.Response(502, json={"enviado": False, "id": None, "error": "dominio no verificado"}),
     "dominio no verificado"),
    (httpx.Response(503, json={"detail": "CORREO_SERVICE_TOKEN no configurado"}),
     "CORREO_SERVICE_TOKEN no configurado"),
    (httpx.Response(500, text="Internal Server Error"), "HTTP 500"),
    (httpx.ReadTimeout("lento"), "puede haber salido"),
    (httpx.ConnectError("caído"), "inalcanzable"),
])
def test_si_el_correo_falla_la_aprobacion_queda(monkeypatch, cliente, correo, respuesta, motivo):
    correo.respuestas = [respuesta]
    r = _aprobar(monkeypatch, cliente)
    assert r.status_code == 200
    assert r.json()["aprobada"] is True
    aviso = r.json()["aviso_cliente"]
    assert aviso["enviado"] is False and motivo in aviso["motivo"]


def test_reintenta_una_vez_si_el_correo_no_conecta(monkeypatch, cliente, correo):
    """Ventu Correo reiniciando por un deploy: el segundo intento lo alcanza, y
    la misma clave impide que Resend lo mande dos veces."""
    correo.respuestas = [httpx.ConnectError("reiniciando"), *correo.respuestas]
    r = _aprobar(monkeypatch, cliente)
    assert r.json()["aviso_cliente"]["enviado"] is True
    assert len(correo.llamadas) == 2
    assert correo.llamadas[0][1] == correo.llamadas[1][1]


def test_sin_storefront_el_aviso_va_sin_boton(monkeypatch, cliente, correo):
    monkeypatch.setattr(config, "STOREFRONT_URL", "")
    _aprobar(monkeypatch, cliente)
    assert "boton" not in correo.llamadas[0][1]["aviso"]


# ───────────────────────── /company/pendientes ─────────────────────────

def _nodo_pendiente(n, *, nivel="retail-cl", rut="76.543.210-3", alta=None,
                    forjada=False):
    """`forjada`: las claves escritas a mano por el cliente en su pública, sin
    alta, o sea sin nada en la privada."""
    privada = [] if forjada else [
        {"key": models.K_NIVEL, "value": nivel},
        {"key": models.K_RUT, "value": rut},
        {"key": models.K_RAZON, "value": f"Empresa {n} SpA"},
        {"key": models.K_GIRO, "value": "Ferretería"},
        {"key": models.K_TELEFONO, "value": "+56911112222"}]
    if alta:
        privada.append({"key": company_service.K_ALTA, "value": alta})
    return {"node": {
        "id": f"VXNlcjo{n}", "email": f"compras{n}@ejemplo.cl",
        "firstName": "Ana", "lastName": "Pérez", "isActive": True,
        "isConfirmed": False, "dateJoined": f"2026-09-0{n}T12:00:00+00:00",
        "metadata": [{"key": models.K_RUT, "value": rut},
                     {"key": models.K_RAZON, "value": f"Empresa {n} SpA"},
                     {"key": models.K_GIRO, "value": "Ferretería"},
                     {"key": models.K_TELEFONO, "value": "+56911112222"},
                     {"key": models.K_ESTADO, "value": "pendiente"}],
        "privateMetadata": privada,
    }}


def _saleor_pendientes(paginas, llamadas):
    """Saleor falso para la lista: `paginas` es una lista de listas de nodos;
    responde la página que corresponde al cursor recibido."""
    def gql(query, variables=None, **kw):
        assert "customers(" in query, query[:60]
        llamadas.append((query, dict(variables or {})))
        cursor = (variables or {}).get("after")
        i = int(cursor) if cursor else 0
        hay_mas = i + 1 < len(paginas)
        return {"data": {"customers": {
            "pageInfo": {"hasNextPage": hay_mas, "endCursor": str(i + 1) if hay_mas else None},
            "edges": paginas[i]}}}
    return gql


def test_pendientes_filtra_por_el_espejo_publico(monkeypatch, cliente):
    llamadas = []
    monkeypatch.setattr(company_service, "gql",
                        _saleor_pendientes([[_nodo_pendiente(1)]], llamadas))

    r = cliente.get("/company/pendientes")
    assert r.status_code == 200
    query, variables = llamadas[0]
    assert "filter: {metadata: [{key: $key, value: $value}]}" in query
    assert variables["key"] == models.K_ESTADO == "ventu.b2b.estado"
    assert variables["value"] == "pendiente"
    assert variables["first"] == 100
    assert "sortBy: {field: CREATED_AT, direction: ASC}" in query


def test_pendientes_devuelve_lo_necesario_para_revisar(monkeypatch, cliente):
    monkeypatch.setattr(company_service, "gql", _saleor_pendientes(
        [[_nodo_pendiente(1, alta="2026-09-01T12:05:00Z")]], []))

    d = cliente.get("/company/pendientes").json()
    assert d["total"] == 1
    assert d["truncado"] is False
    assert "aviso" not in d
    assert d["empresas"] == [{
        "user_id": "VXNlcjo1", "email": "compras1@ejemplo.cl", "nombre": "Ana Pérez",
        "rut": "76543210-3", "razon_social": "Empresa 1 SpA", "giro": "Ferretería",
        "telefono": "+56911112222", "nivel_precio": "retail-cl",
        "cuenta_creada": "2026-09-01T12:00:00+00:00",
        "empresa_registrada": "2026-09-01T12:05:00Z",
        "correo_confirmado": False, "activa": True,
    }]


def test_pendientes_recorre_todas_las_paginas(monkeypatch, cliente):
    llamadas = []
    paginas = [[_nodo_pendiente(1), _nodo_pendiente(2)], [_nodo_pendiente(3)]]
    monkeypatch.setattr(company_service, "gql", _saleor_pendientes(paginas, llamadas))

    d = cliente.get("/company/pendientes").json()
    assert [e["user_id"] for e in d["empresas"]] == ["VXNlcjo1", "VXNlcjo2", "VXNlcjo3"]
    assert d["truncado"] is False
    assert [v.get("after") for _, v in llamadas] == [None, "1"]


def test_pendientes_avisa_cuando_corta_por_el_tope(monkeypatch, cliente):
    """Un filtro que dejó de filtrar no debe recorrer la base entera, pero la
    lista cortada tiene que decir que lo está."""
    llamadas = []
    paginas = [[_nodo_pendiente(i)] for i in range(1, 6)]
    monkeypatch.setattr(company_service, "MAX_PAGINAS", 2)
    monkeypatch.setattr(company_service, "gql", _saleor_pendientes(paginas, llamadas))

    d = cliente.get("/company/pendientes").json()
    assert len(llamadas) == 2
    assert d["total"] == 2
    assert d["truncado"] is True
    assert "hay más" in d["aviso"]


def test_pendientes_omite_espejos_atrasados_y_empresas_ilegibles(monkeypatch, cliente):
    """Si el nivel ya es B2B, la empresa no está pendiente aunque el espejo lo
    diga (quedó atrás por una escritura a medias). Y una empresa inventada en
    la pública, sin alta, no se le ofrece al staff para aprobar."""
    paginas = [[_nodo_pendiente(1, nivel="b2b-cl"),
                _nodo_pendiente(2, rut="76.543.210-9"),
                _nodo_pendiente(3),
                _nodo_pendiente(4, forjada=True)]]
    monkeypatch.setattr(company_service, "gql", _saleor_pendientes(paginas, []))

    d = cliente.get("/company/pendientes").json()
    assert [e["user_id"] for e in d["empresas"]] == ["VXNlcjo3"]


def test_pendientes_es_solo_para_el_staff(monkeypatch, cliente):
    monkeypatch.setattr(config, "SERVICE_TOKEN", "tok-servicio-de-prueba")
    monkeypatch.setattr(config, "STAFF_TOKEN", "tok-staff-de-prueba")
    monkeypatch.setattr(company_service, "gql", _saleor_pendientes([[]], []))

    servicio = {"Authorization": "Bearer tok-servicio-de-prueba"}
    staff = {"Authorization": "Bearer tok-staff-de-prueba"}
    assert cliente.get("/company/pendientes", headers=servicio).status_code == 401
    assert cliente.get("/company/pendientes").status_code == 401
    assert cliente.get("/company/pendientes", headers=staff).status_code == 200


def test_pendientes_con_saleor_caido_es_502(monkeypatch, cliente):
    monkeypatch.setattr(company_service, "gql",
                        lambda *a, **kw: {"errors": [{"message": "permiso"}]})
    assert cliente.get("/company/pendientes").status_code == 502
