"""Location, delivery pricing, checkout quote, operations and earnings endpoints."""
from __future__ import annotations

from datetime import timedelta
from decimal import Decimal, InvalidOperation
from types import SimpleNamespace

from django.core.exceptions import ValidationError as DjangoValidationError
from django.db.models import Count, Q, Sum
from django.forms.models import model_to_dict
from django.shortcuts import get_object_or_404
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from rest_framework import serializers
from rest_framework.exceptions import PermissionDenied
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView

from accounts.models import Role
from core.geo import valid_coordinates
from core.permissions import IsCustomer, IsDeliveryPartner, IsManagement, IsStoreUser, get_customer, get_delivery_partner, get_store_membership, is_management

from . import engine
from .models import CheckoutQuote, DeliveryPricingVersion, PartnerEarning, PricingZone
from .providers import ProviderUnavailable, get_geocoder
from .services import (
    VERSION_FIELDS, active_version, create_version, customer_view, is_peak, jsonable, quote_for_store, serviceability,
    store_location_problems, validate_polygon,
)


def _drf(exc: DjangoValidationError):
    return serializers.ValidationError(exc.message_dict if hasattr(exc, "error_dict") else {"detail": exc.messages})


def _need(user, perm):
    if not is_management(user):
        raise PermissionDenied("Administrator access is required.")
    if user.role != Role.SUPER_ADMIN and not user.has_perm(perm):
        raise PermissionDenied("You do not have permission for this.")


def _point(params):
    try:
        lat, lon = Decimal(str(params.get("lat"))), Decimal(str(params.get("lon")))
    except (InvalidOperation, ValueError, TypeError):
        raise serializers.ValidationError({"detail": "Send lat and lon as numbers."}) from None
    if not valid_coordinates(lat, lon) or (not lat and not lon):
        raise serializers.ValidationError({"detail": "These coordinates are not valid."})
    return lat, lon


# ------------------------------------------------------------------ geocoding (public, throttled, cached)

class GeoSearchView(APIView):
    permission_classes = [AllowAny]
    authentication_classes = []
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "geo"

    def get(self, request):
        q = (request.query_params.get("q") or "").strip()
        if len(q) < 3:
            return Response({"results": [], "available": True})
        try:
            places = get_geocoder().search(q[:120])
        except ProviderUnavailable:
            return Response({"results": [], "available": False,
                             "detail": "Address search is unavailable right now. Place the pin on the map or type the address."})
        return Response({"results": [p.as_dict() for p in places], "available": True})


class GeoReverseView(APIView):
    permission_classes = [AllowAny]
    authentication_classes = []
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "geo"

    def get(self, request):
        lat, lon = _point(request.query_params)
        try:
            return Response({"result": get_geocoder().reverse(lat, lon).as_dict(), "available": True})
        except ProviderUnavailable:
            return Response({"result": None, "available": False,
                             "detail": "We couldn't look up this point's address. Type the address details below."})


# ------------------------------------------------------------------ store serviceability (public)

class ServiceableStoresView(APIView):
    """Which active stores deliver to this point, with an indicative fee (before order-size offers)."""

    permission_classes = [AllowAny]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "quote"

    def get(self, request):
        from stores.models import Store, StoreStatus
        lat, lon = _point(request.query_params)
        stores = Store.objects.filter(status=StoreStatus.ACTIVE, is_active=True).select_related("address", "service_zone").order_by("name")[:200]
        out = []
        for store in stores:
            svc = serviceability(store, lat, lon)
            row = {"id": store.pk, "name": store.name, "serviceable": svc["serviceable"], "reasons": svc["reasons"], "open_now": svc["open_now"],
                   "distance_km": None, "fee": None, "eta_minutes": None}
            if svc["serviceable"]:
                try:
                    q = quote_for_store(store, lat, lon, check_service=False)
                    row.update(distance_km=q["distance_km"], distance_source=q["distance_source"], fee=q["customer_fee_before_discount"],
                               eta_minutes=q["eta_minutes"])
                except DjangoValidationError as exc:
                    row.update(serviceable=False, reasons=[m for v in (exc.message_dict.values() if hasattr(exc, "error_dict") else [exc.messages]) for m in v])
            out.append(row)
        out.sort(key=lambda r: (not r["serviceable"], Decimal(r["distance_km"] or "9999")))
        return Response({"stores": out, "serviceable_count": sum(1 for r in out if r["serviceable"])})


