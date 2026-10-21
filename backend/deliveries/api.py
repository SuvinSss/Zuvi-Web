"""REST endpoints for the delivery domain (partner, store, customer, admin)."""
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db.models import Q
from django.http import Http404
from django.shortcuts import get_object_or_404
from django.utils import timezone
from drf_spectacular.utils import extend_schema
from rest_framework import generics, serializers, status
from rest_framework.exceptions import PermissionDenied
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.response import Response
from rest_framework.throttling import UserRateThrottle
from rest_framework.views import APIView

from accounts.models import Role
from core.files import private_file_response
from core.pagination import StandardPagination
from core.permissions import (
    IsDeliveryPartner,
    IsDeliveryPartnerProfile,
    IsManagement,
    IsStoreUser,
    get_customer,
    get_delivery_partner,
    get_store_membership,
    is_management,
    is_support_staff,
)
from notifications.models import Kind
from notifications.services import notify
from orders.models import Order

from . import services
from .models import (
    Delivery,
    DeliveryAttempt,
    DeliveryEvidence,
    DeliveryPartner,
    DeliveryStatus,
    EvidenceKind,
    EvidencePhoto,
    LocationPing,
    PartnerStatus,
)

ACTIVE = [DeliveryStatus.OFFERED, DeliveryStatus.ACCEPTED, DeliveryStatus.AT_STORE,
          DeliveryStatus.IN_TRANSIT, DeliveryStatus.ARRIVED]


class LocationThrottle(UserRateThrottle):
    scope = "location"


# ------------------------------------------------------------------ serializers

class PartnerSerializer(serializers.ModelSerializer):
    username = serializers.CharField(source="user.username", read_only=True)
    full_name = serializers.SerializerMethodField()
    is_approved = serializers.BooleanField(read_only=True)

    class Meta:
        model = DeliveryPartner
        fields = ["id", "username", "full_name", "status", "is_approved", "vehicle_type", "vehicle_number",
                  "is_online", "last_latitude", "last_longitude", "last_location_at", "status_reason", "created_at"]
        read_only_fields = ["id", "username", "full_name", "status", "is_approved", "last_latitude",
                            "last_longitude", "last_location_at", "status_reason", "created_at", "is_online"]

    def get_full_name(self, obj) -> str:
        return obj.user.get_full_name()


class PhotoSerializer(serializers.ModelSerializer):
    url = serializers.SerializerMethodField()

    class Meta:
        model = EvidencePhoto
        fields = ["id", "url", "content_type", "size", "width", "height", "created_at"]

    def get_url(self, obj) -> str:
        return f"/api/v1/evidence-photos/{obj.pk}/file/"


class EvidenceSerializer(serializers.ModelSerializer):
    photos = PhotoSerializer(many=True, read_only=True)
    captured_by_name = serializers.CharField(source="captured_by.get_full_name", read_only=True)

    class Meta:
        model = DeliveryEvidence
        fields = ["id", "kind", "attempt_number", "latitude", "longitude", "accuracy_m", "distance_from_target_m",
                  "within_tolerance", "notes", "recipient_name", "captured_by_name", "store_confirmed_at",
                  "created_at", "photos"]


class AttemptSerializer(serializers.ModelSerializer):
    class Meta:
        model = DeliveryAttempt
        fields = ["number", "outcome", "failure_reason", "failure_note", "started_at", "ended_at"]


