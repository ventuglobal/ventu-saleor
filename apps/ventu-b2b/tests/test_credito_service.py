"""Tests del servicio de crédito: sin red, con un Saleor falso."""

from __future__ import annotations

import json

import pytest

from ventu_b2b import auditoria

from ventu_b2b.company.models import Company
from ventu_b2b.credito import estados as st
from ventu_b2b.credito import service

AHORA = "2026-08-10T04:00:00Z"


def _company(**kw):
    base = dict(rut="76.543.210-3", razon_social="Comercial Ventu SpA")
    base.update(kw)
    return Company(**base)


def _router(capturas=None, errores=None, historial=None):
    def gql(query, variables=None, **kw):
        if "privateMetafield" in query:
            # El registro se lee antes de anexarle la entrada nueva.
            return {"data": {"user": {"privateMetafield": historial}}}
        if "updatePrivateMetadata" in query:
            if capturas is not None:
                capturas.append((variables or {}).get("input"))
            return {"data": {"updatePrivateMetadata": {"errors": errores or []}}}
        raise AssertionError(f"query inesperada: {query[:40]}")
    return gql


def _claves(entrada):
    return {p["key"]: p["value"] for p in entrada}


# ───────────────────────── solicitud ─────────────────────────

def test_solicitar_deja_pendiente(monkeypatch):
    capturas = []
    monkeypatch.setattr(service, "gql", _router(capturas))
    s = service.solicitar("VXNlcjo1", _company(), ahora=AHORA)
    assert s.estado == st.PENDIENTE
    assert _claves(capturas[0])["ventu.b2b.credito_estado"] == st.PENDIENTE


def test_no_se_puede_solicitar_dos_veces_seguidas(monkeypatch):
    """De pendiente a pendiente no es una transición: evita duplicar registros."""
    monkeypatch.setattr(service, "gql", _router())
    with pytest.raises(st.TransicionInvalida):
        service.solicitar("VXNlcjo1", _company(credito_estado=st.PENDIENTE), ahora=AHORA)


def test_una_empresa_rechazada_puede_volver_a_solicitar(monkeypatch):
    monkeypatch.setattr(service, "gql", _router())
    s = service.solicitar("VXNlcjo1", _company(credito_estado=st.RECHAZADA), ahora=AHORA)
    assert s.estado == st.PENDIENTE


# ───────────────────────── auditoría ─────────────────────────

def test_cada_cambio_deja_registro(monkeypatch):
    """La metadata se sobrescribe; sin registro aparte no habría forma de
    responder por qué una empresa tiene crédito."""
    capturas = []
    monkeypatch.setattr(service, "gql", _router(capturas))
    service.resolver("VXNlcjo1", _company(credito_estado=st.PENDIENTE),
                     "aprobada", ahora=AHORA, referencia="MX-42")
    log = _claves(capturas[0])[service.K_AUDIT]
    assert AHORA in log
    assert "pendiente>aprobada" in log
    assert "MX-42" in log


def test_el_registro_se_anexa_y_no_se_sobrescribe(monkeypatch):
    """Antes cada cambio pisaba al anterior y solo quedaba el último."""
    capturas = []
    previo = json.dumps([{"ts": "2026-08-01T00:00:00Z", "transicion": "sin_solicitud>pendiente"}])
    monkeypatch.setattr(service, "gql", _router(capturas, historial=previo))
    service.resolver("VXNlcjo1", _company(credito_estado=st.PENDIENTE),
                     "aprobada", ahora=AHORA, referencia="MX-42", actor="staff@ejemplo.cl")

    log = json.loads(_claves(capturas[0])[service.K_AUDIT])
    assert [e["transicion"] for e in log] == ["sin_solicitud>pendiente", "pendiente>aprobada"]
    assert log[-1]["actor"] == "staff@ejemplo.cl"


def test_el_registro_esta_acotado(monkeypatch):
    """La metadata viaja completa en cada lectura del usuario: no puede crecer
    sin límite."""
    capturas = []
    previo = json.dumps([{"n": i} for i in range(auditoria.MAX_ENTRADAS)])
    monkeypatch.setattr(service, "gql", _router(capturas, historial=previo))
    service.solicitar("VXNlcjo1", _company(), ahora=AHORA)

    log = json.loads(_claves(capturas[0])[service.K_AUDIT])
    assert len(log) == auditoria.MAX_ENTRADAS
    assert log[0] == {"n": 1}, "se descarta la entrada más antigua"
    assert log[-1]["transicion"] == "sin_solicitud>pendiente"


def test_un_registro_en_formato_antiguo_se_conserva(monkeypatch):
    capturas = []
    monkeypatch.setattr(service, "gql", _router(capturas, historial="2026-07-01 pendiente"))
    service.solicitar("VXNlcjo1", _company(credito_estado=st.RECHAZADA), ahora=AHORA)

    log = json.loads(_claves(capturas[0])[service.K_AUDIT])
    assert log[0] == {"legado": "2026-07-01 pendiente"}


