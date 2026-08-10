"""Tests de la máquina de estados de crédito: puros, sin red."""

from __future__ import annotations

import pytest

from ventu_b2b.credito import estados as st


# ───────────────────────── transiciones válidas ─────────────────────────

@pytest.mark.parametrize("desde,hacia", [
    (st.SIN_SOLICITUD, st.PENDIENTE),
    (st.PENDIENTE, st.APROBADA),
    (st.PENDIENTE, st.RECHAZADA),
    (st.RECHAZADA, st.PENDIENTE),
    (st.APROBADA, st.RECHAZADA),
    (st.APROBADA, st.PENDIENTE),
])
def test_transiciones_permitidas(desde, hacia):
    assert st.puede(desde, hacia)
    assert st.aplicar(desde, hacia).hacia == hacia


def test_una_empresa_rechazada_puede_volver_a_postular():
    """Su situación tributaria cambia con el tiempo: el rechazo no es definitivo."""
    assert st.puede(st.RECHAZADA, st.PENDIENTE)


def test_una_linea_aprobada_puede_revocarse():
    assert st.puede(st.APROBADA, st.RECHAZADA)


# ───────────────────────── transiciones inválidas ─────────────────────────

def test_no_se_aprueba_sin_evaluacion():
    """El salto que importa evitar: crédito otorgado sin que nadie evalúe."""
    assert not st.puede(st.SIN_SOLICITUD, st.APROBADA)
    with pytest.raises(st.TransicionInvalida):
        st.aplicar(st.SIN_SOLICITUD, st.APROBADA)


def test_no_se_rechaza_sin_solicitud():
    assert not st.puede(st.SIN_SOLICITUD, st.RECHAZADA)


@pytest.mark.parametrize("estado", ["", "APROBADA", "en_revision", "aprobado"])
def test_estados_desconocidos_se_rechazan(estado):
    assert not st.puede(st.PENDIENTE, estado)
    assert not st.puede(estado, st.PENDIENTE)


def test_no_hay_transicion_a_si_mismo():
    """Repetir el estado no es un cambio y no debe generar registro de auditoría."""
    for e in st.ESTADOS:
        assert not st.puede(e, e)


# ───────────────────────── auditoría ─────────────────────────

def test_la_transicion_conserva_motivo_y_referencia():
    t = st.aplicar(st.PENDIENTE, st.APROBADA, motivo="Maxxa aprueba 2M", referencia="MX-42")
    assert (t.desde, t.hacia, t.motivo, t.referencia) == (
        st.PENDIENTE, st.APROBADA, "Maxxa aprueba 2M", "MX-42")


def test_la_transicion_valida_al_construirse():
    """No debe poder existir un registro de auditoría de algo imposible."""
    with pytest.raises(st.TransicionInvalida):
        st.Transicion(desde=st.SIN_SOLICITUD, hacia=st.APROBADA)


# ───────────────────────── veredicto de Maxxa ─────────────────────────

@pytest.mark.parametrize("veredicto,esperado", [
    ("aprobada", st.APROBADA), ("approved", st.APROBADA), ("OK", st.APROBADA),
    ("rechazada", st.RECHAZADA), ("rejected", st.RECHAZADA), ("Denied", st.RECHAZADA),
])
def test_traduce_el_veredicto_de_maxxa(veredicto, esperado):
    assert st.resultado_maxxa(veredicto) == esperado


@pytest.mark.parametrize("raro", ["", "   ", "quizás", "pending", None])
def test_veredicto_desconocido_no_se_interpreta(raro):
    """Ante una respuesta que no se entiende, dejar pendiente y revisar a mano:
    interpretarla mal significaría otorgar crédito por error."""
    assert st.resultado_maxxa(raro) is None


def test_destinos_para_la_interfaz():
    assert set(st.destinos(st.PENDIENTE)) == {st.APROBADA, st.RECHAZADA}
    assert st.destinos(st.SIN_SOLICITUD) == (st.PENDIENTE,)