# ------------------------------------------------------------------ checkout quote (customer)

class CheckoutQuoteView(APIView):
    """Server-calculated totals the customer confirms. Pass ``quote_token`` when placing the order."""

    permission_classes = [IsCustomer]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "quote"

    def post(self, request):
        from orders.services import get_owned_active_delivery_address
        from logistics.checkout import fingerprint, save_quote, store_quotes
        from orders.models import FulfillmentType
        from orders.services import build_checkout_preview
        customer = get_customer(request.user)
        fulfillment = request.data.get("fulfillment_type") or FulfillmentType.DELIVERY
        if fulfillment not in FulfillmentType.values:
            raise serializers.ValidationError({"fulfillment_type": "Choose a valid option."})
        preview = build_checkout_preview(customer)
        address = None
        if fulfillment == FulfillmentType.DELIVERY:
            try:
                address = get_owned_active_delivery_address(customer=customer, address_id=request.data.get("delivery_address_id"))
            except DjangoValidationError as exc:
                raise _drf(exc) from exc
        from stores.models import Store
        stores = {s.pk: s for s in Store.objects.filter(pk__in=[g["store_id"] for g in preview["store_groups"]]).select_related("address", "service_zone")}
        groups = [(stores[g["store_id"]], g["items_subtotal"]) for g in preview["store_groups"] if g["store_id"] in stores]
        if fulfillment == FulfillmentType.DELIVERY:
            result = store_quotes(groups, address)
        else:
            result = {"stores": [{"store_id": s.pk, "store_name": s.name, "ok": True} for s, _ in groups], "delivery_total": Decimal("0.00"), "all_ok": True}
        lines = [(row["product"].pk, row["quantity"], row["unit_price"]) for g in preview["store_groups"] for row in g["items"]]
        quote = save_quote(customer=customer, address=address, fulfillment_type=fulfillment, fp=fingerprint(lines, address, fulfillment),
                           result=result, items_subtotal=preview["items_subtotal"])
        return Response({
            "quote_token": str(quote.token), "expires_at": quote.expires_at,
            "items_subtotal": str(preview["items_subtotal"]), "discount_total": str(preview["discount_total"]),
            "delivery_total": str(result["delivery_total"]), "grand_total": str(quote.grand_total),
            "all_deliverable": result["all_ok"], "has_blocking_issues": preview["has_blocking_issues"] or not result["all_ok"],
            "blocking_messages": preview["blocking_messages"] + [f"{s['store_name']}: {s['error']}" for s in result["stores"] if not s["ok"]],
            "stores": [{"store_id": s["store_id"], "store_name": s["store_name"], "ok": s["ok"], "error": s.get("error"),
                        "delivery": s.get("customer")} for s in result["stores"]],
        })


# ------------------------------------------------------------------ admin: pricing versions, simulator, zones

def version_payload(v: DeliveryPricingVersion) -> dict:
    data = jsonable(model_to_dict(v, fields=VERSION_FIELDS))
    data.update({"id": v.pk, "version": v.version, "zone": v.zone_id, "zone_name": v.zone.name if v.zone_id else "Default",
                 "effective_from": v.effective_from, "created_at": v.created_at, "created_by": v.created_by.get_username() if v.created_by_id else None,
                 "fuel_cost_per_km": str(engine.money(engine.fuel_cost_per_km(v)))})
    return data


