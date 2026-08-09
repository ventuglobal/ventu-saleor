"""Tests del módulo Pricing: motor (puro) y servicio (mock del writer)."""

from __future__ import annotations

from ventu import config
from ventu.pricing import policies, service
from ventu.pricing.engine import compute_price
from ventu.pricing.models import CostInput, PricingPolicy


def test_engine_gross_with_markup_and_rounding():
    p = PricingPolicy(channel_slug="retail-cl", markup=0.30, iva_rate=0.19, round_to=10)
    # 8500*1.30 = 11050; *1.19 = 13149.5; redondeo a 10 => 13150
    assert compute_price(8500, p) == 13150.0


def test_engine_net_no_iva():
    p = PricingPolicy(channel_slug="b2b-cl", markup=0.30, gross=False, round_to=10)
    assert compute_price(8500, p) == 11050.0


def test_engine_fixed_fee():
    p = PricingPolicy(channel_slug="x", markup=0.0, fixed_fee_net=500, gross=False, round_to=1)
    assert compute_price(1000, p) == 1500.0


def test_compute_channel_prices_per_channel(monkeypatch):
    monkeypatch.setattr(config, "PRICING_CHANNELS", ["retail-cl", "b2b-cl"])
    monkeypatch.setattr(config, "PRICING_IVA_RATE", 0.19)
    monkeypatch.setattr(config, "PRICING_GROSS", True)
    monkeypatch.setattr(config, "PRICING_ROUND_TO", 10)
    monkeypatch.setattr(config, "PRICING_FIXED_FEE", 0.0)
    # markup por channel distinto
    monkeypatch.setenv("PRICING_MARKUP_RETAIL_CL", "0.30")
    monkeypatch.setenv("PRICING_MARKUP_B2B_CL", "0.15")

    prices = service.compute_channel_prices(8500)
    by = {p.channel_slug: p.amount for p in prices}
    assert set(by) == {"retail-cl", "b2b-cl"}
    assert by["retail-cl"] == 13150.0            # 8500*1.30*1.19 → 13150
    assert by["b2b-cl"] == 11630.0               # 8500*1.15*1.19 = 11632.25 → 11630


def test_publish_prices_for_calls_writer(monkeypatch):
    monkeypatch.setattr(config, "PRICING_CHANNELS", ["retail-cl"])
    seen = {}

    def fake_writer(sku, prices):
        seen["sku"] = sku
        seen["prices"] = list(prices)
        from ventu.catalog.models import PublishResult
        return PublishResult(sku, ok=True, detail="prices")

    monkeypatch.setattr(service, "publish_prices", fake_writer)
    results = service.publish_prices_for([CostInput(sku="ABC", cost_net=8500)])
    assert len(results) == 1 and results[0].ok
    assert seen["sku"] == "ABC"
    assert seen["prices"][0].channel_slug == "retail-cl"
    assert seen["prices"][0].amount > 0
