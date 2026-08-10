"""Precios por tramo de cantidad (volume pricing).

Saleor no tiene precios escalonados por cantidad: un channel-listing guarda un
precio único por variante. El precio del tramo se resuelve aquí y se aplica a la
línea del carrito mediante `price` de `CheckoutLineInput`, que Saleor sí admite.

Este módulo es **puro**: resuelve qué precio corresponde a una cantidad. No habla
con Saleor ni decide cuándo aplicarlo.

Un tramo se define por su cantidad mínima. Los tramos se ordenan y se elige el de
mayor `desde` que no supere la cantidad pedida:

    100 c/u  desde 1
     90 c/u  desde 10
     80 c/u  desde 50

    cantidad 1..9   → 100
    cantidad 10..49 →  90
    cantidad 50+    →  80
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Iterable, List, Optional, Sequence


class TramoInvalido(ValueError):
    """La definición de tramos no es utilizable."""


@dataclass(frozen=True)
class Tramo:
    """Precio unitario a partir de una cantidad mínima (inclusive)."""

    desde: int
    precio_unitario: float

    def __post_init__(self) -> None:
        if self.desde < 1:
            raise TramoInvalido(f"'desde' debe ser >= 1, recibido {self.desde}")
        if self.precio_unitario < 0:
            raise TramoInvalido(f"precio negativo: {self.precio_unitario}")


def normalizar_tramos(tramos: Iterable[Tramo]) -> List[Tramo]:
    """Ordena por cantidad y valida la escalera.

    Rechaza dos tramos con el mismo `desde` (ambigüedad: no habría forma de saber
    cuál aplica) y exige que exista un tramo base que cubra la cantidad 1, para
    que ninguna cantidad quede sin precio.
    """
    ordenados = sorted(tramos, key=lambda t: t.desde)
    if not ordenados:
        raise TramoInvalido("no hay tramos definidos")

    vistos = set()
    for t in ordenados:
        if t.desde in vistos:
            raise TramoInvalido(f"dos tramos con el mismo 'desde': {t.desde}")
        vistos.add(t.desde)

    if ordenados[0].desde != 1:
        raise TramoInvalido(
            f"falta el tramo base: el primero empieza en {ordenados[0].desde}, debería ser 1"
        )
    return ordenados


def precio_para(cantidad: int, tramos: Sequence[Tramo]) -> float:
    """Precio unitario que corresponde a `cantidad`.

    Elige el tramo de mayor `desde` que no supere la cantidad.
    """
    if cantidad < 1:
        raise TramoInvalido(f"cantidad debe ser >= 1, recibida {cantidad}")

    escalera = normalizar_tramos(tramos)
    elegido = escalera[0]
    for t in escalera:
        if t.desde <= cantidad:
            elegido = t
        else:
            break
    return elegido.precio_unitario


def total_para(cantidad: int, tramos: Sequence[Tramo]) -> float:
    """Total de la línea: precio del tramo por la cantidad.

    El tramo aplica a **todas** las unidades de la línea, no solo a las que
    exceden el mínimo. Es el modelo habitual en distribución mayorista y el que
    usa el sitio actual.
    """
    unitario = Decimal(str(precio_para(cantidad, tramos)))
    return float(unitario * Decimal(cantidad))


def siguiente_tramo(cantidad: int, tramos: Sequence[Tramo]) -> Optional[Tramo]:
    """Próximo tramo por alcanzar, o `None` si ya está en el mejor.

    Sirve para incentivar la compra: «lleva 3 más y pagas $90 c/u».
    """
    escalera = normalizar_tramos(tramos)
    for t in escalera:
        if t.desde > cantidad:
            return t
    return None


# ─────────────── escalera por channel (factores) ───────────────

def parsear_escalera(crudo: str) -> List[tuple]:
    """`"1:1.0,10:0.9,50:0.8"` → [(1, 1.0), (10, 0.9), (50, 0.8)].

    La escalera se define por **factores** sobre el precio del channel, no por
    montos: así una misma regla («desde 10 unidades, 10% menos») sirve para todo
    el catálogo sin repetir precios producto por producto.

    Cadena vacía significa "este channel no tiene tramos" y devuelve lista vacía,
    que es distinto de una escalera inválida: lo primero es una configuración
    legítima, lo segundo un error que debe ser ruidoso.
    """
    if not crudo or not crudo.strip():
        return []

    pares: List[tuple] = []
    for trozo in crudo.split(","):
        trozo = trozo.strip()
        if not trozo:
            continue
        if ":" not in trozo:
            raise TramoInvalido(f"tramo sin ':' → {trozo!r}")
        izq, der = trozo.split(":", 1)
        try:
            desde, factor = int(izq.strip()), float(der.strip())
        except ValueError as exc:
            raise TramoInvalido(f"tramo no numérico → {trozo!r}") from exc
        if desde < 1:
            raise TramoInvalido(f"'desde' debe ser >= 1 → {trozo!r}")
        if factor <= 0:
            raise TramoInvalido(f"factor debe ser > 0 → {trozo!r}")
        pares.append((desde, factor))

    vistos = [d for d, _ in pares]
    if len(set(vistos)) != len(vistos):
        raise TramoInvalido(f"cantidades duplicadas en la escalera: {crudo!r}")
    return sorted(pares)


def escalera_a_tramos(precio_base: float, crudo: str) -> List[Tramo]:
    """Convierte la escalera de factores en tramos con precio del producto.

    `precio_base` es el precio unitario del channel; cada factor lo escala.
    """
    pares = parsear_escalera(crudo)
    if not pares:
        return []
    tramos = [Tramo(desde=d, precio_unitario=round(precio_base * f, 2)) for d, f in pares]
    return normalizar_tramos(tramos)