class DeliverySerializer(serializers.ModelSerializer):
    """Operational view (partner/store/admin). Customer data is shown only when needed."""

    order_number = serializers.CharField(source="store_order.order.order_number", read_only=True)
    store_order_number = serializers.CharField(source="store_order.store_order_number", read_only=True)
    store_name = serializers.CharField(source="store_order.store_name", read_only=True)
    partner = serializers.SerializerMethodField()
    customer = serializers.SerializerMethodField()
    offer_expires_at = serializers.SerializerMethodField()
    pickup = serializers.SerializerMethodField()
    dropoff = serializers.SerializerMethodField()
    trip = serializers.SerializerMethodField()

    class Meta:
        model = Delivery
        fields = ["id", "status", "attempt_number", "order_number", "store_order_number", "store_name",
                  "partner", "customer", "pickup", "dropoff", "needs_attention", "rejection_count",
                  "offer_expires_at", "assigned_at", "picked_up_at", "delivered_at", "created_at", "trip"]

    def get_trip(self, obj):
        """Distance and the rider's pay for this job (from the order's frozen pricing). Never the customer's fee internals."""
        snap = obj.store_order.delivery_pricing or {}
        if not snap:
            return None
        return {"distance_km": snap.get("distance_km"), "distance_source": snap.get("distance_source"),
                "estimated_payout": snap.get("partner_payout"), "payout_breakdown": snap.get("rider_breakdown"),
                "eta_minutes": snap.get("eta_minutes")}

    def get_partner(self, obj):
        if not obj.partner_id:
            return None
        return {"id": obj.partner_id, "name": obj.partner.user.get_full_name(), "phone": obj.partner.user.phone_number,
                "vehicle_type": obj.partner.vehicle_type}

    def _reveal_customer(self, obj) -> bool:
        request = self.context.get("request")
        if request is None:
            return False
        if is_management(request.user) or get_store_membership(request.user):
            return True
        # Partners only learn the customer's details once they have accepted.
        return obj.status in (DeliveryStatus.ACCEPTED, DeliveryStatus.AT_STORE, DeliveryStatus.IN_TRANSIT,
                              DeliveryStatus.ARRIVED, DeliveryStatus.FAILED, DeliveryStatus.DELIVERED)

    def get_customer(self, obj):
        if not self._reveal_customer(obj):
            return None
        order = obj.store_order.order
        return {"name": order.delivery_recipient_name, "phone": order.delivery_phone_number,
                "instructions": order.delivery_instructions}

    def get_pickup(self, obj):
        pickup = obj.store_order.pickup_location
        return {"latitude": _f(obj.pickup_latitude), "longitude": _f(obj.pickup_longitude),
                "name": pickup.name if pickup else obj.store_order.store_name}

    def get_dropoff(self, obj):
        order = obj.store_order.order
        base = {"latitude": _f(obj.dropoff_latitude), "longitude": _f(obj.dropoff_longitude),
                "city": order.delivery_city, "postal_code": order.delivery_postal_code}
        if self._reveal_customer(obj):
            base.update(line1=order.delivery_line1, line2=order.delivery_line2, landmark=order.delivery_landmark)
        return base

    def get_offer_expires_at(self, obj):
        offer = next((a for a in obj.assignments.all() if a.status == "OFFERED"), None)
        return offer.expires_at if offer else None


def _f(value):
    return float(value) if value is not None else None


class RejectSerializer(serializers.Serializer):
    reason = serializers.CharField(required=False, allow_blank=True, max_length=255)


class LocationSerializer(serializers.Serializer):
    latitude = serializers.DecimalField(max_digits=9, decimal_places=6)
    longitude = serializers.DecimalField(max_digits=9, decimal_places=6)
    accuracy_m = serializers.FloatField(required=False, allow_null=True, min_value=0)
    device_time = serializers.DateTimeField(required=False, allow_null=True)


class EvidenceInputSerializer(serializers.Serializer):
    latitude = serializers.DecimalField(max_digits=9, decimal_places=6)
    longitude = serializers.DecimalField(max_digits=9, decimal_places=6)
    accuracy_m = serializers.FloatField(required=False, allow_null=True, min_value=0)
    notes = serializers.CharField(required=False, allow_blank=True, max_length=2000)
    recipient_name = serializers.CharField(required=False, allow_blank=True, max_length=150)
    otp = serializers.CharField(required=False, allow_blank=True, max_length=10)
    photos = serializers.ListField(child=serializers.ImageField(), required=False, write_only=True)


class FailSerializer(serializers.Serializer):
    reason = serializers.ChoiceField(choices=DeliveryAttempt.FailureReason.choices)
    note = serializers.CharField(required=False, allow_blank=True, max_length=2000)
    latitude = serializers.DecimalField(max_digits=9, decimal_places=6, required=False, allow_null=True)
    longitude = serializers.DecimalField(max_digits=9, decimal_places=6, required=False, allow_null=True)


