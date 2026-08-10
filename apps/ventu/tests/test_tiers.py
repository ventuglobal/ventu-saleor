"""Tests de precios por tramo: puros, sin red."""

from __future__ import annotations

import pytest

from ventu.pricing.tiers import (
    Tramo,
    TramoInvalido,
    normalizar_tramos,
    precio_para,
    siguiente_tramo,
    total_para,
)

# 1-9 → 100 | 10-49 → 90 | 50+ → 80
ESCALERA = [Tramo(desde=1, precio_unitario=100.0),
            Tramo(desde=10, precio_unitario=90.0),
            Tramo(desde=50, precio_unitario=80.0)]


# ───────────────────────── resolución del tramo ─────────────────────────

@pytest.mark.parametrize("cantidad,esperado", [
    (1, 100.0), (9, 100.0),        # tramo base
    (10, 90.0), (49, 90.0),        # tramo medio
    (50, 80.0), (500, 80.0),       # tramo alto
])
def test_precio_por_cantidad(cantidad, esperado):
    assert precio_para(cantidad, ESCALERA) == esperado


def test_los_bordes_son_inclusivos():
    """La cantidad mínima de un tramo ya paga ese tramo.

    Es el error clásico: comprar 10 y seguir pagando el precio de 9.
    """
    assert precio_para(9, ESCALERA) == 100.0
    assert precio_para(10, ESCALERA) == 90.0
    assert precio_para(49, ESCALERA) == 90.0
    assert precio_para(50, ESCALERA) == 80.0


def test_el_orden_de_definicion_no_importa():
    desordenada = [ESCALERA[2], ESCALERA[0], ESCALERA[1]]
    assert precio_para(25, desordenada) == 90.0


# ───────────────────────── total de la línea ─────────────────────────

def test_el_tramo_aplica_a_todas_las_unidades():
    """No es escalonado por franjas: 50 unidades pagan 80 c/u, no un mixto."""
    assert total_para(50, ESCALERA) == 4000.0
    assert total_para(10, ESCALERA) == 900.0
    assert total_para(9, ESCALERA) == 900.0


def test_comprar_una_unidad_mas_puede_salir_mas_barato():
    """Consecuencia real de este modelo: 9 unidades cuestan lo mismo que 10.

    Documentado a propósito: es lo esperado en distribución mayorista y conviene
    que quede explícito para no confundirlo con un error de cálculo.
    """
    assert total_para(9, ESCALERA) == total_para(10, ESCALERA) == 900.0


# ───────────────────────── validación de la escalera ─────────────────────────

def test_exige_tramo_base():
    """Sin tramo desde 1, una cantidad pequeña quedaría sin precio."""
    with pytest.raises(TramoInvalido, match="tramo base"):
        precio_para(5, [Tramo(desde=10, precio_unitario=90.0)])


def test_rechaza_tramos_duplicados():
    with pytest.raises(TramoInvalido, match="mismo 'desde'"):
        normalizar_tramos([Tramo(desde=1, precio_unitario=100.0),
                           Tramo(desde=1, precio_unitario=80.0)])


def test_rechaza_escalera_vacia():
    with pytest.raises(TramoInvalido, match="no hay tramos"):
        normalizar_tramos([])


def test_rechaza_desde_invalido():
    with pytest.raises(TramoInvalido, match="'desde'"):
        Tramo(desde=0, precio_unitario=100.0)


def test_rechaza_precio_negativo():
    with pytest.raises(TramoInvalido, match="negativo"):
        Tramo(desde=1, precio_unitario=-1.0)


def test_rechaza_cantidad_invalida():
    with pytest.raises(TramoInvalido, match="cantidad"):
        precio_para(0, ESCALERA)


# ───────────────────────── incentivo de compra ─────────────────────────

def test_siguiente_tramo_para_incentivar():
    assert siguiente_tramo(7, ESCALERA) == Tramo(desde=10, precio_unitario=90.0)
    assert siguiente_tramo(10, ESCALERA) == Tramo(desde=50, precio_unitario=80.0)


def test_en_el_mejor_tramo_no_hay_siguiente():
    assert siguiente_tramo(50, ESCALERA) is None
    assert siguiente_tramo(999, ESCALERA) is None
