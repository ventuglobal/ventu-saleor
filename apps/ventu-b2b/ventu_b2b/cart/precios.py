"""Resolución del precio de una línea según la cantidad.

Reproduce el comportamiento del sitio actual: la tabla de tramos vive en el
producto y la **cantidad elegida en el carrito determina el precio unitario**.

La tabla se guarda en la metadata del producto en Saleor, así que Pricing la
publica y la App B2B la lee: una sola fuente, sin duplicar la escalera.
"""

from __future__ import annotations

from typing import Optional

from ..saleor_client import data_errors, gql, payload
from ..tiers import TramoInvalido, escalera_a_tramos, precio_para, siguiente_tramo

# Clave donde el producto guarda su escalera. Formato: "1=13240,4=8900,6=8400"
# (montos) o "1:1.0,10:0.9" (factores). Ver `ventu_b2b.tiers`.
K_TRAMOS = "ventu.pricing.tramos"

_VARIANTE = """
query($id: ID!, $channel: String!) {
  productVariant(id: $id, channel: $channel) {
    id
    pricing { price { gross { amount } } }
    product { metadata { key value } }
    metadata { key value }
  }
}
"""


def _pares(meta) -> dict:
    return {p["key"]: p["value"] for p in (meta or [])}


def resolver_precio(variant_id: str, cantidad: int, *, canal: str,
                    escalera_channel: str = "") -> Optional[float]:
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

    crudo = (_pares(v.get("metadata")).get(K_TRAMOS)
             or _pares((v.get("product") or {}).get("metadata")).get(K_TRAMOS)
             or escalera_channel
             or "")
    if not crudo.strip():
        return None

    base = (((v.get("pricing") or {}).get("price") or {}).get("gross") or {}).get("amount") or 0.0
    tramos = escalera_a_tramos(float(base), crudo)
    if not tramos:
        return None
    return precio_para(cantidad, tramos)


def incentivo(variant_id: str, cantidad: int, *, canal: str,
              escalera_channel: str = "") -> Optional[dict]:
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

    crudo = (_pares(v.get("metadata")).get(K_TRAMOS)
             or _pares((v.get("product") or {}).get("metadata")).get(K_TRAMOS)
             or escalera_channel or "")
    if not crudo.strip():
        return None

    base = (((v.get("pricing") or {}).get("price") or {}).get("gross") or {}).get("amount") or 0.0
    tramos = escalera_a_tramos(float(base), crudo)
    prox = siguiente_tramo(cantidad, tramos)
    if not prox:
        return None
    return {"faltan": prox.desde - cantidad, "desde": prox.desde,
            "precio_unitario": prox.precio_unitario}
