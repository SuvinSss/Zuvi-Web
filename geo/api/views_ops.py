"""Store portal, administration and Delivery Partner endpoints."""

import time
from decimal import Decimal

from django.conf import settings
from django.db import IntegrityError, transaction
from django.utils import timezone
from rest_framework import status
from rest_framework.exceptions import NotFound, ValidationError
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts.models import Role
from geo import google_client, routing
from geo.config import get_maps_config
from geo.coords import Coordinate, parse_coordinate
from geo.errors import MapsError
from geo.models import DeliveryPricingConfig, MapsHealthCheck
from geo.navigation import navigation_url
from geo.pricing import get_active_config, price_leg
from geo.serviceability import evaluate_store, store_coordinate
from geo.store_locations import duplicate_location_ids, store_location_report, update_store_location
from orders.models import (
    DeliveryAssignment,
    DeliveryAssignmentStatus,
    FulfillmentType,
    StoreOrder,
    StoreOrderStatus,
)
from stores.models import Store

from .permissions import (
    CanManageAssignments,
    CanManageMaps,
    CanManagePricing,
    IsDeliveryAgent,
    IsStoreUser,
)
from .serializers import (
    AssignmentCreateSerializer,
    PricingConfigSerializer,
    SimulatorSerializer,
    StoreLocationWriteSerializer,
)
from .throttles import AdminGeoThrottle

# Customer drop-off details become visible to the store only once it has accepted the order.
STORE_CAN_SEE_DROPOFF = {
    StoreOrderStatus.ACCEPTED,
    StoreOrderStatus.PREPARING,
    StoreOrderStatus.READY,
    StoreOrderStatus.OUT_FOR_DELIVERY,
}
ASSIGNABLE_STATUSES = {StoreOrderStatus.ACCEPTED, StoreOrderStatus.PREPARING, StoreOrderStatus.READY}
ACTIVE_STORE_ORDER_STATUSES = STORE_CAN_SEE_DROPOFF


def _address_block(address, *, recipient_name="", phone=""):
    return {
        "recipient_name": recipient_name,
        "phone_number": phone,
        "line1": address["line1"],
        "line2": address["line2"],
        "landmark": address["landmark"],
        "city": address["city"],
        "postal_code": address["postal_code"],
        "latitude": address["latitude"],
        "longitude": address["longitude"],
        "navigation_url": navigation_url(address["latitude"], address["longitude"], place_id=address.get("place_id", "")),
    }


def pickup_block(store):
    a = store.address
    block = _address_block(
        {
            "line1": a.line1, "line2": a.line2, "landmark": a.landmark, "city": a.city,
            "postal_code": a.postal_code, "latitude": str(a.latitude), "longitude": str(a.longitude),
            "place_id": a.google_place_id,
        },
        recipient_name=store.name,
        phone=store.contact_phone,
    )
    return block


def dropoff_block(order):
    return _address_block(
        {
            "line1": order.delivery_line1, "line2": order.delivery_line2, "landmark": order.delivery_landmark,
            "city": order.delivery_city, "postal_code": order.delivery_postal_code,
            "latitude": str(order.delivery_latitude), "longitude": str(order.delivery_longitude),
        },
        recipient_name=order.delivery_recipient_name,
        phone=order.delivery_phone_number,
    )


# ------------------------------------------------------------------ Store portal


class StoreLocationView(APIView):
    permission_classes = [IsStoreUser]

    def get(self, request):
        store = Store.objects.select_related("address").get(pk=request.store.pk)
        return Response(store_location_report(store, duplicate_location_ids([store])))

    def patch(self, request):
        data = StoreLocationWriteSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        values = {k: v for k, v in data.validated_data.items() if k != "delivery_radius_km"}
        store = Store.objects.select_related("address").get(pk=request.store.pk)
        update_store_location(store, values, actor=request.user, allow_radius=False)
        store.refresh_from_db()
        return Response(store_location_report(store))


class StoreOrdersView(APIView):
    """Pickup details always; customer drop-off details only after the store accepted the order."""

    permission_classes = [IsStoreUser]

    def get(self, request):
        qs = (
            StoreOrder.objects.filter(store=request.store, order__fulfillment_type=FulfillmentType.DELIVERY)
            .select_related("order", "store__address")
            .order_by("-created_at")[:50]
        )
        orders = []
        for so in qs:
            item = {
                "store_order_number": so.store_order_number,
                "status": so.status,
                "status_display": so.get_status_display(),
                "pickup": pickup_block(so.store),
            }
            if so.status in STORE_CAN_SEE_DROPOFF:
                item["dropoff"] = dropoff_block(so.order)
            orders.append(item)
        return Response({"orders": orders})


