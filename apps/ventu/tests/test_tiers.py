"""Tests de precios por tramo: puros, sin red."""

from __future__ import annotations

import pytest

from ventu.pricing import tiers

from ventu.pricing.tiers import (
    Tramo,
    TramoInvalido,
    escalera_a_tramos,
    normalizar_tramos,
    parsear_escalera,
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


# ─────────────── escalera por channel ───────────────

def _esc(s):
    return parsear_escalera(s)


def test_parsea_escalera_ordenada():
    assert _esc("1:1.0,10:0.9,50:0.8") == [(1, 1.0, True), (10, 0.9, True), (50, 0.8, True)]


def test_parsea_escalera_desordenada_queda_ordenada():
    assert _esc("50:0.8,1:1.0,10:0.9") == [(1, 1.0, True), (10, 0.9, True), (50, 0.8, True)]


def test_channel_sin_tramos_no_es_error():
    """Cadena vacía es configuración legítima, no escalera inválida."""
    assert _esc("") == []
    assert _esc("   ") == []


@pytest.mark.parametrize("malo", ["10", "10:", "a:1.0", "10:x", "0:1.0", "10:0", "10:-1"])
def test_escalera_invalida_es_ruidosa(malo):
    with pytest.raises(TramoInvalido):
        _esc(malo)


def test_rechaza_cantidades_duplicadas():
    with pytest.raises(TramoInvalido, match="duplicadas"):
        _esc("10:0.9,10:0.8")


def test_escalera_a_tramos_aplica_factores_al_precio():
    t = escalera_a_tramos(1000.0, "1:1.0,10:0.9,50:0.8")
    assert [(x.desde, x.precio_unitario) for x in t] == [(1, 1000.0), (10, 900.0), (50, 800.0)]


def test_escalera_a_tramos_respeta_los_cortes():
    t = escalera_a_tramos(1000.0, "1:1.0,10:0.9,50:0.8")
    assert precio_para(9, t) == 1000.0
    assert precio_para(10, t) == 900.0
    assert precio_para(50, t) == 800.0


def test_sin_escalera_no_hay_tramos():
    assert escalera_a_tramos(1000.0, "") == []


# ───────── reglas heredadas de PriceTier (Ventu 1.0) ─────────

def test_comprar_mas_nunca_cuesta_mas_por_unidad():
    """Una escalera que encarece al comprar más no es un descuento por volumen:
    suele ser un dedo cambiado, y el cliente lo vería como un castigo."""
    with pytest.raises(TramoInvalido, match="más barato"):
        normalizar_tramos([Tramo(desde=1, precio_unitario=100.0),
                           Tramo(desde=10, precio_unitario=120.0)])


def test_rechaza_tramos_de_igual_precio():
    """Dos tramos al mismo precio no describen un descuento; es configuración
    incompleta que aparenta funcionar."""
    with pytest.raises(TramoInvalido, match="más barato"):
        normalizar_tramos([Tramo(desde=1, precio_unitario=100.0),
                           Tramo(desde=10, precio_unitario=100.0)])


def test_ningun_tramo_puede_quedar_bajo_el_costo():
    """La regla que impide que un descuento por volumen venda a pérdida. El error
    no se nota hasta que alguien revisa el margen del mes."""
    with pytest.raises(TramoInvalido, match="bajo el costo"):
        normalizar_tramos([Tramo(desde=1, precio_unitario=100.0),
                           Tramo(desde=50, precio_unitario=40.0)],
                          costo_unitario=50.0)


def test_el_piso_de_costo_es_opcional():
    """No todos los llamadores conocen el costo; la escalera se valida igual."""
    assert len(normalizar_tramos(ESCALERA)) == 3


def test_tramo_exactamente_en_el_costo_se_acepta():
    """Vender al costo es una decisión comercial válida (liquidación); vender
    bajo el costo casi nunca lo es."""
    t = normalizar_tramos([Tramo(desde=1, precio_unitario=100.0),
                           Tramo(desde=10, precio_unitario=50.0)],
                          costo_unitario=50.0)
    assert t[-1].precio_unitario == 50.0


def test_escalera_valida_el_piso_de_costo():
    with pytest.raises(TramoInvalido, match="bajo el costo"):
        escalera_a_tramos(1000.0, "1:1.0,50:0.4", costo_unitario=500.0)


def test_escalera_creciente_se_rechaza():
    with pytest.raises(TramoInvalido, match="más barato"):
        escalera_a_tramos(1000.0, "1:1.0,10:1.1")


# ───────── escalera por producto (modelo de Ventu 1.0) ─────────

def test_el_producto_manda_sobre_el_channel():
    """Ventu 1.0 define los tramos por producto; el channel es solo el defecto."""
    t = tiers.escalera_para(1000.0, del_producto="1:1.0,5:0.8",
                            del_channel="1:1.0,10:0.9")
    assert [(x.desde, x.precio_unitario) for x in t] == [(1, 1000.0), (5, 800.0)]


def test_sin_escalera_de_producto_se_usa_la_del_channel():
    t = tiers.escalera_para(1000.0, del_producto="", del_channel="1:1.0,10:0.9")
    assert [(x.desde, x.precio_unitario) for x in t] == [(1, 1000.0), (10, 900.0)]


def test_sin_ninguna_escalera_no_hay_tramos():
    assert tiers.escalera_para(1000.0) == []


def test_la_escalera_del_producto_tambien_respeta_el_piso_de_costo():
    with pytest.raises(TramoInvalido, match="bajo el costo"):
        tiers.escalera_para(1000.0, del_producto="1:1.0,10:0.3", costo_unitario=600.0)


# ───────── tabla fija por producto (como Ventu 1.0) ─────────

def test_lee_montos_absolutos():
    """Ventu 1.0 guarda el precio literal por producto y cantidad, porque cada
    monto es una decisión comercial y no siempre es un porcentaje redondo."""
    assert _esc("1=13240,4=8900,6=8400") == [
        (1, 13240.0, False), (4, 8900.0, False), (6, 8400.0, False)]


def test_los_montos_no_dependen_del_precio_base():
    """Con montos, el precio del channel se ignora: cada tramo ya trae el suyo."""
    t = escalera_a_tramos(999999.0, "1=13240,4=8900,6=8400")
    assert [(x.desde, x.precio_unitario) for x in t] == [
        (1, 13240.0), (4, 8900.0), (6, 8400.0)]


def test_resuelve_el_precio_segun_la_cantidad_del_carrito():
    """Es el comportamiento del sitio actual: la cantidad elegida determina el
    precio unitario de la compra."""
    t = escalera_a_tramos(0, "1=13240,4=8900,6=8400")
    assert precio_para(1, t) == 13240.0
    assert precio_para(3, t) == 13240.0
    assert precio_para(4, t) == 8900.0
    assert precio_para(5, t) == 8900.0
    assert precio_para(6, t) == 8400.0
    assert precio_para(20, t) == 8400.0


def test_no_se_pueden_mezclar_montos_y_factores():
    """Un ':' donde iba un '=' daría un precio 8.900 veces mayor sin que nada
    falle, así que la mezcla se rechaza."""
    with pytest.raises(TramoInvalido, match="mezcla"):
        _esc("1=13240,4:0.9")


def test_los_montos_tambien_respetan_la_monotonia():
    with pytest.raises(TramoInvalido, match="más barato"):
        escalera_a_tramos(0, "1=8900,4=9500")


def test_los_montos_tambien_respetan_el_piso_de_costo():
    with pytest.raises(TramoInvalido, match="bajo el costo"):
        escalera_a_tramos(0, "1=13240,6=4000", costo_unitario=5000.0)
