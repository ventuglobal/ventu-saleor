"""Tests del enlace de carrito: puros, sin red."""

from __future__ import annotations

import pytest

from ventu_b2b.cart import link


def test_genera_identificadores_distintos():
    ids = {link.generar() for _ in range(200)}
    assert len(ids) == 200, "colisión: el espacio o la fuente de azar es débil"


def test_largo_estable():
    assert len(link.generar()) == link.LARGO


def test_evita_caracteres_confundibles():
    """El enlace a veces se lee en voz alta o se dicta por teléfono."""
    for prohibido in "0O1lI":
        assert prohibido not in link.ALFABETO


def test_valida_los_generados():
    for _ in range(50):
        assert link.es_valido(link.generar())


@pytest.mark.parametrize("malo", ["", "corto", "0" * 22, "a" * 21, "a" * 23, "a!" * 11])
def test_rechaza_identificadores_malformados(malo):
    assert link.es_valido(malo) is False
    with pytest.raises(link.LinkInvalido):
        link.validar(malo)


def test_url_completa():
    lid = link.generar()
    assert link.url("https://ventu.cl", lid) == f"https://ventu.cl/c/{lid}"


def test_url_tolera_barra_final():
    lid = link.generar()
    assert link.url("https://ventu.cl/", lid) == f"https://ventu.cl/c/{lid}"


def test_url_rechaza_identificador_invalido():
    with pytest.raises(link.LinkInvalido):
        link.url("https://ventu.cl", "manipulado")