# --------------------------------------------------------------------- Admin


HEALTH_POINT = Coordinate(Decimal("28.613900"), Decimal("77.209000"))
HEALTH_POINT_2 = Coordinate(Decimal("28.630400"), Decimal("77.217700"))


def _latest_checks():
    out = {}
    for service in MapsHealthCheck.Service.values:
        check = MapsHealthCheck.objects.filter(service=service).first()
        last_ok = MapsHealthCheck.objects.filter(service=service, ok=True).first()
        out[service] = {
            "checked_at": check.checked_at.isoformat() if check else None,
            "ok": check.ok if check else None,
            "error_code": check.error_code if check else "",
            "message": check.message if check else "",
            "latency_ms": check.latency_ms if check else None,
            "last_success_at": last_ok.checked_at.isoformat() if last_ok else None,
        }
    return out


class MapsStatusView(APIView):
    permission_classes = [CanManageMaps]

    def get(self, request):
        cfg = get_maps_config()
        return Response(
            {
                # "configured" means a value is present. It does not mean Google accepts it;
                # only the health checks below can show that.
                "configuration": {
                    "browser_key_present": cfg.browser_configured,
                    "server_key_present": cfg.server_configured,
                    "map_id_present": cfg.map_id_configured,
                    "region": cfg.region,
                    "language": cfg.language,
                    "travel_mode": cfg.travel_mode,
                    "route_cache_ttl_seconds": cfg.route_cache_ttl,
                    "address_validation_enabled": cfg.address_validation_enabled,
                    "delivery_quotes_enforced": settings.DELIVERY_QUOTES_ENFORCED,
                },
                "health": _latest_checks(),
                "pricing_configured": DeliveryPricingConfig.objects.filter(is_active=True).exists(),
                "docs": {
                    "setup": "docs/google-maps-platform-setup.md",
                    "troubleshooting": "docs/google-maps-troubleshooting.md",
                    "google_cloud_console": "https://console.cloud.google.com/google/maps-apis",
                },
            }
        )


class MapsHealthCheckView(APIView):
    """Controlled live checks that spend a tiny amount of paid quota. Admin-triggered only."""

    permission_classes = [CanManageMaps]
    throttle_classes = [AdminGeoThrottle]

    def post(self, request):
        results = {}
        checks = (
            (MapsHealthCheck.Service.GEOCODING, lambda: google_client.reverse_geocode(HEALTH_POINT)),
            (MapsHealthCheck.Service.ROUTES, lambda: google_client.compute_route(HEALTH_POINT, HEALTH_POINT_2)),
        )
        for service, call in checks:
            started = time.monotonic()
            try:
                call()
                ok, code, message = True, "", "Responded normally."
            except MapsError as exc:
                ok, code, message = False, exc.code, exc.public_message
            latency = int((time.monotonic() - started) * 1000)
            row = MapsHealthCheck.objects.create(
                service=service, ok=ok, error_code=code, message=message[:200],
                latency_ms=latency, checked_by=request.user,
            )
            results[service] = {"ok": row.ok, "error_code": row.error_code, "message": row.message,
                                "latency_ms": row.latency_ms, "checked_at": row.checked_at.isoformat()}
        return Response(results)


class AdminStoreLocationsView(APIView):
    permission_classes = [CanManageMaps]

    def get(self, request):
        stores = list(Store.objects.select_related("address").order_by("name"))
        duplicates = duplicate_location_ids(stores)
        reports = [store_location_report(s, duplicates) for s in stores]
        return Response(
            {
                "stores": reports,
                "needs_attention": sum(1 for r in reports if r["issues"]),
            }
        )


class AdminStoreLocationDetailView(APIView):
    permission_classes = [CanManageMaps]

    def patch(self, request, pk):
        store = Store.objects.select_related("address").filter(pk=pk).first()
        if store is None:
            raise NotFound()
        data = StoreLocationWriteSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        update_store_location(store, data.validated_data, actor=request.user, allow_radius=True)
        store.refresh_from_db()
        return Response(store_location_report(store))


def pricing_config_dict(c):
    fields = [
        "fuel_price_per_litre", "vehicle_mileage_km_per_litre", "maintenance_cost_per_km",
        "operational_distance_multiplier", "minimum_operational_distance_km", "rider_base_payout",
        "rider_payout_per_km", "other_cost_per_delivery", "customer_base_fee", "customer_free_distance_km",
        "customer_fee_per_km", "customer_minimum_fee", "customer_maximum_fee", "fee_rounding_step",
        "free_delivery_threshold", "store_funded_discount_percent", "max_road_distance_km",
    ]
    data = {f: (None if getattr(c, f) is None else str(getattr(c, f))) for f in fields}
    data.update({"id": c.pk, "version": c.version, "name": c.name, "is_active": c.is_active,
                 "created_at": c.created_at.isoformat()})
    return data


