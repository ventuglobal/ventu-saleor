"""Precios por tramo de cantidad (volume pricing).

Copia literal de `apps/ventu/pricing/tiers.py`: es un módulo puro y sin
dependencias, y la app B2B necesita resolver el mismo precio que Pricing publica.
Si divergen, el carrito cobraría distinto de lo publicado.

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


def normalizar_tramos(tramos: Iterable[Tramo], *,
                      costo_unitario: Optional[float] = None) -> List[Tramo]:
    """Ordena por cantidad y valida la escalera.

    Las dos últimas reglas vienen del modelo `PriceTier` de Ventu 1.0, donde se
    aplicaban al guardar desde el admin:

    1. Sin `desde` duplicados: no habría forma de saber cuál tramo aplica.
    2. Debe existir un tramo base en 1, para que ninguna cantidad quede sin precio.
    3. **Monotonía**: a mayor cantidad, menor precio unitario. Una escalera que
       encarece al comprar más no es un descuento por volumen; suele ser un dedo
       cambiado en la configuración y el cliente lo vería como un castigo.
    4. **Piso de costo**: ningún tramo por debajo del costo. Es la regla que
       impide que un descuento por volumen termine vendiendo a pérdida — el error
       no se nota hasta que alguien revisa el margen del mes.

    `costo_unitario` es opcional porque no todos los llamadores lo conocen: la
    escalera se valida igual, solo que sin el piso.
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

    for anterior, siguiente in zip(ordenados, ordenados[1:]):
        if siguiente.precio_unitario >= anterior.precio_unitario:
            raise TramoInvalido(
                f"el tramo desde {siguiente.desde} ({siguiente.precio_unitario}) no es "
                f"más barato que el de {anterior.desde} ({anterior.precio_unitario}): "
                "comprar más nunca debe costar más por unidad"
            )

    if costo_unitario is not None:
        for t in ordenados:
            if t.precio_unitario < costo_unitario:
                raise TramoInvalido(
                    f"el tramo desde {t.desde} ({t.precio_unitario}) queda bajo el "
                    f"costo unitario ({costo_unitario}): sería vender a pérdida"
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
    """Lee una escalera en cualquiera de sus dos notaciones.

    Ventu 1.0 define los tramos como **precios absolutos por producto** —una
    tabla fija: «este producto, a 4 unidades, vale $8.900»— porque cada monto es
    una decisión comercial y no siempre corresponde a un porcentaje redondo.

        "1=13240,4=8900,6=8400"      → montos, uno por tramo

    La notación por **factor** existe para el caso opuesto: una regla única que
    sirve para todo el catálogo sin cargarla producto por producto.

        "1:1.0,10:0.9,50:0.8"        → factores sobre el precio del channel

    Devuelve `[(desde, valor, es_factor)]`.

    **No se permite mezclar** ambas notaciones en una misma escalera: un
    `4:8900` (factor 8900) junto a un `6=8400` casi siempre es un `:` donde iba
    un `=`, y el resultado sería un precio 8.900 veces mayor sin que nada falle.
    """
    if not crudo or not crudo.strip():
        return []

    pares: List[tuple] = []
    for trozo in crudo.split(","):
        trozo = trozo.strip()
        if not trozo:
            continue
        if "=" in trozo:
            izq, der = trozo.split("=", 1)
            es_factor = False
        elif ":" in trozo:
            izq, der = trozo.split(":", 1)
            es_factor = True
        else:
            raise TramoInvalido(f"tramo sin ':' ni '=' → {trozo!r}")

        try:
            desde, valor = int(izq.strip()), float(der.strip())
        except ValueError as exc:
            raise TramoInvalido(f"tramo no numérico → {trozo!r}") from exc
        if desde < 1:
            raise TramoInvalido(f"'desde' debe ser >= 1 → {trozo!r}")
        if valor <= 0:
            raise TramoInvalido(f"el valor debe ser > 0 → {trozo!r}")
        pares.append((desde, valor, es_factor))

    vistos = [d for d, _, _ in pares]
    if len(set(vistos)) != len(vistos):
        raise TramoInvalido(f"cantidades duplicadas en la escalera: {crudo!r}")

    notaciones = {f for _, _, f in pares}
    if len(notaciones) > 1:
        raise TramoInvalido(
            f"la escalera mezcla montos (=) y factores (:): {crudo!r}. "
            "Casi siempre es un ':' donde iba un '='"
        )
    return sorted(pares)


def escalera_a_tramos(precio_base: float, crudo: str, *,
                      costo_unitario: Optional[float] = None) -> List[Tramo]:
    """Convierte la escalera de factores en tramos con precio del producto.

    `precio_base` es el precio unitario del channel y solo se usa cuando la
    escalera está en factores; con montos absolutos se ignora, porque cada tramo
    ya trae su precio.
    """
    pares = parsear_escalera(crudo)
    if not pares:
        return []
    tramos = [
        Tramo(desde=d,
              precio_unitario=round(precio_base * v, 2) if es_factor else round(v, 2))
        for d, v, es_factor in pares
    ]
    return normalizar_tramos(tramos, costo_unitario=costo_unitario)


# ─────────── escalera por producto (modelo de Ventu 1.0) ───────────

def escalera_para(precio_base: float, *, del_producto: str = "",
                  del_channel: str = "",
                  costo_unitario: Optional[float] = None) -> List[Tramo]:
    """Tramos aplicables a un producto: los suyos, o los del channel.

    Ventu 1.0 define los tramos **por producto** (`PriceTier`, con una fila por
    cantidad), mientras que aquí el channel trae una escalera por defecto. Ambas
    cosas conviven: la del producto gana cuando existe.

    El motivo de conservar la del channel es que definirla producto por producto
    no escala a 22.765 artículos; la del producto existe porque hay casos —un
    proveedor con su propia política, un artículo de margen ajustado— donde la
    regla general no sirve.

    Una cadena vacía en ambos lados significa "sin tramos", que es configuración
    válida y distinta de una escalera mal escrita.
    """
    crudo = del_producto.strip() if del_producto else ""
    if not crudo:
        crudo = del_channel.strip() if del_channel else ""
    if not crudo:
        return []
    return escalera_a_tramos(precio_base, crudo, costo_unitario=costo_unitario)