class PricingVersionsView(APIView):
    permission_classes = [IsManagement]

    def get(self, request):
        _need(request.user, "logistics.view_delivery_operations")
        zone = request.query_params.get("zone")
        qs = DeliveryPricingVersion.objects.select_related("zone", "created_by")
        qs = qs.filter(zone_id=int(zone)) if str(zone or "").isdigit() else qs.filter(zone__isnull=True)
        now = timezone.now()
        try:
            current = active_version(zone=PricingZone.objects.filter(pk=zone).first() if str(zone or "").isdigit() else None)
        except DjangoValidationError:
            current = None
        return Response({
            "active": version_payload(current) if current else None,
            "scheduled": [version_payload(v) for v in qs.filter(effective_from__gt=now)],
            "history": [version_payload(v) for v in qs[:50]],
            "choices": {"fuel_type": DeliveryPricingVersion._meta.get_field("fuel_type").choices, "pricing_mode": engine.Mode.CHOICES,
                        "rounding": engine.Rounding.CHOICES, "funder": engine.Funder.CHOICES},
            "can_edit": request.user.role == Role.SUPER_ADMIN or request.user.has_perm("logistics.manage_delivery_pricing"),
        })

    def post(self, request):
        _need(request.user, "logistics.manage_delivery_pricing")
        zone = None
        if request.data.get("zone"):
            zone = get_object_or_404(PricingZone, pk=request.data["zone"])
        effective = parse_datetime(str(request.data.get("effective_from"))) if request.data.get("effective_from") else None
        if request.data.get("effective_from") and effective is None:
            raise serializers.ValidationError({"effective_from": "Enter a valid date and time."})
        if effective is not None and timezone.is_naive(effective):
            effective = timezone.make_aware(effective)
        data = {k: v for k, v in (request.data.get("settings") or {}).items() if k in VERSION_FIELDS}
        for key in ("energy_price_verified_at",):
            if data.get(key):
                parsed = parse_datetime(str(data[key]))
                if parsed is None:
                    raise serializers.ValidationError({key: "Enter a valid date and time."})
                data[key] = timezone.make_aware(parsed) if timezone.is_naive(parsed) else parsed
            elif key in data:
                data[key] = None
        try:
            v = create_version(actor=request.user, data=data, zone=zone, reason=request.data.get("reason", ""), effective_from=effective, request=request._request)
        except DjangoValidationError as exc:
            raise _drf(exc) from exc
        return Response(version_payload(v), status=201)


class PricingSimulatorView(APIView):
    """Runs the checkout engine with optional overrides. Nothing is saved."""

    permission_classes = [IsManagement]

    def post(self, request):
        _need(request.user, "logistics.view_delivery_operations")
        d = request.data
        zone = PricingZone.objects.filter(pk=d.get("zone")).first() if d.get("zone") else None
        try:
            base = active_version(zone=zone)
            values = {**model_to_dict(base, fields=VERSION_FIELDS), **{k: v for k, v in (d.get("overrides") or {}).items() if k in VERSION_FIELDS}}
            s = SimpleNamespace(**values)
            notes, source = ["Simulated inputs; estimated results."], "manual"
            if d.get("store") and d.get("lat") not in (None, "") and d.get("lon") not in (None, ""):
                from stores.models import Store
                store = get_object_or_404(Store.objects.select_related("address", "service_zone"), pk=d["store"])
                lat, lon = _point(d)
                svc = serviceability(store, lat, lon)
                if not svc["serviceable"]:
                    notes.append("At checkout this store would not deliver here: " + " ".join(svc["reasons"]))
                from .providers import travel_distance
                from .services import store_point
                if store_point(store) is None:
                    raise DjangoValidationError({"store": "This store has no map location."})
                km, source, note = travel_distance(store_point(store), (lat, lon), fallback_factor=s.road_fallback_factor)
                if note:
                    notes.append(note)
            else:
                km = d.get("distance_km")
            ctx = engine.TripContext(distance_km=km, items_subtotal=Decimal(str(d.get("items_subtotal") or 0)),
                                     is_peak=bool(d.get("is_peak")), heavy=bool(d.get("heavy")),
                                     zone_surcharge=zone.service_area_surcharge if zone else Decimal("0"), distance_source=source, notes=notes)
            result = engine.quote(s, ctx)
            batch = None
            if d.get("batch"):
                b = d["batch"]
                batch = engine.batch_quote(s, route_km=b.get("route_km"), stops=b.get("stops") or [], basis=b.get("basis", "distance"))
        except DjangoValidationError as exc:
            raise _drf(exc) from exc
        except (TypeError, ValueError, InvalidOperation):
            raise serializers.ValidationError({"detail": "Check the numbers you entered."}) from None
        return Response({"result": jsonable(result), "batch": jsonable(batch), "based_on": str(base),
                         "overridden": sorted(k for k in (d.get("overrides") or {}) if k in VERSION_FIELDS)})