class AssignSerializer(serializers.Serializer):
    partner_id = serializers.IntegerField()
    reason = serializers.CharField(required=False, allow_blank=True, max_length=255)


# ------------------------------------------------------------------ querysets

def delivery_queryset():
    return Delivery.objects.select_related(
        "store_order__order__customer__user", "store_order__store", "store_order__pickup_location",
        "partner__user",
    ).prefetch_related("assignments")


def visible_deliveries(user):
    """Deliveries a user may see; the ownership rules live here and nowhere else."""
    qs = delivery_queryset()
    if is_management(user) or is_support_staff(user):
        return qs
    partner = get_delivery_partner(user, approved_only=False)
    if partner:
        return qs.filter(partner=partner)
    membership = get_store_membership(user)
    if membership:
        return qs.filter(store_order__store_id=membership.store_id)
    customer = get_customer(user)
    if customer:
        return qs.filter(store_order__order__customer=customer)
    return qs.none()


def _partner_delivery(request, pk) -> Delivery:
    partner = get_delivery_partner(request.user)
    return get_object_or_404(delivery_queryset(), pk=pk, partner=partner), partner


# ------------------------------------------------------------------ partner

class PartnerProfileView(generics.RetrieveUpdateAPIView):
    serializer_class = PartnerSerializer
    permission_classes = [IsDeliveryPartnerProfile]

    def get_object(self):
        return get_delivery_partner(self.request.user, approved_only=False)


class PartnerOnlineSerializer(serializers.Serializer):
    is_online = serializers.BooleanField()
    latitude = serializers.DecimalField(max_digits=9, decimal_places=6, required=False)
    longitude = serializers.DecimalField(max_digits=9, decimal_places=6, required=False)


class PartnerOnlineView(APIView):
    permission_classes = [IsDeliveryPartner]

    @extend_schema(request=PartnerOnlineSerializer, responses=PartnerSerializer)
    def post(self, request):
        data = PartnerOnlineSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        partner = get_delivery_partner(request.user)
        partner.is_online = data.validated_data["is_online"]
        fields = ["is_online", "updated_at"]
        if "latitude" in data.validated_data and "longitude" in data.validated_data:
            lat, lon = services._coords(data.validated_data["latitude"], data.validated_data["longitude"])
            partner.last_latitude, partner.last_longitude, partner.last_location_at = lat, lon, timezone.now()
            fields += ["last_latitude", "last_longitude", "last_location_at"]
        elif partner.is_online and partner.last_latitude is None:
            return Response({"location": ["Share your location to go online."]}, status=400)
        partner.save(update_fields=fields)
        return Response(PartnerSerializer(partner).data)


class MyDeliveriesView(generics.ListAPIView):
    serializer_class = DeliverySerializer
    permission_classes = [IsDeliveryPartner]
    pagination_class = StandardPagination

    def get_queryset(self):
        qs = delivery_queryset().filter(partner=get_delivery_partner(self.request.user))
        scope = self.request.query_params.get("scope", "active")
        if scope == "active":
            qs = qs.filter(status__in=ACTIVE)
        elif scope == "history":
            qs = qs.exclude(status__in=ACTIVE)
        return qs.order_by("-updated_at")


class DeliveryDetailView(generics.RetrieveAPIView):
    """Any role, but only for deliveries that role is allowed to see."""

    serializer_class = DeliverySerializer

    def get_queryset(self):
        return visible_deliveries(self.request.user)


class _PartnerAction(APIView):
    permission_classes = [IsDeliveryPartner]

    def respond(self, delivery):
        delivery = delivery_queryset().get(pk=delivery.pk)
        return Response(DeliverySerializer(delivery, context={"request": self.request}).data)


class AcceptView(_PartnerAction):
    @extend_schema(request=None, responses=DeliverySerializer)
    def post(self, request, pk):
        _, partner = _partner_delivery(request, pk)
        return self.respond(services.accept_assignment(pk, partner))