class PricingConfigView(APIView):
    permission_classes = [CanManagePricing]

    def get(self, request):
        return Response({"configs": [pricing_config_dict(c) for c in DeliveryPricingConfig.objects.all()]})

    def post(self, request):
        """Create and activate a new version. Existing versions are never edited."""
        data = PricingConfigSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        with transaction.atomic():
            latest = DeliveryPricingConfig.objects.select_for_update().order_by("-version").first()
            DeliveryPricingConfig.objects.filter(is_active=True).update(is_active=False)
            config = DeliveryPricingConfig.objects.create(
                version=(latest.version + 1) if latest else 1,
                is_active=True,
                created_by=request.user,
                **data.validated_data,
            )
        return Response(pricing_config_dict(config), status=status.HTTP_201_CREATED)


class PricingSimulatorView(APIView):
    """Runs the same route lookup and price_leg() used by checkout quotes."""

    permission_classes = [CanManagePricing]
    throttle_classes = [AdminGeoThrottle]

    def post(self, request):
        data = SimulatorSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        v = data.validated_data
        store = Store.objects.select_related("address").filter(pk=v["store_id"]).first()
        if store is None:
            raise NotFound()
        destination = parse_coordinate(v["latitude"], v["longitude"])
        origin = store_coordinate(store)
        if origin is None:
            raise ValidationError({"store_id": "This store has no usable location."})
        config = get_active_config()
        verdict = evaluate_store(store, destination)
        refresh = bool(request.data.get("refresh"))
        route = routing.get_route(origin, destination, origin_ref=f"store:{store.pk}",
                                  destination_ref="simulated", use_cache=not refresh)
        pricing = price_leg(config, road_distance_meters=route.distance_meters, items_subtotal=v["items_subtotal"])
        return Response(
            {
                "input": {"kind": "SIMULATED_DESTINATION", "latitude": str(destination.latitude),
                          "longitude": str(destination.longitude), "items_subtotal": str(v["items_subtotal"])},
                "route": {**route.as_dict(), "is_live": route.source == routing.SOURCE_LIVE},
                "serviceability": {
                    "eligible": verdict.eligible,
                    "reasons": verdict.reasons,
                    "straight_line_km": verdict.straight_line_km,
                    "within_max_road_distance": route.distance_km <= Decimal(config.max_road_distance_km),
                },
                "pricing_version": config.version,
                "pricing": {
                    "road_distance_km": str(pricing.road_distance_km),
                    "operational_distance_km": str(pricing.operational_distance_km),
                    "operational_cost": str(pricing.operational_cost),
                    "customer_fee_before_discount": str(pricing.fee_before_discount),
                    "discount": str(pricing.discount),
                    "customer_fee": str(pricing.fee_after_discount),
                    "rider_payout": str(pricing.rider_payout),
                    "platform_subsidy": str(pricing.platform_subsidy),
                    "store_funded_discount": str(pricing.store_funded_discount),
                    "unrecovered_cost": str(pricing.unrecovered_cost),
                    "contribution": str(pricing.contribution),
                },
            }
        )


def assignment_admin_dict(a):
    return {
        "id": a.pk,
        "store_order_number": a.store_order.store_order_number,
        "store_name": a.store_order.store_name,
        "agent_id": a.agent_id,
        "agent_username": a.agent.get_username(),
        "status": a.status,
        "assigned_at": a.assigned_at.isoformat(),
    }


class AdminAssignmentsView(APIView):
    permission_classes = [CanManageAssignments]

    def get(self, request):
        qs = DeliveryAssignment.objects.select_related("store_order", "agent").order_by("-assigned_at")[:100]
        agents = [
            {"id": u.pk, "username": u.get_username(), "name": u.get_full_name() or u.get_username()}
            for u in _agents()
        ]
        return Response({"assignments": [assignment_admin_dict(a) for a in qs], "agents": agents})

    def post(self, request):
        data = AssignmentCreateSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        v = data.validated_data
        agent = _agents().filter(pk=v["agent_id"]).first()
        if agent is None:
            raise ValidationError({"agent_id": "Choose an active delivery partner."})
        try:
            with transaction.atomic():
                so = (
                    StoreOrder.objects.select_for_update()
                    .select_related("order")
                    .filter(store_order_number=v["store_order_number"])
                    .first()
                )
                if so is None:
                    raise NotFound()
                if so.order.fulfillment_type != FulfillmentType.DELIVERY or so.status not in ASSIGNABLE_STATUSES:
                    raise ValidationError({"store_order_number": "This order cannot be assigned right now."})
                assignment = DeliveryAssignment.objects.create(store_order=so, agent=agent, assigned_by=request.user)
        except IntegrityError:
            raise ValidationError({"store_order_number": "This order already has a delivery partner."}) from None
        return Response(assignment_admin_dict(assignment), status=status.HTTP_201_CREATED)