def test_si_no_se_puede_leer_el_historial_no_se_escribe(monkeypatch):
    """Escribir sin haber leído borraría el historial existente."""
    from ventu_b2b.saleor_client import SaleorTransportError

    capturas = []

    def gql(query, variables=None, **kw):
        if "privateMetafield" in query:
            raise SaleorTransportError("caído")
        capturas.append(variables)
        return {"data": {"updatePrivateMetadata": {"errors": []}}}

    monkeypatch.setattr(service, "gql", gql)
    with pytest.raises(service.RegistroFallido):
        service.solicitar("VXNlcjo1", _company(), ahora=AHORA)
    assert capturas == []


def test_anexar_recorta_al_maximo():
    crudo = ""
    for i in range(5):
        crudo = auditoria.anexar(crudo, {"n": i}, maximo=3)
    assert json.loads(crudo) == [{"n": 2}, {"n": 3}, {"n": 4}]


def test_la_referencia_de_maxxa_se_guarda(monkeypatch):
    capturas = []
    monkeypatch.setattr(service, "gql", _router(capturas))
    service.resolver("VXNlcjo1", _company(credito_estado=st.PENDIENTE),
                     "aprobada", ahora=AHORA, referencia="MX-42")
    assert _claves(capturas[0])["ventu.b2b.credito_ref"] == "MX-42"


def test_error_de_saleor_al_registrar_no_pasa_inadvertido(monkeypatch):
    monkeypatch.setattr(service, "gql", _router(
        errores=[{"field": "input", "message": "nope", "code": "INVALID"}]))
    with pytest.raises(service.CreditoError):
        service.solicitar("VXNlcjo1", _company(), ahora=AHORA)


# ───────────────────────── veredicto ─────────────────────────

def test_aprobacion_registrada(monkeypatch):
    monkeypatch.setattr(service, "gql", _router())
    s = service.resolver("VXNlcjo1", _company(credito_estado=st.PENDIENTE),
                         "approved", ahora=AHORA, referencia="MX-1")
    assert s.estado == st.APROBADA


def test_veredicto_ininteligible_no_cambia_nada(monkeypatch):
    """Ante una respuesta que no se entiende, quedarse pendiente: adivinar
    significaría otorgar o negar crédito por error."""
    capturas = []
    monkeypatch.setattr(service, "gql", _router(capturas))
    s = service.resolver("VXNlcjo1", _company(credito_estado=st.PENDIENTE),
                         "quizás", ahora=AHORA)
    assert s.estado == st.PENDIENTE
    assert capturas == [], "no debe escribir nada"


# ───────────────── carpeta tributaria: entregar y borrar ─────────────────

def test_entrega_y_borra_la_copia_local():
    """Retención mínima: recibir y reenviar no obliga a conservar."""
    borrado = []
    ref = service.entregar_carpeta(
        _company(), b"%PDF-carpeta",
        enviar_a_maxxa=lambda rut, doc: "MX-7",
        borrar_local=lambda: borrado.append(True),
    )
    assert ref == "MX-7"
    assert borrado == [True]


def test_si_maxxa_falla_NO_se_borra():
    """El documento es el único ejemplar que subió el cliente: pedírselo de nuevo
    es fricción real, así que se conserva para reintentar."""
    borrado = []

    def explota(rut, doc):
        raise ConnectionError("timeout")

    with pytest.raises(service.EntregaFallida):
        service.entregar_carpeta(_company(), b"%PDF", enviar_a_maxxa=explota,
                                 borrar_local=lambda: borrado.append(True))
    assert borrado == [], "no debe borrarse si la entrega falló"


def test_sin_referencia_la_entrega_se_considera_fallida():
    borrado = []
    with pytest.raises(service.EntregaFallida):
        service.entregar_carpeta(_company(), b"%PDF",
                                 enviar_a_maxxa=lambda r, d: "",
                                 borrar_local=lambda: borrado.append(True))
    assert borrado == []


def test_carpeta_vacia_se_rechaza():
    with pytest.raises(service.CreditoError, match="vacía"):
        service.entregar_carpeta(_company(), b"", enviar_a_maxxa=lambda r, d: "MX-1")


def test_si_falla_el_borrado_la_entrega_sigue_valida(caplog):
    """La entrega ya ocurrió y no se puede deshacer, pero un documento tributario
    sin borrar es exposición retenida: debe quedar registrado."""
    def borrar_roto():
        raise OSError("bucket no disponible")

    ref = service.entregar_carpeta(_company(), b"%PDF",
                                   enviar_a_maxxa=lambda r, d: "MX-9",
                                   borrar_local=borrar_roto)
    assert ref == "MX-9"
    assert any("NO borrada" in r.message for r in caplog.records)


def test_el_rut_llega_normalizado_a_maxxa():
    visto = {}

    def enviar(rut, doc):
        visto["rut"] = rut
        return "MX-3"

    service.entregar_carpeta(_company(rut="76543210-3"), b"%PDF", enviar_a_maxxa=enviar)
    assert visto["rut"] == "76543210-3"
