"""Resolución del precio de una línea según la cantidad.

Reproduce el comportamiento del sitio actual: la tabla de tramos vive en el
producto y la **cantidad elegida en el carrito determina el precio unitario**.

La tabla se guarda en la metadata del producto en Saleor, así que Pricing la
publica y la App B2B la lee: una sola fuente, sin duplicar la escalera.
"""

from __future__ import annotations

from typing import List, Optional, Tuple

from .. import config
from ..saleor_client import SaleorRespuestaError, data_errors, gql, payload
from ..margen import markup_real_a
from ..tiers import Tramo, TramoInvalido, escalera_a_tramos, precio_para, siguiente_tramo

# Claves en `privateMetadata`. Formato de la escalera: "1=13240,4=8900,6=8400"
# (montos) o "1:1.0,10:0.9" (factores). Ver `ventu_b2b.tiers`.
K_TRAMOS = "ventu.pricing.tramos"

# La tabla de tramos y el costo viven en `privateMetadata`, no en `metadata`:
# la metadata de producto se lee SIN autenticación, así que publicar ahí la
# escalera la haría visible a cualquiera —incluido un cliente retail o un
# competidor— y el costo quedaría directamente expuesto.
#
# `quantityAvailable` se pide para no ofrecer tramos que no se pueden cumplir.
#
# El precio viene neto y bruto, junto con cómo el channel ingresa sus precios,
# porque el precio de un tramo se escribe en la línea como `price` y Saleor lo
# toma como si fuera el de lista: si el channel ingresa precios sin IVA
# (b2b-cl, ver docs/b2b/lanzamiento.md §d), le suma el IVA encima. Calcular el
# tramo sobre el bruto cobraría el IVA dos veces. `taxConfiguration` exige un
# token de app o de staff, que es lo que usa esta consulta.
_VARIANTE = """
query($id: ID!, $channel: String!) {
  productVariant(id: $id, channel: $channel) {
    id
    quantityAvailable
    pricing { price { net { amount } gross { amount } } }
    product { privateMetadata { key value } }
    privateMetadata { key value }
  }
  channel(slug: $channel) { taxConfiguration { pricesEnteredWithTax } }
}
"""


def _pares(meta) -> dict:
    return {p["key"]: p["value"] for p in (meta or [])}


def _leer(variant_id: str, canal: str) -> dict:
    body = gql(_VARIANTE, {"id": variant_id, "channel": canal},
               token=config.SALEOR_PRODUCTS_TOKEN)
    if data_errors(body):
        raise SaleorRespuestaError(f"lectura de variante: {data_errors(body)}")
    return payload(body)


def _bases(datos: dict) -> Tuple[float, float]:
    """`(precio de entrada, factor para mostrar)` de la variante en el channel.

    El de entrada es el que Saleor espera en `price` de una línea: el neto si
    el channel ingresa precios sin IVA, el bruto si los ingresa con IVA. Los
    tramos se calculan y se escriben en esa base.

    El factor lleva un precio de entrada a lo que muestra la ficha (el bruto):
    así la tabla y el incentivo se leen igual que el precio de al lado, y
    coinciden con lo que el carrito termina cobrando.

    Sin dato del channel se asume precio con IVA, que es lo que Saleor usa por
    omisión en una configuración de impuestos nueva.
    """
    v = datos.get("productVariant") or {}
    precio = ((v.get("pricing") or {}).get("price")) or {}
    bruto = float((precio.get("gross") or {}).get("amount") or 0.0)
    neto = float((precio.get("net") or {}).get("amount") or 0.0) or bruto
    impuestos = ((datos.get("channel") or {}).get("taxConfiguration")) or {}
    entrada = neto if impuestos.get("pricesEnteredWithTax") is False else bruto
    return entrada, (bruto / entrada if entrada else 1.0)


def _tramos(datos: dict, *, escalera_channel: str,
            stock_minimo: int) -> Tuple[List[Tramo], float]:
    """Tramos alcanzables en la base de entrada del channel, y el factor para
    mostrarlos (ver `_bases`). Sin variante o sin escalera, ninguno."""
    v = datos.get("productVariant")
    if not v:
        return [], 1.0
    crudo = (_pares(v.get("privateMetadata")).get(K_TRAMOS)
             or _pares((v.get("product") or {}).get("privateMetadata")).get(K_TRAMOS)
             or escalera_channel
             or "")
    if not crudo.strip():
        return [], 1.0
    entrada, a_vista = _bases(datos)
    tramos = tramos_alcanzables(escalera_a_tramos(entrada, crudo),
                                v.get("quantityAvailable"), minimo=stock_minimo)
    return tramos, a_vista