def _agents():
    from django.contrib.auth import get_user_model

    return get_user_model().objects.filter(role=Role.DELIVERY_AGENT, is_active=True).order_by("username")


# ------------------------------------------------------------ Delivery Partner


def _rider_assignments(user):
    return DeliveryAssignment.objects.filter(agent=user).select_related(
        "store_order", "store_order__order", "store_order__store__address"
    )


def rider_assignment_dict(a, *, detail=False):
    so = a.store_order
    active = (
        a.status != DeliveryAssignmentStatus.CANCELLED and so.status in ACTIVE_STORE_ORDER_STATUSES
    )
    data = {
        "id": a.pk,
        "store_order_number": so.store_order_number,
        "status": a.status,
        "status_display": a.get_status_display(),
        "store_order_status": so.status,
        "store_order_status_display": so.get_status_display(),
        "is_active": active,
        "next_action": _next_action(a, so),
        "pickup": pickup_block(so.store),
    }
    if active:
        data["dropoff"] = dropoff_block(so.order)
        data["delivery_instructions"] = so.order.delivery_instructions
        leg = next(
            (leg for leg in so.order.delivery_pricing_snapshot.get("legs", []) if leg["store_code"] == so.store_code),
            None,
        )
        if leg:
            route = leg["route"]
            data["route"] = {
                "distance_km": str((Decimal(route["distance_meters"]) / 1000).quantize(Decimal("0.1"))),
                "duration_minutes": round(route["duration_seconds"] / 60),
                "source": route["source"],
            }
    return data


def _next_action(a, so):
    if a.status == DeliveryAssignmentStatus.CANCELLED or so.status not in ACTIVE_STORE_ORDER_STATUSES:
        return None
    if a.status == DeliveryAssignmentStatus.ASSIGNED:
        if so.status in (StoreOrderStatus.READY, StoreOrderStatus.OUT_FOR_DELIVERY):
            return {"code": "PICK_UP", "label": "Collect the order from the store"}
        return {"code": "WAIT", "label": "Wait until the store marks the order ready"}
    if a.status == DeliveryAssignmentStatus.PICKED_UP:
        return {"code": "ARRIVE", "label": "Deliver to the customer"}
    return {"code": "HAND_OVER", "label": "Hand over the order and collect payment"}


class RiderAssignmentsView(APIView):
    permission_classes = [IsDeliveryAgent]

    def get(self, request):
        rows = [rider_assignment_dict(a) for a in _rider_assignments(request.user)[:50]]
        return Response({"assignments": [r for r in rows if r["is_active"]]})


class RiderAssignmentDetailView(APIView):
    permission_classes = [IsDeliveryAgent]

    def get(self, request, pk):
        assignment = _rider_assignments(request.user).filter(pk=pk).first()
        if assignment is None:
            raise NotFound()  # another partner's assignment looks the same as a missing one
        return Response(rider_assignment_dict(assignment, detail=True))


class RiderAdvanceView(APIView):
    """Move the partner's own progress forward. Fees and distances are never writable here."""

    permission_classes = [IsDeliveryAgent]

    def post(self, request, pk):
        with transaction.atomic():
            assignment = (
                DeliveryAssignment.objects.select_for_update()
                .select_related("store_order", "store_order__order", "store_order__store__address")
                .filter(pk=pk, agent=request.user)
                .first()
            )
            if assignment is None:
                raise NotFound()
            so = assignment.store_order
            if assignment.status == DeliveryAssignmentStatus.ASSIGNED:
                if so.status not in (StoreOrderStatus.READY, StoreOrderStatus.OUT_FOR_DELIVERY):
                    raise ValidationError({"status": "The store has not marked this order ready yet."})
                assignment.status = DeliveryAssignmentStatus.PICKED_UP
                assignment.picked_up_at = timezone.now()
            elif assignment.status == DeliveryAssignmentStatus.PICKED_UP:
                assignment.status = DeliveryAssignmentStatus.ARRIVED
                assignment.arrived_at = timezone.now()
            else:
                raise ValidationError({"status": "There is no further step to record."})
            assignment.save()
        return Response(rider_assignment_dict(assignment))
