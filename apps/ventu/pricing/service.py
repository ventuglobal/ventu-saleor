"""Servicio de Pricing: computa precios por channel y los publica a Saleor.

Orquesta motor (engine) + políticas (policies) + writer (catalog.publisher).
Respeta la constitución: Pricing **computa** una vez; el writer del módulo
Catálogo **escribe** los channel-listings (un solo lugar habla con Saleor sobre
productos).
"""

from __future__ import annotations

import logging
from typing import Iterable, List

from ..catalog.models import ChannelPrice, PublishResult
from ..catalog.publisher import publish_prices
from . import policies
from .engine import compute_price
from .models import CostInput

logger = logging.getLogger("ventu.pricing")


def compute_channel_prices(cost_net: float) -> List[ChannelPrice]:
    """Precio final por cada channel configurado, a partir del costo neto."""
    return [
        ChannelPrice(channel_slug=p.channel_slug, amount=compute_price(cost_net, p))
        for p in policies.default_policies()
    ]


def publish_prices_for(cost_inputs: Iterable[CostInput]) -> List[PublishResult]:
    """Para cada SKU: computa precios por channel y los escribe en Saleor."""
    results: List[PublishResult] = []
    for ci in cost_inputs:
        prices = compute_channel_prices(ci.cost_net)
        try:
            results.append(publish_prices(ci.sku, prices))
        except Exception as exc:  # noqa: BLE001
            logger.warning("(pricing) publish sku=%s error: %s", ci.sku, exc)
            results.append(PublishResult(ci.sku, ok=False, detail=f"error: {exc}"))
    return results