def tramos_alcanzables(tramos, disponible: Optional[int], *, minimo: int = 0):
    """Descarta los tramos que el stock no permite cumplir.

    Ofrecer «50 unidades a $8.400» con 12 en bodega es una promesa que el
    checkout va a rechazar: el cliente ve el precio, arma el pedido y recién ahí
    descubre que no hay. Peor en B2B, donde la cantidad es el motivo de la
    compra.

    `minimo` suprime la tabla completa cuando queda poco stock: por debajo de ese
    umbral no tiene sentido publicar precios por volumen.
    """
    if disponible is None:
        # Sin dato de stock no se filtra: es preferible mostrar la tabla que
        # ocultarla por una consulta incompleta.
        return tramos
    if disponible < max(minimo, 1):
        return []
    return [t for t in tramos if t.desde <= disponible]


def resolver_precio(variant_id: str, cantidad: int, *, canal: str,
                    escalera_channel: str = "",
                    stock_minimo: int = 0) -> Optional[float]:
    """Precio unitario para esa cantidad, o `None` si el producto no tiene tramos.

    `None` significa "usa el precio de catálogo": no es un error, es el caso
    normal de un producto sin escalera. Devolver el precio de lista aquí
    obligaría a fijar `price` en la línea siempre, y una sobreescritura
    innecesaria queda registrada en el checkout como si hubiera negociación.

    La escalera de la variante gana sobre la del producto, y ambas sobre la del
    channel: lo más específico manda.

    El precio vuelve en la base de entrada del channel (neto en b2b-cl), que es
    la que espera `price` en la línea del checkout.
    """
    if cantidad < 1:
        raise TramoInvalido(f"cantidad debe ser >= 1, recibida {cantidad}")

    tramos, _ = _tramos(_leer(variant_id, canal), escalera_channel=escalera_channel,
                        stock_minimo=stock_minimo)
    if not tramos:
        return None
    return precio_para(cantidad, tramos)


def incentivo(variant_id: str, cantidad: int, *, canal: str,
              escalera_channel: str = "", stock_minimo: int = 0) -> Optional[dict]:
    """Próximo tramo por alcanzar: «lleva N más y pagas $X c/u».

    Es lo que convierte la tabla de tramos en una herramienta de venta y no solo
    en un cálculo. El precio va como lo muestra la ficha (ver `_bases`).
    """
    tramos, a_vista = _tramos(_leer(variant_id, canal), escalera_channel=escalera_channel,
                              stock_minimo=stock_minimo)
    if not tramos:
        return None
    prox = siguiente_tramo(cantidad, tramos)
    if not prox:
        return None
    return {"faltan": prox.desde - cantidad, "desde": prox.desde,
            "precio_unitario": round(prox.precio_unitario * a_vista, 2)}


# ─────────── revisión de precios negociados ───────────

# Costo unitario. Va en `privateMetadata` por razones obvias: publicarlo en
# `metadata` lo dejaría legible sin autenticación, y con él el margen de Ventu.
K_COSTO = "ventu.pricing.costo"


def costo_de(variant_id: str, *, canal: str) -> Optional[float]:
    """Costo unitario publicado del producto, o `None` si no lo tiene."""
    v = _leer(variant_id, canal).get("productVariant")
    if not v:
        return None
    crudo = (_pares(v.get("privateMetadata")).get(K_COSTO)
             or _pares((v.get("product") or {}).get("privateMetadata")).get(K_COSTO))
    if not crudo:
        return None
    try:
        return float(crudo)
    except ValueError:
        return None


def revisar_negociado(variant_id: str, precio: float, *, canal: str,
                      markup_minimo: float, comision_pct: float = 0.0) -> Optional[dict]:
    """¿Este precio negociado deja el margen mínimo?

    Devuelve `None` cuando no hay nada que objetar —o cuando falta el costo y no
    se puede juzgar—. Si el precio queda bajo el piso, devuelve el detalle para
    que quien decide vea la cifra en vez de un rechazo a secas.

    No bloquea por sí sola: cerrar una venta ajustada puede ser una decisión
    comercial legítima. Lo que no debe pasar es que ocurra sin que nadie lo sepa.
    """
    if markup_minimo <= 0:
        return None
    costo = costo_de(variant_id, canal=canal)
    if costo is None or costo <= 0:
        return None

    real = markup_real_a(int(precio), int(costo), comision_pct=comision_pct)
    if real is None or real >= markup_minimo:
        return None
    return {
        "costo": costo,
        "precio": precio,
        "markup_real": round(real, 4),
        "markup_minimo": markup_minimo,
        "comision_pct": comision_pct,
    }


def tabla_visible(variant_id: str, *, canal: str, escalera_channel: str = "",
                  stock_minimo: int = 0) -> list:
    """Tramos aplicables, listos para mostrar.

    Devuelve solo cantidad y precio: el costo y el margen nunca salen de aquí,
    ni siquiera hacia una empresa registrada.

    Los precios van como los muestra la ficha, junto al precio de lista (el
    bruto): la línea se cobra en la base de entrada y Saleor le suma el IVA,
    así que lo que se ve aquí es lo que termina pagando (ver `_bases`).
    """
    tramos, a_vista = _tramos(_leer(variant_id, canal), escalera_channel=escalera_channel,
                              stock_minimo=stock_minimo)
    return [{"desde": t.desde, "precio_unitario": round(t.precio_unitario * a_vista, 2)}
            for t in tramos]