class RejectView(_PartnerAction):
    @extend_schema(request=RejectSerializer, responses=DeliverySerializer)
    def post(self, request, pk):
        _, partner = _partner_delivery(request, pk)
        data = RejectSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        return self.respond(services.reject_assignment(pk, partner, reason=data.validated_data.get("reason", "")))


class ArriveStoreView(_PartnerAction):
    @extend_schema(request=None, responses=DeliverySerializer)
    def post(self, request, pk):
        _, partner = _partner_delivery(request, pk)
        return self.respond(services.arrive_at_store(pk, partner))


class ArriveCustomerView(_PartnerAction):
    @extend_schema(request=None, responses=DeliverySerializer)
    def post(self, request, pk):
        _, partner = _partner_delivery(request, pk)
        return self.respond(services.mark_arrived(pk, partner))


class _EvidenceAction(_PartnerAction):
    parser_classes = [MultiPartParser, FormParser]

    def parse(self, request):
        data = EvidenceInputSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        # Files are validated by content in the service (not by the serializer's lenient check).
        return data.validated_data, request.FILES.getlist("photos")


class PickupView(_EvidenceAction):
    @extend_schema(request={"multipart/form-data": EvidenceInputSerializer}, responses=DeliverySerializer)
    def post(self, request, pk):
        _, partner = _partner_delivery(request, pk)
        data, files = self.parse(request)
        return self.respond(services.confirm_pickup(
            pk, partner, photos=files, latitude=data["latitude"], longitude=data["longitude"],
            accuracy_m=data.get("accuracy_m"), notes=data.get("notes", "")))


class CompleteView(_EvidenceAction):
    @extend_schema(request={"multipart/form-data": EvidenceInputSerializer}, responses=DeliverySerializer)
    def post(self, request, pk):
        _, partner = _partner_delivery(request, pk)
        data, files = self.parse(request)
        return self.respond(services.complete_delivery_checked(
            pk, partner, photos=files, latitude=data["latitude"], longitude=data["longitude"],
            accuracy_m=data.get("accuracy_m"), notes=data.get("notes", ""),
            recipient_name=data.get("recipient_name", ""), otp=data.get("otp", "")))


class FailView(_PartnerAction):
    @extend_schema(request=FailSerializer, responses=DeliverySerializer)
    def post(self, request, pk):
        _, partner = _partner_delivery(request, pk)
        data = FailSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        v = data.validated_data
        return self.respond(services.fail_delivery(pk, partner, reason=v["reason"], note=v.get("note", ""),
                                                   latitude=v.get("latitude"), longitude=v.get("longitude")))


class LocationView(APIView):
    permission_classes = [IsDeliveryPartner]
    throttle_classes = [LocationThrottle]

    @extend_schema(request=LocationSerializer, responses={201: None})
    def post(self, request, pk):
        _, partner = _partner_delivery(request, pk)
        data = LocationSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        v = data.validated_data
        ping = services.record_location(pk, partner, latitude=v["latitude"], longitude=v["longitude"],
                                        accuracy_m=v.get("accuracy_m"), device_time=v.get("device_time"))
        return Response({"recorded_at": ping.recorded_at}, status=status.HTTP_201_CREATED)


class PingSerializer(serializers.ModelSerializer):
    class Meta:
        model = LocationPing
        fields = ["latitude", "longitude", "accuracy_m", "recorded_at"]


class TrackingHistoryView(generics.ListAPIView):
    """Full GPS trail: the assigned partner and administrators only (not customers or other stores)."""

    serializer_class = PingSerializer
    pagination_class = StandardPagination

    def get_queryset(self):
        user = self.request.user
        qs = delivery_queryset()
        if is_management(user):
            delivery = get_object_or_404(qs, pk=self.kwargs["pk"])
        else:
            partner = get_delivery_partner(user, approved_only=False)
            if partner is None:
                raise PermissionDenied("Only the assigned partner or an administrator can view the GPS history.")
            delivery = get_object_or_404(qs, pk=self.kwargs["pk"], partner=partner)
        return LocationPing.objects.filter(delivery=delivery).order_by("recorded_at", "pk")


