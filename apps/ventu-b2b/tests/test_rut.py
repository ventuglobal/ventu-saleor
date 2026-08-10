"""Tests de RUT: puros, sin red."""

from __future__ import annotations

import pytest

from ventu_b2b.company import rut


# ───────────────────────── normalización ─────────────────────────

@pytest.mark.parametrize("entrada", [
    "76.543.210-3",
    "76543210-3",
    "765432103",
    " 76.543.210-3 ",
    "76.543.210-3",
])
def test_mismo_rut_en_distintos_formatos_normaliza_igual(entrada):
    """Todos los formatos de escritura deben converger a una sola forma.

    Sin esto la misma empresa aparecería varias veces y la unicidad por RUT
    dejaría de funcionar.
    """
    assert rut.normalizar(entrada) == "76543210-3"


def test_verificador_k_se_normaliza_en_mayuscula():
    assert rut.normalizar("76.543.209-k") == "76543209-K"
    assert rut.normalizar("76543209K") == "76543209-K"


# ───────────────────────── dígito verificador ─────────────────────────

def test_digito_verificador_conocidos():
    assert rut.digito_verificador("76543210") == "3"
    assert rut.digito_verificador("12345678") == "5"
    assert rut.digito_verificador("76543209") == "K"
    assert rut.digito_verificador("11111111") == "1"


def test_rechaza_verificador_incorrecto():
    """Formato correcto pero verificador equivocado es digitación, no un RUT."""
    with pytest.raises(rut.RutInvalido, match="dígito verificador"):
        rut.normalizar("76.543.210-9")


@pytest.mark.parametrize("malo", ["", "   ", "abc", "1234", "76.543.210-XY", "1234567890123"])
def test_rechaza_entradas_invalidas(malo):
    with pytest.raises(rut.RutInvalido):
        rut.normalizar(malo)


def test_es_valido_no_lanza():
    assert rut.es_valido("76.543.210-3") is True
    assert rut.es_valido("76.543.210-9") is False
    assert rut.es_valido("") is False


# ───────────────────────── presentación ─────────────────────────

def test_formatear_para_mostrar():
    assert rut.formatear("76543210-3") == "76.543.210-3"
    assert rut.formatear("76543209-K") == "76.543.209-K"


def test_formatear_rut_corto():
    canonico = rut.normalizar("7.654.321-" + rut.digito_verificador("7654321"))
    assert rut.formatear(canonico).startswith("7.654.321-")


def test_formatear_exige_forma_canonica():
    """Evita que se filtre a la vista un RUT sin normalizar."""
    with pytest.raises(rut.RutInvalido):
        rut.formatear("76.543.210-3")
