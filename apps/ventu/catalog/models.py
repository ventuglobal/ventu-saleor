"""Modelos de entrada del publicador de catálogo.

Representan lo que la App Ventu *publica* a Saleor. El store propio del módulo
(catálogo normalizado multi-proveedor + costo) se define en un incremento
posterior; por ahora estos dataclasses son el contrato de entrada del
publicador (lo que llega por el endpoint / batch).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional


@dataclass(frozen=True)
class ChannelPrice:
    """Precio final por channel (ya calculado por Pricing; Saleor solo lo muestra)."""
    channel_slug: str
    amount: float


@dataclass
class VariantInput:
    """Estado deseado de una variante en Saleor, identificada por SKU.

    `available` es el *available deseado* por Ventu; el publicador lo traduce a
    `quantity = available + allocated_actual` en el warehouse VENTU.
    """
    sku: str
    available: int = 0
    prices: List[ChannelPrice] = field(default_factory=list)
    name: Optional[str] = None
    description: Optional[str] = None
    # URLs de las fotos del producto. Saleor las descarga y las guarda en su
    # storage (S3/R2 en despliegue real); se publican de forma idempotente.
    images: List[str] = field(default_factory=list)

    @classmethod
    def from_dict(cls, d: dict) -> "VariantInput":
        return cls(
            sku=str(d["sku"]),
            available=int(d.get("available") or 0),
            name=d.get("name"),
            description=d.get("description"),
            prices=[ChannelPrice(channel_slug=p["channel_slug"], amount=float(p["amount"]))
                    for p in (d.get("prices") or [])],
            images=[str(u) for u in (d.get("images") or []) if u],
        )


@dataclass
class PublishResult:
    sku: str
    ok: bool
    detail: str = ""
    stock_set: Optional[int] = None
    created: bool = False
