from decimal import Decimal

from django.test import SimpleTestCase

from .pricing import price_leg


class Cfg:
    """Plain stand-in for DeliveryPricingConfig (the function reads attributes only)."""

    def __init__(self, **kw):
        defaults = dict(
            fuel_price_per_litre=Decimal("100"), vehicle_mileage_km_per_litre=Decimal("40"),
            maintenance_cost_per_km=Decimal("0.50"), operational_distance_multiplier=Decimal("2"),
            minimum_operational_distance_km=Decimal("0"), rider_base_payout=Decimal("10"),
            rider_payout_per_km=Decimal("2"), other_cost_per_delivery=Decimal("1"),
            customer_base_fee=Decimal("20"), customer_free_distance_km=Decimal("1"),
            customer_fee_per_km=Decimal("8"), customer_minimum_fee=Decimal("25"),
            customer_maximum_fee=Decimal("80"), fee_rounding_step=Decimal("1"),
            free_delivery_threshold=None, store_funded_discount_percent=Decimal("0"),
        )
        defaults.update(kw)
        self.__dict__.update(defaults)


class PriceLegTests(SimpleTestCase):
    def test_worked_example(self):
        # 4 km road: operational 8 km. fuel 8/40*100=20, maintenance 4, rider 10+8=18, other 1 => 43.
        # fee = 20 + (4-1)*8 = 44.
        p = price_leg(Cfg(), road_distance_meters=4000, items_subtotal=Decimal("300"))
        self.assertEqual(p.road_distance_km, Decimal("4.000"))
        self.assertEqual(p.operational_distance_km, Decimal("8.000"))
        self.assertEqual(p.operational_cost, Decimal("43.00"))
        self.assertEqual(p.rider_payout, Decimal("18.00"))
        self.assertEqual(p.fee_before_discount, Decimal("44.00"))
        self.assertEqual((p.discount, p.fee_after_discount), (Decimal("0.00"), Decimal("44.00")))
        self.assertEqual(p.contribution, Decimal("1.00"))
        self.assertEqual(p.unrecovered_cost, Decimal("0.00"))

    def test_minimum_and_maximum_fee_apply(self):
        near = price_leg(Cfg(), road_distance_meters=500, items_subtotal=Decimal("0"))
        far = price_leg(Cfg(), road_distance_meters=40000, items_subtotal=Decimal("0"))
        self.assertEqual(near.fee_before_discount, Decimal("25.00"))
        self.assertEqual(far.fee_before_discount, Decimal("80.00"))

    def test_fee_rounds_up_to_the_step(self):
        p = price_leg(Cfg(customer_fee_per_km=Decimal("8.30"), fee_rounding_step=Decimal("5")),
                      road_distance_meters=4000, items_subtotal=Decimal("0"))
        self.assertEqual(p.fee_before_discount, Decimal("45.00"))  # 20 + 3 * 8.30 = 44.90, up to the next 5

    def test_rounding_never_exceeds_the_maximum_fee(self):
        p = price_leg(Cfg(customer_maximum_fee=Decimal("42"), fee_rounding_step=Decimal("5")),
                      road_distance_meters=4000, items_subtotal=Decimal("0"))
        self.assertEqual(p.fee_before_discount, Decimal("42.00"))

    def test_free_delivery_threshold_creates_platform_subsidy(self):
        p = price_leg(Cfg(free_delivery_threshold=Decimal("500")), road_distance_meters=4000,
                      items_subtotal=Decimal("500"))
        self.assertEqual((p.fee_before_discount, p.discount, p.fee_after_discount),
                         (Decimal("44.00"), Decimal("44.00"), Decimal("0.00")))
        self.assertEqual(p.platform_subsidy, Decimal("44.00"))
        self.assertEqual(p.contribution, Decimal("-43.00"))
        self.assertEqual(p.unrecovered_cost, Decimal("43.00"))

    def test_below_threshold_pays_full_fee(self):
        p = price_leg(Cfg(free_delivery_threshold=Decimal("500")), road_distance_meters=4000,
                      items_subtotal=Decimal("499.99"))
        self.assertEqual(p.fee_after_discount, Decimal("44.00"))

    def test_store_funded_share_of_the_discount(self):
        p = price_leg(Cfg(free_delivery_threshold=Decimal("100"), store_funded_discount_percent=Decimal("25")),
                      road_distance_meters=4000, items_subtotal=Decimal("100"))
        self.assertEqual(p.store_funded_discount, Decimal("11.00"))
        self.assertEqual(p.platform_subsidy, Decimal("33.00"))
        self.assertEqual(p.store_funded_discount + p.platform_subsidy, p.discount)
        self.assertEqual(p.unrecovered_cost, Decimal("32.00"))

    def test_minimum_operational_distance(self):
        p = price_leg(Cfg(minimum_operational_distance_km=Decimal("3")), road_distance_meters=500,
                      items_subtotal=Decimal("0"))
        self.assertEqual(p.operational_distance_km, Decimal("3.000"))

    def test_customer_view_hides_internal_costs(self):
        view = price_leg(Cfg(), road_distance_meters=4000, items_subtotal=Decimal("0")).customer_view()
        self.assertEqual(set(view), {"delivery_fee_before_discount", "delivery_discount", "delivery_fee"})

    def test_zero_distance(self):
        p = price_leg(Cfg(), road_distance_meters=0, items_subtotal=Decimal("0"))
        self.assertEqual(p.fee_before_discount, Decimal("25.00"))