# ------------------------------------------------------------------ customer tracking

class OrderTrackingView(APIView):
    """GET /orders/{id}/tracking/ - only the order's own customer (or admin/support)."""

    @extend_schema(responses={200: dict})
    def get(self, request, pk):
        user = request.user
        order_qs = Order.objects.filter(pk=pk)
        if not (is_management(user) or is_support_staff(user)):
            customer = get_customer(user)
            if customer is None:
                raise PermissionDenied("Only the customer who placed this order can track it.")
            order_qs = order_qs.filter(customer=customer)
        order = get_object_or_404(order_qs)
        customer_view = not (is_management(user) or is_support_staff(user))
        deliveries = delivery_queryset().filter(store_order__order=order).order_by("pk")
        items = []
        for delivery in deliveries:
            snapshot = services.tracking_snapshot(delivery, for_customer=customer_view)
            snapshot["store_order_number"] = delivery.store_order.store_order_number
            snapshot["store_name"] = delivery.store_order.store_name
            items.append(snapshot)
        return Response({"order_id": order.pk, "order_number": order.order_number, "order_status": order.status,
                         "deliveries": items})


# ------------------------------------------------------------------ evidence

def _can_view_evidence(user, delivery, evidence_kind=None) -> bool:
    if is_management(user) or is_support_staff(user):
        return True
    partner = get_delivery_partner(user, approved_only=False)
    if partner and delivery.partner_id == partner.pk:
        return True
    membership = get_store_membership(user)
    if membership and delivery.store_order.store_id == membership.store_id:
        return True
    customer = get_customer(user)
    if customer and delivery.store_order.order.customer_id == customer.pk:
        return evidence_kind in (None, EvidenceKind.DELIVERY)  # customers never see pickup proof
    return False


class DeliveryEvidenceView(APIView):
    @extend_schema(responses=EvidenceSerializer(many=True))
    def get(self, request, pk):
        delivery = get_object_or_404(delivery_queryset(), pk=pk)
        if not _can_view_evidence(request.user, delivery):
            raise Http404  # do not reveal that the delivery exists
        items = delivery.evidence.select_related("captured_by").prefetch_related("photos")
        if get_customer(request.user):
            items = items.filter(kind=EvidenceKind.DELIVERY)
        return Response(EvidenceSerializer(items, many=True).data)


class EvidencePhotoFileView(APIView):
    """Private photo bytes, streamed only after an ownership check."""

    @extend_schema(responses={200: bytes})
    def get(self, request, pk):
        photo = get_object_or_404(EvidencePhoto.objects.select_related(
            "evidence__delivery__store_order__order", "evidence__delivery__store_order__store"), pk=pk)
        delivery = photo.evidence.delivery
        if not _can_view_evidence(request.user, delivery, photo.evidence.kind):
            raise Http404
        return private_file_response(photo.file)


class StoreConfirmPickupView(APIView):
    permission_classes = [IsStoreUser]

    @extend_schema(request=None, responses=EvidenceSerializer)
    def post(self, request, pk):
        membership = get_store_membership(request.user)
        evidence = services.store_confirm_pickup(pk, store=membership.store, user=request.user)
        return Response(EvidenceSerializer(evidence).data)


class StoreDeliveriesView(generics.ListAPIView):
    serializer_class = DeliverySerializer
    permission_classes = [IsStoreUser]
    pagination_class = StandardPagination

    def get_queryset(self):
        membership = get_store_membership(self.request.user)
        qs = delivery_queryset().filter(store_order__store_id=membership.store_id)
        if self.request.query_params.get("status"):
            qs = qs.filter(status=self.request.query_params["status"])
        return qs.order_by("-created_at")


# ------------------------------------------------------------------ admin

