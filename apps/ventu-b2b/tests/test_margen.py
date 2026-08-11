"""Tests del margen neto garantizado (portado de Ventu 1.0)."""

from __future__ import annotations

import pytest

from ventu_b2b import margen


# ───────── la garantía: el markup se cumple DESPUÉS de los costos ─────────

def test_sin_comision_el_markup_es_directo():
    c = margen.precio_para_markup(10000, 0.30, redondeo=1)
    assert c.precio == 13000
    assert c.utilidad_neta == 3000
    assert c.cumple


def test_con_comision_el_markup_sigue_cumpliendose():
    """Lo que distingue este cálculo de multiplicar por (1+markup): con una
    pasarela del 3%, cobrar 13.000 dejaría 2.610 y no 3.000."""
    c = margen.precio_para_markup(10000, 0.30, comision_pct=0.03, redondeo=1)
    assert c.precio > 13000, "debe subir el precio para absorber la comisión"
    assert c.utilidad_neta >= 3000
    assert c.cumple


def test_el_error_de_multiplicar_ingenuamente():
    """Deja explícito el tamaño del error que este módulo corrige."""
    ingenuo = margen.markup_real_a(13000, 10000, comision_pct=0.03)
    assert ingenuo is not None and ingenuo < 0.30
    assert round(ingenuo, 3) == 0.261  # 26,1% real donde se creía tener 30%


def test_el_costo_fijo_tambien_se_absorbe():
    """En Ventu 1.0 el cargo fijo se comía el margen de los articulos baratos y
    nadie lo notaba porque el precio 'tenía' su markup."""
    c = margen.precio_para_markup(1000, 0.30, comision_pct=0.03,
                                  costo_fijo=500, redondeo=1)
    assert c.utilidad_neta >= 300
    assert c.cumple


def test_articulo_barato_con_cargo_fijo_grande():
    """El caso que destapó la auditoría: sin absorber el fijo se vendería bajo
    el punto de equilibrio."""
    c = margen.precio_para_markup(500, 0.25, comision_pct=0.03,
                                  costo_fijo=1000, redondeo=1)
    assert c.utilidad_neta >= 125
    assert c.precio > 500 + 1000, "el precio debe cubrir costo y cargo fijo"


# ───────── redondeo ─────────

def test_redondea_hacia_arriba():
    """Hacia abajo se pierde margen en cada venta, y esa fuga no aparece en
    ningún informe porque cada caso es de centavos."""
    c = margen.precio_para_markup(1001, 0.30, redondeo=10)
    assert c.precio % 10 == 0
    assert c.precio >= 1001 * 1.30


def test_el_redondeo_nunca_baja_del_objetivo():
    for costo in (333, 777, 1234, 9999):
        c = margen.precio_para_markup(costo, 0.30, comision_pct=0.03, redondeo=100)
        assert c.cumple, f"costo {costo} no alcanza el markup"


# ───────── entradas inválidas ─────────

@pytest.mark.parametrize("costo", [0, -1])
def test_costo_no_positivo_se_rechaza(costo):
    with pytest.raises(margen.MargenInviable):
        margen.precio_para_markup(costo, 0.30)


@pytest.mark.parametrize("comision", [1.0, 1.5, -0.1])
def test_comision_fuera_de_rango_se_rechaza(comision):
    """Una comisión del 100% haría el denominador cero: no hay precio posible."""
    with pytest.raises(margen.MargenInviable):
        margen.precio_para_markup(10000, 0.30, comision_pct=comision)


# ───────── auditoría de un precio ya decidido ─────────

def test_margen_sobre_el_precio():
    assert margen.margen_a(13000, 10000) == pytest.approx(0.2307, abs=1e-3)


def test_margen_negativo_cuando_se_vende_a_perdida():
    m = margen.margen_a(9000, 10000)
    assert m is not None and m < 0


def test_markup_real_y_margen_responden_preguntas_distintas():
    """Confundirlos hace parecer sano un precio que no lo está: 23% sobre el
    precio es 30% sobre el costo."""
    precio, costo = 13000, 10000
    assert margen.margen_a(precio, costo) == pytest.approx(0.2307, abs=1e-3)
    assert margen.markup_real_a(precio, costo) == pytest.approx(0.30, abs=1e-3)


def test_precio_cero_no_revienta():
    assert margen.margen_a(0, 10000) is None
    assert margen.markup_real_a(0, 10000) is None


# ───────── piso para precios negociados ─────────

def test_precio_negociado_que_respeta_el_piso():
    assert margen.alcanza_el_piso(13000, 10000, 0.25) is True


def test_precio_negociado_bajo_el_piso():
    """El ejecutivo negoció demasiado: no alcanza el margen mínimo."""
    assert margen.alcanza_el_piso(11000, 10000, 0.25) is False


def test_el_piso_considera_la_comision_de_la_pasarela():
    """Un precio que parece alcanzar el piso puede no hacerlo una vez que la
    pasarela cobra lo suyo."""
    assert margen.alcanza_el_piso(12600, 10000, 0.25) is True
    assert margen.alcanza_el_piso(12600, 10000, 0.25, comision_pct=0.03) is False
