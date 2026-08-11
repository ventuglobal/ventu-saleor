"""La cantidad del carrito determina el precio unitario.

Es el comportamiento del sitio actual: la tabla de tramos vive en el producto y
al elegir la cantidad se calcula el precio de compra.
"""

from __future__ import annotations

import pytest

from ventu_b2b.cart import precios
from ventu_b2b.tiers import TramoInvalido

VAR = "UHJvZHVjdFZhcmlhbnQ6MQ=="

# Tabla fija del producto, como la de Ventu 1.0.
TABLA = "1=13240,4=8900,6=8400"


def _router(*, tramos_variante="", tramos_producto="", base=13240.0, existe=True):
    def gql(query, variables=None, **kw):
        if not existe:
            return {"data": {"productVariant": None}}
        meta = lambda v: ([{"key": precios.K_TRAMOS, "value": v}] if v else [])
        return {"data": {"productVariant": {
            "id": VAR,
            "pricing": {"price": {"gross": {"amount": base}}},
            "metadata": meta(tramos_variante),
            "product": {"metadata": meta(tramos_producto)},
        }}}
    return gql


# ───────────────── resolución por cantidad ─────────────────

@pytest.mark.parametrize("cantidad,esperado", [
    (1, 13240.0), (3, 13240.0),
    (4, 8900.0), (5, 8900.0),
    (6, 8400.0), (50, 8400.0),
])
def test_la_cantidad_determina_el_precio(monkeypatch, cantidad, esperado):
    monkeypatch.setattr(precios, "gql", _router(tramos_producto=TABLA))
    assert precios.resolver_precio(VAR, cantidad, canal="b2b-cl") == esperado


def test_producto_sin_tramos_no_fuerza_precio(monkeypatch):
    """`None` significa «usa el precio de catálogo». Devolver el precio de lista
    obligaría a sobreescribir la línea siempre, y esa sobreescritura queda
    registrada en el checkout como si hubiera habido negociación."""
    monkeypatch.setattr(precios, "gql", _router())
    assert precios.resolver_precio(VAR, 10, canal="b2b-cl") is None


def test_la_variante_manda_sobre_el_producto(monkeypatch):
    """Lo más específico gana: una variante puede tener su propia tabla."""
    monkeypatch.setattr(precios, "gql", _router(
        tramos_variante="1=9000,4=7000", tramos_producto=TABLA))
    assert precios.resolver_precio(VAR, 4, canal="b2b-cl") == 7000.0


def test_el_producto_manda_sobre_el_canal(monkeypatch):
    monkeypatch.setattr(precios, "gql", _router(tramos_producto=TABLA))
    assert precios.resolver_precio(VAR, 4, canal="b2b-cl",
                                   escalera_channel="1:1.0,4:0.5") == 8900.0


def test_sin_tabla_propia_se_usa_la_del_canal(monkeypatch):
    """Con factores, el precio base del canal sí importa."""
    monkeypatch.setattr(precios, "gql", _router(base=10000.0))
    assert precios.resolver_precio(VAR, 10, canal="b2b-cl",
                                   escalera_channel="1:1.0,10:0.9") == 9000.0


def test_variante_inexistente_no_revienta(monkeypatch):
    monkeypatch.setattr(precios, "gql", _router(existe=False))
    assert precios.resolver_precio(VAR, 5, canal="b2b-cl") is None


def test_cantidad_invalida_se_rechaza(monkeypatch):
    monkeypatch.setattr(precios, "gql", _router(tramos_producto=TABLA))
    with pytest.raises(TramoInvalido):
        precios.resolver_precio(VAR, 0, canal="b2b-cl")


def test_tabla_mal_escrita_es_ruidosa(monkeypatch):
    """No se traga una escalera inválida en silencio: quien llama decide si cae
    al precio de catálogo, pero se entera."""
    monkeypatch.setattr(precios, "gql", _router(tramos_producto="1=13240,4:0.9"))
    with pytest.raises(TramoInvalido, match="mezcla"):
        precios.resolver_precio(VAR, 4, canal="b2b-cl")


