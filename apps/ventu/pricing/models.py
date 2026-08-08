"""Modelos del módulo Pricing."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class PricingPolicy:
    """Regla de precio de un channel.

    price_net = cost_net * (1 + markup) + fixed_fee_net
    price     = price_net * (1 + iva_rate)   (si gross)
    price     = redondeo(price, round_to)
    """
    channel_slug: str
    markup: float = 0.30          # margen sobre el costo neto
    fixed_fee_net: float = 0.0    # fee fijo neto (CLP)
    iva_rate: float = 0.19
    gross: bool = True            # publicar precio con IVA incluido
    round_to: int = 10            # redondear al múltiplo (CLP)


@dataclass
class CostInput:
    """Costo neto de un SKU (fuente: módulo Catálogo & Abastecimiento)."""
    sku: str
    cost_net: float

    @classmethod
    def from_dict(cls, d: dict) -> "CostInput":
        return cls(sku=str(d["sku"]), cost_net=float(d["cost_net"]))