def zone_payload(z: PricingZone) -> dict:
    return {"id": z.pk, "name": z.name, "state": z.state, "district": z.district, "locality": z.locality, "polygon": z.polygon,
            "service_area_surcharge": str(z.service_area_surcharge), "is_active": z.is_active, "store_count": z.stores.count()}


class ZoneIn(serializers.Serializer):
    name = serializers.CharField(max_length=120)
    state = serializers.CharField(max_length=100, required=False, default="Kerala")
    district = serializers.CharField(max_length=100, required=False, allow_blank=True)
    locality = serializers.CharField(max_length=120, required=False, allow_blank=True)
    polygon = serializers.JSONField(required=False)
    service_area_surcharge = serializers.DecimalField(max_digits=10, decimal_places=2, min_value=0, required=False)
    is_active = serializers.BooleanField(required=False)


class ZonesView(APIView):
    permission_classes = [IsManagement]

    def get(self, request):
        _need(request.user, "logistics.view_delivery_operations")
        return Response([zone_payload(z) for z in PricingZone.objects.all()])

    def post(self, request):
        _need(request.user, "logistics.manage_delivery_pricing")
        ser = ZoneIn(data=request.data)
        ser.is_valid(raise_exception=True)
        data = dict(ser.validated_data)
        try:
            data["polygon"] = validate_polygon(data.get("polygon"))
        except DjangoValidationError as exc:
            raise _drf(exc) from exc
        z = PricingZone.objects.create(**data)
        from core.audit import audit
        audit(request.user, "delivery_zone.created", z, request=request._request, summary=f"Zone {z.name}")
        return Response(zone_payload(z), status=201)


class ZoneDetailView(APIView):
    permission_classes = [IsManagement]

    def patch(self, request, pk):
        _need(request.user, "logistics.manage_delivery_pricing")
        z = get_object_or_404(PricingZone, pk=pk)
        ser = ZoneIn(data=request.data, partial=True)
        ser.is_valid(raise_exception=True)
        data = dict(ser.validated_data)
        if "polygon" in data:
            try:
                data["polygon"] = validate_polygon(data["polygon"])
            except DjangoValidationError as exc:
                raise _drf(exc) from exc
        before = zone_payload(z)
        for k, v in data.items():
            setattr(z, k, v)
        z.save()
        from core.audit import audit
        audit(request.user, "delivery_zone.updated", z, request=request._request, summary=f"Zone {z.name}",
              changes={k: {"from": before.get(k), "to": zone_payload(z).get(k)} for k in data})
        return Response(zone_payload(z))


# ------------------------------------------------------------------ admin: operations report

