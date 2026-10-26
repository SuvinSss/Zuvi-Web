import re

from decimal import Decimal

from rest_framework import serializers

from customers.models import AddressLabel
from geo.coords import parse_coordinate
from geo.errors import InvalidCoordinates
from locations.models import LocationSource

PLACE_ID_RE = re.compile(r"^[A-Za-z0-9_-]{10,255}$")


class CoordinateFieldsMixin(serializers.Serializer):
    latitude = serializers.CharField(max_length=20)
    longitude = serializers.CharField(max_length=20)

    def validate(self, attrs):
        attrs = super().validate(attrs)
        try:
            point = parse_coordinate(attrs["latitude"], attrs["longitude"])
        except InvalidCoordinates:
            raise serializers.ValidationError({"latitude": "Choose a valid location on the map."}) from None
        attrs["latitude"], attrs["longitude"] = point.latitude, point.longitude
        return attrs


class PointSerializer(CoordinateFieldsMixin):
    """A bare latitude/longitude pair."""


class ForwardGeocodeSerializer(serializers.Serializer):
    address = serializers.CharField(max_length=300, trim_whitespace=True)


class CustomerAddressWriteSerializer(CoordinateFieldsMixin):
    label = serializers.ChoiceField(choices=AddressLabel.choices)
    recipient_name = serializers.CharField(max_length=150)
    phone_number = serializers.CharField(max_length=20)
    line1 = serializers.CharField(max_length=255)
    line2 = serializers.CharField(max_length=255, required=False, allow_blank=True, default="")
    landmark = serializers.CharField(max_length=255, required=False, allow_blank=True, default="")
    city = serializers.CharField(max_length=100)
    district = serializers.CharField(max_length=100, required=False, allow_blank=True, default="")
    state = serializers.CharField(max_length=100)
    postal_code = serializers.CharField(max_length=20)
    delivery_instructions = serializers.CharField(required=False, allow_blank=True, default="", max_length=500)
    is_default = serializers.BooleanField(required=False, default=False)
    google_place_id = serializers.CharField(required=False, allow_blank=True, default="", max_length=255)
    location_source = serializers.ChoiceField(choices=LocationSource.choices, default=LocationSource.MANUAL)
    # The customer must confirm the pin position before an address is saved.
    location_confirmed = serializers.BooleanField()

    def validate_google_place_id(self, value):
        if value and not PLACE_ID_RE.match(value):
            raise serializers.ValidationError("Not a valid place identifier.")
        return value

    def validate_location_confirmed(self, value):
        if not value:
            raise serializers.ValidationError("Confirm the location on the map before saving.")
        return value


def customer_address_dict(ca):
    a = ca.address
    return {
        "id": ca.pk,
        "label": ca.label,
        "label_display": ca.get_label_display(),
        "recipient_name": ca.recipient_name,
        "phone_number": ca.phone_number,
        "line1": a.line1,
        "line2": a.line2,
        "landmark": a.landmark,
        "city": a.city,
        "district": a.district,
        "state": a.state,
        "postal_code": a.postal_code,
        "country": a.country,
        "latitude": str(a.latitude),
        "longitude": str(a.longitude),
        "google_place_id": a.google_place_id,
        "location_source": a.location_source,
        "location_confirmed": a.location_confirmed_at is not None,
        "delivery_instructions": ca.delivery_instructions,
        "is_default": ca.is_default,
        "created_at": ca.created_at.isoformat(),
        "updated_at": ca.updated_at.isoformat(),
    }


