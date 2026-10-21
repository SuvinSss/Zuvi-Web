"""Pure pricing engine tests (no database)."""
from decimal import Decimal
from types import SimpleNamespace

from django.core.exceptions import ValidationError
from django.test import SimpleTestCase

from logistics import engine
from logistics.engine import Mode, TripContext

D = Decimal


def cfg(**over):
    base = dict(
        energy_price=D("115"), efficiency_km_per_unit=D("40"), maintenance_per_km=D("1.50"),
        rider_pay_per_order=D("25"), rider_pay_per_km=D("0"), rider_fixed_daily_pay=D("0"), rider_expected_orders_per_day=D("20"),
        rider_pay_per_failed_attempt=D("15"), operational_multiplier=D("2.0"), overhead_per_order=D("8"), overhead_per_km=D("0"),
        failure_cost_rate=D("0.10"), special_handling_cost=D("0"),
        pricing_mode=Mode.BASE_PLUS_DISTANCE, base_fee=D("25"), included_km=D("2"), per_km_rate=D("6"), distance_bands=[],
        customer_recovery_ratio=D("0.65"), max_platform_subsidy_per_order=D("30"),
        min_fee=D("0"), max_fee=D("999"), allow_above_max_fee=False, rounding="NONE", max_service_km=None,
        peak_surcharge=D("0"), heavy_surcharge=D("0"), free_delivery_threshold=None, free_delivery_funded_by="PLATFORM",
        delivery_discount_amount=D("0"), delivery_discount_min_order=D("0"), delivery_discount_funded_by="PLATFORM",
        delivery_tax_rate=D("0"),
    )
    base.update(over)
    return SimpleNamespace(**base)


class WorkedExampleTests(SimpleTestCase):
    """The documented isolated-trip example (docs/delivery-pricing-algorithm.md §Worked example)."""

    def test_every_step(self):
        c = engine.estimate_cost(cfg(), D("5"))
        self.assertEqual(c["fuel_cost_per_km"], D("2.875"))
        self.assertEqual(c["operational_km"], D("10.0"))
        self.assertEqual(c["fuel_cost"].quantize(D("0.01")), D("28.75"))
        self.assertEqual(c["maintenance_cost"], D("15.000"))
        self.assertEqual(c["direct_operating_cost"].quantize(D("0.01")), D("76.75"))
        self.assertEqual(c["failure_allowance"].quantize(D("0.001")), D("7.675"))
        self.assertEqual(engine.money(c["estimated_cost"]), D("84.43"))

    def test_customer_paying_55_leaves_a_29_43_subsidy_not_profit(self):
        q = engine.quote(cfg(pricing_mode=Mode.BANDS, distance_bands=[{"up_to_km": 6, "fee": 55}]), TripContext(distance_km=D("5")))
        self.assertEqual(q["customer_fee"], D("55.00"))
        self.assertEqual(q["estimated_cost"], D("84.43"))
        self.assertEqual(q["platform_subsidy"], D("29.43"))
        self.assertEqual(q["delivery_contribution"], D("0.00"))
        self.assertEqual(q["partner_payout"], D("25.00"))  # rider pay is not the customer fee


class FuelTests(SimpleTestCase):
    def test_other_prices_and_mileage(self):
        self.assertEqual(engine.fuel_cost_per_km(cfg(energy_price=D("102"), efficiency_km_per_unit=D("51"))), D("2"))
        self.assertEqual(engine.fuel_cost_per_km(cfg(energy_price=D("120"), efficiency_km_per_unit=D("30"))), D("4"))

    def test_electric_vehicle(self):
        # ₹8/kWh at 25 km/kWh → ₹0.32/km
        self.assertEqual(engine.fuel_cost_per_km(cfg(energy_price=D("8"), efficiency_km_per_unit=D("25"))), D("0.32"))

    def test_zero_or_negative_mileage_rejected(self):
        for bad in ("0", "-5"):
            with self.assertRaises(ValidationError):
                engine.fuel_cost_per_km(cfg(efficiency_km_per_unit=D(bad)))


