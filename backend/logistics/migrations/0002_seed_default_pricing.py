"""Seed one clearly illustrative default pricing version so checkout can price deliveries out of the box.

Every number here is a planning example (Kerala, October 2026), not a verified business cost.
Admins replace it from Delivery pricing settings; placed orders keep their own snapshot.
"""
from decimal import Decimal

from django.db import migrations
from django.utils import timezone


def seed(apps, schema_editor):
    Version = apps.get_model("logistics", "DeliveryPricingVersion")
    if Version.objects.filter(zone__isnull=True).exists():
        return
    Version.objects.create(
        zone=None, version=1, effective_from=timezone.now(), is_illustrative=True,
        fuel_type="PETROL", energy_price=Decimal("115.00"),
        energy_price_source="Illustrative planning value. Fuel listings for 21 Oct 2026 showed about ₹113.74/L statewide and ₹115.09/L in Wayanad. Verify the local pump price.",
        efficiency_km_per_unit=Decimal("40"), maintenance_per_km=Decimal("1.50"),
        rider_pay_per_order=Decimal("25"), rider_pay_per_km=Decimal("0"), rider_fixed_daily_pay=Decimal("0"),
        rider_expected_orders_per_day=Decimal("20"), rider_pay_per_failed_attempt=Decimal("15"),
        operational_multiplier=Decimal("1.6"), overhead_per_order=Decimal("8"), overhead_per_km=Decimal("0"),
        failure_cost_rate=Decimal("0.10"), special_handling_cost=Decimal("0"), road_fallback_factor=Decimal("1.35"),
        allow_estimated_distance=True,
        pricing_mode="BASE_PLUS_DISTANCE", base_fee=Decimal("25"), included_km=Decimal("2"), per_km_rate=Decimal("6"),
        distance_bands=[{"up_to_km": 2, "fee": 25}, {"up_to_km": 5, "fee": 40}, {"up_to_km": 8, "fee": 55}],
        customer_recovery_ratio=Decimal("0.65"), max_platform_subsidy_per_order=Decimal("30"),
        min_fee=Decimal("20"), max_fee=Decimal("79"), allow_above_max_fee=False, rounding="NEAREST_RUPEE",
        max_service_km=Decimal("15"), peak_surcharge=Decimal("0"), peak_windows=[], heavy_surcharge=Decimal("0"),
        free_delivery_threshold=None, free_delivery_funded_by="PLATFORM",
        delivery_discount_amount=Decimal("0"), delivery_discount_min_order=Decimal("0"), delivery_discount_funded_by="PLATFORM",
        delivery_tax_rate=Decimal("0"), tax_treatment_confirmed=False,
        reason="Initial illustrative defaults (replace with verified costs)",
        notes="Example assumptions for testing. Replace fuel price, mileage, rider pay and overhead with verified figures before launch.",
    )


class Migration(migrations.Migration):
    dependencies = [("logistics", "0001_initial")]
    operations = [migrations.RunPython(seed, migrations.RunPython.noop)]