class StoreLocationWriteSerializer(CoordinateFieldsMixin):
    line1 = serializers.CharField(max_length=255)
    line2 = serializers.CharField(max_length=255, required=False, allow_blank=True, default="")
    landmark = serializers.CharField(max_length=255, required=False, allow_blank=True, default="")
    city = serializers.CharField(max_length=100)
    district = serializers.CharField(max_length=100, required=False, allow_blank=True, default="")
    state = serializers.CharField(max_length=100)
    postal_code = serializers.CharField(max_length=20)
    google_place_id = serializers.CharField(required=False, allow_blank=True, default="", max_length=255)
    location_source = serializers.ChoiceField(choices=LocationSource.choices, default=LocationSource.MAP_PIN)
    delivery_radius_km = serializers.DecimalField(
        max_digits=5, decimal_places=2, min_value=Decimal("0.5"), max_value=Decimal("100"), required=False
    )
    confirm = serializers.BooleanField(default=False)

    def validate_google_place_id(self, value):
        if value and not PLACE_ID_RE.match(value):
            raise serializers.ValidationError("Not a valid place identifier.")
        return value


class QuoteRequestSerializer(serializers.Serializer):
    address_id = serializers.IntegerField(min_value=1)


class CheckoutRequestSerializer(serializers.Serializer):
    address_id = serializers.IntegerField(min_value=1)
    quote_id = serializers.IntegerField(min_value=1)
    checkout_token = serializers.CharField(max_length=128)
    customer_notes = serializers.CharField(required=False, allow_blank=True, default="", max_length=500)
    # Any "delivery_fee"/"total" key sent by a client is not a declared field and is ignored.


class SimulatorSerializer(CoordinateFieldsMixin):
    store_id = serializers.IntegerField(min_value=1)
    items_subtotal = serializers.DecimalField(max_digits=10, decimal_places=2, min_value=0)


class PricingConfigSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=100, required=False, allow_blank=True, default="")
    fuel_price_per_litre = serializers.DecimalField(max_digits=10, decimal_places=2, min_value=0)
    vehicle_mileage_km_per_litre = serializers.DecimalField(max_digits=6, decimal_places=2, min_value=Decimal("0.1"))
    maintenance_cost_per_km = serializers.DecimalField(max_digits=10, decimal_places=2, min_value=0, default=0)
    operational_distance_multiplier = serializers.DecimalField(
        max_digits=4, decimal_places=2, min_value=1, max_value=5, default=1
    )
    minimum_operational_distance_km = serializers.DecimalField(
        max_digits=6, decimal_places=2, min_value=0, default=0
    )
    rider_base_payout = serializers.DecimalField(max_digits=10, decimal_places=2, min_value=0, default=0)
    rider_payout_per_km = serializers.DecimalField(max_digits=10, decimal_places=2, min_value=0, default=0)
    other_cost_per_delivery = serializers.DecimalField(max_digits=10, decimal_places=2, min_value=0, default=0)
    customer_base_fee = serializers.DecimalField(max_digits=10, decimal_places=2, min_value=0, default=0)
    customer_free_distance_km = serializers.DecimalField(max_digits=6, decimal_places=2, min_value=0, default=0)
    customer_fee_per_km = serializers.DecimalField(max_digits=10, decimal_places=2, min_value=0, default=0)
    customer_minimum_fee = serializers.DecimalField(max_digits=10, decimal_places=2, min_value=0, default=0)
    customer_maximum_fee = serializers.DecimalField(
        max_digits=10, decimal_places=2, min_value=0, required=False, allow_null=True, default=None
    )
    fee_rounding_step = serializers.DecimalField(max_digits=6, decimal_places=2, min_value=Decimal("0.01"), default=1)
    free_delivery_threshold = serializers.DecimalField(
        max_digits=10, decimal_places=2, min_value=0, required=False, allow_null=True, default=None
    )
    store_funded_discount_percent = serializers.DecimalField(
        max_digits=5, decimal_places=2, min_value=0, max_value=Decimal("100"), default=0
    )
    max_road_distance_km = serializers.DecimalField(max_digits=6, decimal_places=2, min_value=Decimal("0.1"), default=15)


class AssignmentCreateSerializer(serializers.Serializer):
    store_order_number = serializers.CharField(max_length=32)
    agent_id = serializers.IntegerField(min_value=1)