class DistanceTests(SimpleTestCase):
    def test_invalid_distances(self):
        for bad in (None, "", "-1", "abc", "NaN", "5000"):
            with self.assertRaises(ValidationError):
                engine.quote(cfg(), TripContext(distance_km=bad))

    def test_zero_distance_is_priced_at_the_base(self):
        self.assertEqual(engine.quote(cfg(), TripContext(distance_km=D("0")))["customer_fee"], D("25.00"))

    def test_operational_factor_changes_cost_not_tariff(self):
        a = engine.quote(cfg(operational_multiplier=D("1.6")), TripContext(distance_km=D("5")))
        b = engine.quote(cfg(operational_multiplier=D("2.0")), TripContext(distance_km=D("5")))
        self.assertLess(a["estimated_cost"], b["estimated_cost"])
        self.assertEqual(a["customer_fee"], b["customer_fee"])
        with self.assertRaises(ValidationError):
            engine.estimate_cost(cfg(operational_multiplier=D("0.9")), D("5"))

    def test_beyond_max_service_distance_refused(self):
        with self.assertRaises(ValidationError):
            engine.quote(cfg(max_service_km=D("10")), TripContext(distance_km=D("12")))


class TariffTests(SimpleTestCase):
    def test_base_plus_distance(self):
        self.assertEqual(engine.quote(cfg(), TripContext(distance_km=D("5")))["customer_fee"], D("43.00"))  # 25 + 3×6

    def test_distance_bands_and_beyond_last_band(self):
        s = cfg(pricing_mode=Mode.BANDS, distance_bands=[{"up_to_km": 2, "fee": 20}, {"up_to_km": 5, "fee": 35}], per_km_rate=D("8"))
        self.assertEqual(engine.quote(s, TripContext(distance_km=D("1.5")))["customer_fee"], D("20.00"))
        self.assertEqual(engine.quote(s, TripContext(distance_km=D("5")))["customer_fee"], D("35.00"))
        self.assertEqual(engine.quote(s, TripContext(distance_km=D("6")))["customer_fee"], D("43.00"))

    def test_cost_aware_recovers_share_of_cost(self):
        q = engine.quote(cfg(pricing_mode=Mode.COST_AWARE, customer_recovery_ratio=D("0.8")), TripContext(distance_km=D("5")))
        self.assertEqual(q["recovery_target"], D("67.54"))  # 84.425 × 0.8
        self.assertEqual(q["customer_fee"], D("67.54"))

    def test_hybrid_caps_platform_subsidy(self):
        q = engine.quote(cfg(pricing_mode=Mode.HYBRID, max_platform_subsidy_per_order=D("20")), TripContext(distance_km=D("5")))
        self.assertEqual(q["customer_fee"], D("64.43"))
        self.assertEqual(q["platform_subsidy"], D("20.00"))

    def test_min_and_max_fee_with_unrecovered_cost_recorded(self):
        q = engine.quote(cfg(pricing_mode=Mode.COST_AWARE, customer_recovery_ratio=D("1"), max_fee=D("60")), TripContext(distance_km=D("5")))
        self.assertEqual(q["customer_fee"], D("60.00"))
        self.assertEqual(q["capped_by_max_fee"], D("24.43"))
        self.assertEqual(q["platform_subsidy"], D("24.43"))
        self.assertEqual(engine.quote(cfg(min_fee=D("30")), TripContext(distance_km=D("0")))["customer_fee"], D("30.00"))

    def test_rounding_policies(self):
        s = cfg(pricing_mode=Mode.COST_AWARE, customer_recovery_ratio=D("0.8"))
        self.assertEqual(engine.quote(cfg(**{**s.__dict__, "rounding": "NEAREST_RUPEE"}), TripContext(distance_km=D("5")))["customer_fee"], D("68.00"))
        self.assertEqual(engine.quote(cfg(**{**s.__dict__, "rounding": "UP_RUPEE"}), TripContext(distance_km=D("4.9")))["customer_fee"] % 1, D("0"))

    def test_surcharges(self):
        q = engine.quote(cfg(peak_surcharge=D("10"), heavy_surcharge=D("15"), special_handling_cost=D("12")),
                         TripContext(distance_km=D("5"), is_peak=True, heavy=True, zone_surcharge=D("5")))
        self.assertEqual(q["customer_fee"], D("73.00"))  # 43 + 10 + 5 + 15
        self.assertEqual(q["cost"]["extra_costs"], D("12.00"))


