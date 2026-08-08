"""Políticas de precio por channel, construidas desde config/env.

Permite override de markup por channel (`PRICING_MARKUP_<SLUG>`); el resto de
parámetros (IVA, fee, redondeo, gross) son globales por ahora. Cuando el negocio
lo pida, se mueven a una tabla por channel/categoría/proveedor.
"""

from __future__ import annotations

from typing import List

from .. import config
from .models import PricingPolicy


def policy_for(channel_slug: str) -> PricingPolicy:
    return PricingPolicy(
        channel_slug=channel_slug,
        markup=config.markup_for(channel_slug),
        fixed_fee_net=config.PRICING_FIXED_FEE,
        iva_rate=config.PRICING_IVA_RATE,
        gross=config.PRICING_GROSS,
        round_to=config.PRICING_ROUND_TO,
    )


def default_policies() -> List[PricingPolicy]:
    return [policy_for(slug) for slug in config.PRICING_CHANNELS]