class DeliveryOperationsView(APIView):
    permission_classes = [IsManagement]

    def get(self, request):
        _need(request.user, "logistics.view_delivery_operations")
        from deliveries.models import Delivery, DeliveryAttempt, DeliveryPartner, DeliveryStatus, PartnerStatus
        from orders.models import FulfillmentType, Order, StoreOrder
        from stores.models import Store, StoreStatus
        days = min(max(int(request.query_params.get("days") or 30), 1), 365)
        since = timezone.now() - timedelta(days=days)

        stores = Store.objects.filter(status=StoreStatus.ACTIVE).select_related("address", "service_zone")
        store_issues = [{"id": s.pk, "name": s.name, "store_code": s.store_code, "problems": p}
                        for s in stores if (p := store_location_problems(s))]
        bad_dest = Order.objects.filter(fulfillment_type=FulfillmentType.DELIVERY, placed_at__gte=since).filter(
            Q(delivery_latitude__isnull=True) | Q(delivery_longitude__isnull=True) | (Q(delivery_latitude=0) & Q(delivery_longitude=0)))
        partners = DeliveryPartner.objects.filter(status=PartnerStatus.APPROVED)
        failed = DeliveryAttempt.objects.filter(outcome=DeliveryAttempt.Outcome.FAILED, ended_at__gte=since)

        priced = StoreOrder.objects.filter(created_at__gte=since).exclude(delivery_pricing={})
        totals = {k: Decimal("0") for k in ("customer_fee_before_discount", "delivery_discount", "customer_fee", "delivery_tax", "partner_payout",
                                              "platform_funded_promotion", "store_funded_promotion", "estimated_cost", "platform_subsidy", "delivery_contribution")}
        estimated_km = Decimal("0")
        review = []
        n = 0
        for so in priced.only("pk", "store_order_number", "delivery_pricing")[:5000]:
            snap = so.delivery_pricing
            n += 1
            for k in totals:
                totals[k] += Decimal(str(snap.get(k) or 0))
            estimated_km += Decimal(str(snap.get("distance_km") or 0))
            if snap.get("distance_source") == "estimated" or Decimal(str(snap.get("capped_by_max_fee") or 0)) > 0:
                review.append({"store_order": so.store_order_number, "why": "Estimated distance" if snap.get("distance_source") == "estimated" else "Fee capped at maximum",
                               "customer_fee": snap.get("customer_fee"), "estimated_cost": snap.get("estimated_cost")})
        paid_out = PartnerEarning.objects.filter(created_at__gte=since).aggregate(total=Sum("amount"), unpaid=Sum("amount", filter=Q(status="UNPAID")))
        return Response({
            "period_days": days,
            "stores_with_location_problems": store_issues,
            "orders_with_invalid_destination": [{"order_number": o.order_number, "placed_at": o.placed_at} for o in bad_dest[:50]],
            "partners": {"approved": partners.count(), "online": partners.filter(is_online=True).count()},
            "deliveries": {"active": Delivery.objects.filter(status__in=["OFFERED", "ACCEPTED", "AT_STORE", "IN_TRANSIT", "ARRIVED"]).count(),
                           "waiting_for_partner": Delivery.objects.filter(status=DeliveryStatus.PENDING_ASSIGNMENT).count(),
                           "needs_attention": Delivery.objects.filter(needs_attention=True).count(),
                           "failed_attempts": failed.count(),
                           "failure_reasons": list(failed.values("failure_reason").annotate(n=Count("pk")).order_by("-n"))},
            "economics": {"priced_deliveries": n, **{k: str(engine.money(v)) for k, v in totals.items()},
                          "estimated_km": str(engine.money(estimated_km)),
                          "partner_earnings_recorded": str(paid_out["total"] or 0), "partner_earnings_unpaid": str(paid_out["unpaid"] or 0),
                          "note": "Estimated cost and subsidy come from each order's pricing snapshot. Actual route distance is not recorded yet, so estimated vs actual km cannot be compared."},
            "needs_review": review[:50],
        })


# ------------------------------------------------------------------ partner earnings

def earning_payload(e: PartnerEarning, *, admin=False) -> dict:
    so = e.delivery.store_order if e.delivery_id else None
    data = {"id": e.pk, "kind": e.kind, "kind_label": e.get_kind_display(), "amount": str(e.amount), "status": e.status,
            "paid_at": e.paid_at, "created_at": e.created_at, "attempt_number": e.attempt_number,
            "store_order": so.store_order_number if so else None, "breakdown": e.breakdown, "note": e.note}
    if admin:
        data["partner"] = e.partner.user.get_username()
        data["payout_reference"] = e.payout_reference
    return data