# ───────────────── incentivo de compra ─────────────────

def test_indica_cuanto_falta_para_el_siguiente_tramo(monkeypatch):
    """«Lleva 1 más y pagas $8.900 c/u» — lo que convierte la tabla en una
    herramienta de venta y no solo en un cálculo."""
    monkeypatch.setattr(precios, "gql", _router(tramos_producto=TABLA))
    assert precios.incentivo(VAR, 3, canal="b2b-cl") == {
        "faltan": 1, "desde": 4, "precio_unitario": 8900.0}


def test_en_el_mejor_tramo_no_hay_incentivo(monkeypatch):
    monkeypatch.setattr(precios, "gql", _router(tramos_producto=TABLA))
    assert precios.incentivo(VAR, 10, canal="b2b-cl") is None


def test_sin_tramos_no_hay_incentivo(monkeypatch):
    monkeypatch.setattr(precios, "gql", _router())
    assert precios.incentivo(VAR, 3, canal="b2b-cl") is None


# ───────────────── revisión de precios negociados ─────────────────

def _router_costo(costo="10000", tramos=""):
    def gql(query, variables=None, **kw):
        meta = []
        if costo:
            meta.append({"key": precios.K_COSTO, "value": costo})
        if tramos:
            meta.append({"key": precios.K_TRAMOS, "value": tramos})
        return {"data": {"productVariant": {
            "id": VAR,
            "pricing": {"price": {"gross": {"amount": 13000.0}}},
            "metadata": [],
            "product": {"metadata": meta},
        }}}
    return gql


def test_precio_negociado_sano_no_genera_aviso(monkeypatch):
    monkeypatch.setattr(precios, "gql", _router_costo())
    assert precios.revisar_negociado(VAR, 13000, canal="b2b-cl",
                                     markup_minimo=0.25) is None


def test_precio_negociado_bajo_el_piso_devuelve_el_detalle(monkeypatch):
    """Devuelve la cifra para que quien decide la vea, en vez de un rechazo
    a secas."""
    monkeypatch.setattr(precios, "gql", _router_costo())
    aviso = precios.revisar_negociado(VAR, 11000, canal="b2b-cl",
                                      markup_minimo=0.25)
    assert aviso is not None
    assert aviso["costo"] == 10000.0
    assert aviso["markup_real"] == 0.1
    assert aviso["markup_minimo"] == 0.25


def test_la_comision_de_pasarela_cuenta_en_la_revision(monkeypatch):
    """Un precio que parece alcanzar el piso puede no hacerlo una vez que la
    pasarela cobra lo suyo."""
    monkeypatch.setattr(precios, "gql", _router_costo())
    assert precios.revisar_negociado(VAR, 12600, canal="b2b-cl",
                                     markup_minimo=0.25) is None
    assert precios.revisar_negociado(VAR, 12600, canal="b2b-cl",
                                     markup_minimo=0.25, comision_pct=0.03) is not None


def test_sin_costo_publicado_no_se_juzga(monkeypatch):
    """Bloquear una venta por un dato ausente sería peor que no revisar."""
    monkeypatch.setattr(precios, "gql", _router_costo(costo=""))
    assert precios.revisar_negociado(VAR, 1, canal="b2b-cl",
                                     markup_minimo=0.25) is None


def test_costo_ilegible_no_revienta(monkeypatch):
    monkeypatch.setattr(precios, "gql", _router_costo(costo="mil pesos"))
    assert precios.costo_de(VAR, canal="b2b-cl") is None


def test_sin_piso_configurado_no_se_revisa(monkeypatch):
    """`MARKUP_MINIMO=0` desactiva la revisión."""
    monkeypatch.setattr(precios, "gql", _router_costo())
    assert precios.revisar_negociado(VAR, 1, canal="b2b-cl",
                                     markup_minimo=0) is None
