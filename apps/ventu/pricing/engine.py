"""Motor de precios — función PURA (sin I/O), con Decimal para dinero.

Una regla, un lugar (Ley 2): el precio se computa aquí y nadie más lo recalcula.
"""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal

from .models import PricingPolicy


def _D(x) -> Decimal:
    return Decimal(str(x))


def compute_price(cost_net, policy: PricingPolicy) -> float:
    """Precio final para un channel a partir del costo neto y su política.

    Determinístico y sin efectos: mismo input ⇒ mismo output.
    """
    cost = _D(cost_net)
    price_net = cost * (Decimal(1) + _D(policy.markup)) + _D(policy.fixed_fee_net)
    price = price_net * (Decimal(1) + _D(policy.iva_rate)) if policy.gross else price_net

    step = _D(policy.round_to) if policy.round_to else Decimal(1)
    if step > 0:
        # redondeo al múltiplo más cercano de `round_to`
        price = (price / step).quantize(Decimal(1), rounding=ROUND_HALF_UP) * step
    else:
        price = price.quantize(Decimal(1), rounding=ROUND_HALF_UP)

    return float(price)