class PartnerEarningsView(APIView):
    """A rider's own earnings. Riders cannot change amounts or rules."""

    permission_classes = [IsDeliveryPartner]

    def get(self, request):
        partner = get_delivery_partner(request.user)
        qs = PartnerEarning.objects.filter(partner=partner).select_related("delivery__store_order")
        today = timezone.localdate()
        agg = qs.aggregate(total=Sum("amount"), unpaid=Sum("amount", filter=Q(status="UNPAID")),
                           today=Sum("amount", filter=Q(created_at__date=today)), deliveries=Count("pk", filter=Q(kind="DELIVERY")))
        return Response({"summary": {k: str(v or 0) for k, v in agg.items()}, "results": [earning_payload(e) for e in qs[:100]]})


class AdminEarningsView(APIView):
    permission_classes = [IsManagement]

    def get(self, request):
        _need(request.user, "logistics.view_delivery_operations")
        qs = PartnerEarning.objects.select_related("partner__user", "delivery__store_order")
        if request.query_params.get("status") in ("PAID", "UNPAID"):
            qs = qs.filter(status=request.query_params["status"])
        return Response([earning_payload(e, admin=True) for e in qs[:200]])

    def post(self, request):
        """Mark earnings as paid: {"ids": [...], "payout_reference": "..."}."""
        _need(request.user, "logistics.manage_partner_payouts")
        ids = [int(i) for i in request.data.get("ids") or [] if str(i).isdigit()][:500]
        ref = str(request.data.get("payout_reference") or "").strip()[:64]
        if not ids or not ref:
            raise serializers.ValidationError({"detail": "Choose earnings and enter the payout reference."})
        n = PartnerEarning.objects.filter(pk__in=ids, status="UNPAID").update(status="PAID", paid_at=timezone.now(), payout_reference=ref)
        from core.audit import audit
        audit(request.user, "partner_earnings.paid", None, object_type="PartnerEarning", object_id="bulk", request=request._request,
              summary=f"Marked {n} earnings paid ({ref})", ids=ids)
        return Response({"updated": n})


# ------------------------------------------------------------------ store: finance and location readiness

class StoreFinanceView(APIView):
    """Per-order money for the store: what it sold, commission, store-funded promotions and its settlement."""

    permission_classes = [IsStoreUser]

    def get(self, request):
        from orders.models import StoreOrder
        membership = get_store_membership(request.user)
        store = membership.store
        rate = Decimal(store.commission_percentage or 0) / 100
        rows, totals = [], {k: Decimal("0") for k in ("items", "commission", "store_promotions", "settlement", "delivery_fees_paid_by_customers")}
        for so in StoreOrder.objects.filter(store=store).exclude(status__in=["CANCELLED", "REJECTED"]).order_by("-created_at")[:100]:
            snap = so.delivery_pricing or {}
            promo = Decimal(str(snap.get("store_funded_promotion") or 0))
            commission = engine.money(so.items_subtotal * rate)
            settlement = engine.money(so.items_subtotal - commission - promo)
            row = {"store_order": so.store_order_number, "status": so.status, "created_at": so.created_at, "items": str(so.items_subtotal),
                   "commission": str(commission), "store_funded_promotion": str(promo), "settlement": str(settlement),
                   "delivery_fee_paid_by_customer": str(so.delivery_charge)}
            rows.append(row)
            for k, v in (("items", so.items_subtotal), ("commission", commission), ("store_promotions", promo), ("settlement", settlement),
                         ("delivery_fees_paid_by_customers", so.delivery_charge)):
                totals[k] += v
        return Response({"commission_percentage": str(store.commission_percentage), "totals": {k: str(engine.money(v)) for k, v in totals.items()},
                         "orders": rows, "location_problems": store_location_problems(store),
                         "note": "Delivery fees are collected by Zuuvi and pay for delivery; they are not store revenue. Delivery costs are not charged to the store."})
