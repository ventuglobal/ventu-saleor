"""Margen neto garantizado sobre el costo.

Portado de `pricing/markup_engine.py` de Ventu 1.0. Lo que se trae no es el
cálculo de MercadoLibre —flete, comisión por tramos, fijo por umbral— sino la
idea que lo sostiene:

    precio = (costo × (1 + markup) + costos_por_venta) / (1 − comisión%)

Dos cosas la hacen distinta de multiplicar el costo por el markup:

1. **Los costos por venta van al numerador.** En Ventu 1.0 esto fue un arreglo
   posterior, después de auditar órdenes y descubrir que los artículos baratos se
   estaban vendiendo bajo el punto de equilibrio: el cargo fijo se comía el
   margen entero y nadie lo veía porque el precio "tenía" su markup.

2. **Se resuelve iterando**, porque la comisión se calcula sobre el precio final
   y el precio final depende de la comisión. Multiplicar el costo por (1+markup)
   y restar la comisión después da un margen menor al buscado — la diferencia
   crece justo donde el margen es más ajustado.

En B2B no hay comisión de marketplace, pero **sí hay comisión de pasarela**:
Webpay cobra un porcentaje de cada venta. Sin esto, un markup del 30% con una
pasarela del 3% deja 26,1% real, y el error pasa inadvertido porque el precio
publicado sí tiene el markup declarado.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Optional

# Tope de iteraciones. Converge en 3–4; el resto es cinturón de seguridad para
# que una configuración absurda no cuelgue el proceso.
MAX_ITER = 15


class MargenInviable(ValueError):
    """No existe precio que alcance el margen pedido."""


@dataclass(frozen=True)
class Cotizacion:
    precio: int           # redondeado hacia arriba
    costo: int
    markup: float         # markup pedido sobre el costo
    comision_pct: float
    comision_monto: int
    costo_fijo: int
    utilidad_neta: int    # lo que queda después de todos los costos por venta
    markup_real: float    # utilidad_neta / costo — la verificación

    @property
    def cumple(self) -> bool:
        """¿El precio alcanza el markup pedido?

        Se compara contra el markup pedido con una tolerancia de un peso por el
        redondeo, no contra cero: un precio puede tener utilidad positiva y aun
        así quedar bajo el objetivo.
        """
        return self.utilidad_neta >= int(self.markup * self.costo) - 1


def precio_para_markup(costo: int, markup: float, *, comision_pct: float = 0.0,
                       costo_fijo: int = 0, redondeo: int = 10) -> Cotizacion:
    """Precio que deja `markup × costo` de utilidad **después** de los costos.

    `comision_pct` es la de la pasarela (Webpay ronda el 3%); `costo_fijo`, todo
    cargo por transacción que no dependa del monto.

    Redondea **hacia arriba**: hacia abajo se pierde margen en cada venta, y ese
    tipo de fuga no aparece en ningún informe porque cada caso individual es de
    centavos.
    """
    costo = int(costo or 0)
    if costo <= 0:
        raise MargenInviable(f"costo debe ser > 0, recibido {costo}")
    if not 0.0 <= comision_pct < 1.0:
        # Una comisión del 100% haría el denominador cero: no hay precio posible.
        raise MargenInviable(f"comisión fuera de rango: {comision_pct}")

    objetivo = costo * (1.0 + markup)
    denom = 1.0 - comision_pct
    precio = (objetivo + costo_fijo) / denom

    for _ in range(MAX_ITER):
        nuevo = (objetivo + costo_fijo) / denom
        if abs(nuevo - precio) < 1.0:
            precio = nuevo
            break
        precio = nuevo

    precio_r = int(math.ceil(precio / redondeo) * redondeo)
    return _cotizar(precio_r, costo, markup, comision_pct, costo_fijo)


def _cotizar(precio: int, costo: int, markup: float, comision_pct: float,
             costo_fijo: int) -> Cotizacion:
    comision = int(round(comision_pct * precio)) + costo_fijo
    neta = precio - comision - costo
    return Cotizacion(
        precio=precio, costo=costo, markup=markup,
        comision_pct=comision_pct, comision_monto=comision, costo_fijo=costo_fijo,
        utilidad_neta=neta, markup_real=neta / costo if costo else 0.0,
    )


def margen_a(precio: int, costo: int, *, comision_pct: float = 0.0,
             costo_fijo: int = 0) -> Optional[float]:
    """Margen real sobre el precio. Negativo = se vende a pérdida.

    Sirve para auditar un precio ya decidido —el que un ejecutivo negoció en una
    conversación— en vez de calcularlo desde el costo.
    """
    if precio <= 0:
        return None
    comision = int(round(comision_pct * precio)) + costo_fijo
    return (precio - comision - int(costo or 0)) / precio


def markup_real_a(precio: int, costo: int, *, comision_pct: float = 0.0,
                  costo_fijo: int = 0) -> Optional[float]:
    """Utilidad neta sobre el costo a un precio dado.

    Es la cifra que hay que comparar contra el markup objetivo: el margen sobre
    el precio (`margen_a`) responde otra pregunta y confundirlos hace parecer
    sano un precio que no lo está.
    """
    costo = int(costo or 0)
    if costo <= 0 or precio <= 0:
        return None
    comision = int(round(comision_pct * precio)) + costo_fijo
    return (precio - comision - costo) / costo


def alcanza_el_piso(precio: int, costo: int, markup_minimo: float, *,
                    comision_pct: float = 0.0, costo_fijo: int = 0) -> bool:
    """¿Este precio deja al menos `markup_minimo` de utilidad sobre el costo?

    La usa el carrito para revisar un precio negociado antes de fijarlo.
    """
    real = markup_real_a(precio, costo, comision_pct=comision_pct,
                         costo_fijo=costo_fijo)
    return real is not None and real >= markup_minimo