class AdminDeliveryListView(generics.ListAPIView):
    serializer_class = DeliverySerializer
    permission_classes = [IsManagement]
    pagination_class = StandardPagination

    def get_queryset(self):
        qs = delivery_queryset()
        p = self.request.query_params
        if p.get("status"):
            qs = qs.filter(status=p["status"])
        if p.get("needs_attention") in {"1", "true"}:
            qs = qs.filter(needs_attention=True)
        if p.get("partner"):
            qs = qs.filter(partner_id=p["partner"])
        if p.get("q"):
            qs = qs.filter(Q(store_order__order__order_number__icontains=p["q"]) | Q(store_order__store_order_number__icontains=p["q"]))
        return qs.order_by("-created_at")


class AdminAssignView(APIView):
    permission_classes = [IsManagement]

    @extend_schema(request=AssignSerializer, responses=DeliverySerializer)
    def post(self, request, pk):
        get_object_or_404(Delivery, pk=pk)
        data = AssignSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        services.admin_assign(pk, data.validated_data["partner_id"], actor=request.user,
                              reason=data.validated_data.get("reason", ""))
        return Response(DeliverySerializer(delivery_queryset().get(pk=pk), context={"request": request}).data)


class AdminRetryView(APIView):
    permission_classes = [IsManagement]

    @extend_schema(request=None, responses=DeliverySerializer)
    def post(self, request, pk):
        get_object_or_404(Delivery, pk=pk)
        services.retry_delivery(pk, actor=request.user)
        return Response(DeliverySerializer(delivery_queryset().get(pk=pk), context={"request": request}).data)


class AdminCancelView(APIView):
    permission_classes = [IsManagement]

    @extend_schema(request=RejectSerializer, responses=DeliverySerializer)
    def post(self, request, pk):
        get_object_or_404(Delivery, pk=pk)
        data = RejectSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        services.cancel_delivery(pk, actor=request.user, reason=data.validated_data.get("reason", ""))
        return Response(DeliverySerializer(delivery_queryset().get(pk=pk), context={"request": request}).data)


class AdminDeliveryDetailView(generics.RetrieveAPIView):
    permission_classes = [IsManagement]
    serializer_class = DeliverySerializer
    queryset = delivery_queryset()


class AdminAttemptsView(APIView):
    permission_classes = [IsManagement]

    @extend_schema(responses=AttemptSerializer(many=True))
    def get(self, request, pk):
        delivery = get_object_or_404(Delivery, pk=pk)
        return Response(AttemptSerializer(delivery.attempts.all(), many=True).data)


class AdminPartnerListView(generics.ListAPIView):
    serializer_class = PartnerSerializer
    permission_classes = [IsManagement]
    pagination_class = StandardPagination

    def get_queryset(self):
        qs = DeliveryPartner.objects.select_related("user")
        if self.request.query_params.get("status"):
            qs = qs.filter(status=self.request.query_params["status"])
        return qs


class PartnerDecisionSerializer(serializers.Serializer):
    reason = serializers.CharField(required=False, allow_blank=True, max_length=255)


class _AdminPartnerDecision(APIView):
    permission_classes = [IsManagement]
    target = None
    require_reason = False
    allowed_from = ()

    @extend_schema(request=PartnerDecisionSerializer, responses=PartnerSerializer)
    def post(self, request, pk):
        get_object_or_404(DeliveryPartner, pk=pk)
        data = PartnerDecisionSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        try:
            partner = services.decide_partner(pk, self.target, actor=request.user, reason=data.validated_data.get("reason", ""))
        except DjangoValidationError as exc:
            return Response(exc.message_dict, status=400)
        return Response(PartnerSerializer(partner).data)


class ApprovePartnerView(_AdminPartnerDecision):
    target = PartnerStatus.APPROVED
    allowed_from = (PartnerStatus.PENDING, PartnerStatus.SUSPENDED)


class RejectPartnerView(_AdminPartnerDecision):
    target = PartnerStatus.REJECTED
    require_reason = True
    allowed_from = (PartnerStatus.PENDING,)


class SuspendPartnerView(_AdminPartnerDecision):
    target = PartnerStatus.SUSPENDED
    require_reason = True
    allowed_from = (PartnerStatus.APPROVED,)
