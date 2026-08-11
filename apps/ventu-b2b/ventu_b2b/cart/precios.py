"""Resolución del precio de una línea según la cantidad.

Reproduce el comportamiento del sitio actual: la tabla de tramos vive en el
producto y la **cantidad elegida en el carrito determina el precio unitario**.

La tabla se guarda en la metadata del producto en Saleor, así que Pricing la
publica y la App B2B la lee: una sola fuente, sin duplicar la escalera.
"""

from __future__ import annotations

from typing import Optional

from ..saleor_client import data_errors, gql, payload
from ..margen import markup_real_a
from ..tiers import TramoInvalido, escalera_a_tramos, precio_para, siguiente_tramo

# Claves en `privateMetadata`. Formato de la escalera: "1=13240,4=8900,6=8400"
# (montos) o "1:1.0,10:0.9" (factores). Ver `ventu_b2b.tiers`.
K_TRAMOS = "ventu.pricing.tramos"

# La tabla de tramos y el costo viven en `privateMetadata`, no en `metadata`:
# la metadata de producto se lee SIN autenticación, así que publicar ahí la
# escalera la haría visible a cualquiera —incluido un cliente retail o un
# competidor— y el costo quedaría directamente expuesto.
#
# `quantityAvailable` se pide para no ofrecer tramos que no se pueden cumplir.
_VARIANTE = """
query($id: ID!, $channel: String!) {
  productVariant(id: $id, channel: $channel) {
    id
    quantityAvailable
    pricing { price { gross { amount } } }
    product { privateMetadata { key value } }
    privateMetadata { key value }
  }
}
"""


def _pares(meta) -> dict:
    return {p["key"]: p["value"] for p in (meta or [])}


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
    """
    if cantidad < 1:
        raise TramoInvalido(f"cantidad debe ser >= 1, recibida {cantidad}")

    body = gql(_VARIANTE, {"id": variant_id, "channel": canal})
    if data_errors(body):
        raise RuntimeError(f"lectura de variante: {data_errors(body)}")

    v = payload(body).get("productVariant")
    if not v:
        return None

    crudo = (_pares(v.get("privateMetadata")).get(K_TRAMOS)
             or _pares((v.get("product") or {}).get("privateMetadata")).get(K_TRAMOS)
             or escalera_channel
             or "")
    if not crudo.strip():
        return None

    base = (((v.get("pricing") or {}).get("price") or {}).get("gross") or {}).get("amount") or 0.0
    tramos = tramos_alcanzables(escalera_a_tramos(float(base), crudo),
                                v.get("quantityAvailable"), minimo=stock_minimo)
    if not tramos:
        return None
    return precio_para(cantidad, tramos)


def incentivo(variant_id: str, cantidad: int, *, canal: str,
              escalera_channel: str = "", stock_minimo: int = 0) -> Optional[dict]:
    """Próximo tramo por alcanzar: «lleva N más y pagas $X c/u».

    Es lo que convierte la tabla de tramos en una herramienta de venta y no solo
    en un cálculo.
    """
    body = gql(_VARIANTE, {"id": variant_id, "channel": canal})
    if data_errors(body):
        raise RuntimeError(f"lectura de variante: {data_errors(body)}")
    v = payload(body).get("productVariant")
    if not v:
        return None

    crudo = (_pares(v.get("privateMetadata")).get(K_TRAMOS)
             or _pares((v.get("product") or {}).get("privateMetadata")).get(K_TRAMOS)
             or escalera_channel or "")
    if not crudo.strip():
        return None

    base = (((v.get("pricing") or {}).get("price") or {}).get("gross") or {}).get("amount") or 0.0
    tramos = tramos_alcanzables(escalera_a_tramos(float(base), crudo),
                                v.get("quantityAvailable"), minimo=stock_minimo)
    if not tramos:
        return None
    prox = siguiente_tramo(cantidad, tramos)
    if not prox:
        return None
    return {"faltan": prox.desde - cantidad, "desde": prox.desde,
            "precio_unitario": prox.precio_unitario}


# ─────────── revisión de precios negociados ───────────

# Costo unitario. Va en `privateMetadata` por razones obvias: publicarlo en
# `metadata` lo dejaría legible sin autenticación, y con él el margen de Ventu.
K_COSTO = "ventu.pricing.costo"


def costo_de(variant_id: str, *, canal: str) -> Optional[float]:
    """Costo unitario publicado del producto, o `None` si no lo tiene."""
    body = gql(_VARIANTE, {"id": variant_id, "channel": canal})
    if data_errors(body):
        raise RuntimeError(f"lectura de variante: {data_errors(body)}")
    v = payload(body).get("productVariant")
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
    """
    body = gql(_VARIANTE, {"id": variant_id, "channel": canal})
    if data_errors(body):
        raise RuntimeError(f"lectura de variante: {data_errors(body)}")
    v = payload(body).get("productVariant")
    if not v:
        return []

    crudo = (_pares(v.get("privateMetadata")).get(K_TRAMOS)
             or _pares((v.get("product") or {}).get("privateMetadata")).get(K_TRAMOS)
             or escalera_channel or "")
    if not crudo.strip():
        return []

    base = (((v.get("pricing") or {}).get("price") or {}).get("gross") or {}).get("amount") or 0.0
    tramos = tramos_alcanzables(escalera_a_tramos(float(base), crudo),
                                v.get("quantityAvailable"), minimo=stock_minimo)
    return [{"desde": t.desde, "precio_unitario": t.precio_unitario} for t in tramos]