class DiscountTests(SimpleTestCase):
    def test_free_delivery_funded_by_platform(self):
        q = engine.quote(cfg(free_delivery_threshold=D("499")), TripContext(distance_km=D("5"), items_subtotal=D("500")))
        self.assertEqual((q["customer_fee_before_discount"], q["delivery_discount"], q["customer_fee"]), (D("43.00"), D("43.00"), D("0.00")))
        self.assertEqual(q["platform_funded_promotion"], D("43.00"))
        self.assertEqual(q["platform_subsidy"], D("84.43"))

    def test_store_funded_promotion_is_recovered_from_the_store(self):
        q = engine.quote(cfg(free_delivery_threshold=D("499"), free_delivery_funded_by="STORE"), TripContext(distance_km=D("5"), items_subtotal=D("600")))
        self.assertEqual(q["store_funded_promotion"], D("43.00"))
        self.assertEqual(q["platform_funded_promotion"], D("0.00"))
        self.assertEqual(q["platform_subsidy"], D("41.43"))  # 84.43 − 43 from the store

    def test_below_threshold_pays(self):
        q = engine.quote(cfg(free_delivery_threshold=D("499")), TripContext(distance_km=D("5"), items_subtotal=D("498.99")))
        self.assertEqual(q["delivery_discount"], D("0.00"))

    def test_flat_discount_never_negative(self):
        q = engine.quote(cfg(delivery_discount_amount=D("100")), TripContext(distance_km=D("1")))
        self.assertEqual(q["customer_fee"], D("0.00"))

    def test_tax_only_when_configured(self):
        self.assertEqual(engine.quote(cfg(), TripContext(distance_km=D("5")))["delivery_tax"], D("0.00"))
        q = engine.quote(cfg(delivery_tax_rate=D("0.18")), TripContext(distance_km=D("5")))
        self.assertEqual((q["delivery_tax"], q["customer_total"]), (D("7.74"), D("50.74")))


class RiderPayTests(SimpleTestCase):
    def test_components_counted_once(self):
        r = engine.rider_compensation(cfg(rider_pay_per_order=D("20"), rider_pay_per_km=D("3"), rider_fixed_daily_pay=D("400"), rider_expected_orders_per_day=D("20")), D("4"))
        self.assertEqual((r["per_order"], r["per_km"], r["fixed_share"], r["total"]), (D("20"), D("12"), D("20"), D("52")))

    def test_failed_attempt_pay(self):
        self.assertEqual(engine.failed_attempt_payout(cfg()), D("15.00"))

    def test_fixed_pay_needs_expected_orders(self):
        with self.assertRaises(ValidationError):
            engine.rider_compensation(cfg(rider_fixed_daily_pay=D("400"), rider_expected_orders_per_day=D("0")), D("1"))


class SharedRouteTests(SimpleTestCase):
    def test_allocation_adds_up_exactly(self):
        out = engine.allocate_shared_route(D("100"), [{"key": "a", "distance_km": 1}, {"key": "b", "distance_km": 1}, {"key": "c", "distance_km": 1}])
        self.assertEqual(sum(x["share"] for x in out), D("100.00"))
        out = engine.allocate_shared_route(D("90"), [{"key": "a", "distance_km": 2}, {"key": "b", "distance_km": 4}])
        self.assertEqual([x["share"] for x in out], [D("30.00"), D("60.00")])

    def test_equal_and_zero_distance(self):
        self.assertEqual([x["share"] for x in engine.allocate_shared_route(D("10"), [{"distance_km": 0}, {"distance_km": 0}])], [D("5.00"), D("5.00")])
        self.assertEqual(len(engine.allocate_shared_route(D("10"), [{}, {}], basis="equal")), 2)

    def test_batch_is_cheaper_than_isolated_trips(self):
        b = engine.batch_quote(cfg(), route_km=D("7"), stops=[{"key": 1, "distance_km": 3}, {"key": 2, "distance_km": 4}])
        self.assertLess(b["batched_total"], b["isolated_total"])
        self.assertEqual(sum(a["share"] for a in b["allocations"]), b["shared_route_cost"])
