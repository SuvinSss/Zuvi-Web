"""Administration endpoints. Fine-grained Django permissions are honoured exactly as in the management portal."""
from django.contrib.auth import get_user_model
from django.db.models import Avg, Count, Q, Sum
from django.shortcuts import get_object_or_404
from django.utils import timezone
from drf_spectacular.utils import extend_schema
from rest_framework import generics, serializers
from rest_framework.exceptions import PermissionDenied
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts.models import Role
from core.audit import audit
from core.models import AuditEvent
from core.pagination import StandardPagination
from core.permissions import IsManagement
from deliveries.models import Delivery, DeliveryPartner
from orders.decorators import user_has_order_permission
from orders.management_status import admin_cancel_order, update_order_status
from orders.models import Order, OrderStatus
from reviews.models import RatingAggregate, TargetType
from stores.decorators import user_has_store_permission
from stores.models import Store, StoreStatus
from stores.services import record_status_change
from support.models import Complaint, Ticket

from .customer import order_detail, order_summary

User = get_user_model()


def _require(user, check, perm):
    if not check(user, perm):
        raise PermissionDenied("You do not have permission to perform this action.")


# ------------------------------------------------------------------ users

class AdminUserSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ["id", "username", "email", "first_name", "last_name", "phone_number", "role", "is_active", "last_login", "date_joined"]


class AdminUsersView(generics.ListAPIView):
    permission_classes = [IsManagement]
    serializer_class = AdminUserSerializer
    pagination_class = StandardPagination

    def get_queryset(self):
        qs = User.objects.all().order_by("-date_joined")
        p = self.request.query_params
        if p.get("role"):
            qs = qs.filter(role=p["role"])
        if p.get("active") in {"1", "true", "0", "false"}:
            qs = qs.filter(is_active=p["active"] in {"1", "true"})
        if p.get("q"):
            qs = qs.filter(Q(username__icontains=p["q"]) | Q(email__icontains=p["q"]) | Q(phone_number__icontains=p["q"]))
        return qs


class ReasonSerializer(serializers.Serializer):
    reason = serializers.CharField(max_length=255)


class _UserActive(APIView):
    permission_classes = [IsManagement]
    activate = False

    @extend_schema(request=ReasonSerializer, responses=AdminUserSerializer)
    def post(self, request, pk):
        target = get_object_or_404(User, pk=pk)
        data = ReasonSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        if target.pk == request.user.pk:
            raise PermissionDenied("You cannot change your own account status.")
        if target.role in (Role.ADMIN, Role.SUPER_ADMIN) and request.user.role != Role.SUPER_ADMIN:
            raise PermissionDenied("Only a super admin can change an administrator's account.")
        if target.is_active == self.activate:
            raise serializers.ValidationError({"detail": "The account is already in that state."})
        target.is_active = self.activate
        target.save(update_fields=["is_active", "updated_at"])
        if not self.activate:
            from rest_framework.authtoken.models import Token

            Token.objects.filter(user=target).delete()
            if hasattr(target, "delivery_partner"):
                DeliveryPartner.objects.filter(user=target).update(is_online=False)
        audit(request.user, "user.reactivate" if self.activate else "user.suspend", target, summary=data.validated_data["reason"], request=request._request)
        return Response(AdminUserSerializer(target).data)


class SuspendUserView(_UserActive):
    activate = False


class ReactivateUserView(_UserActive):
    activate = True


# ------------------------------------------------------------------ stores

class StoreStatusSerializer(serializers.Serializer):
    status = serializers.ChoiceField(choices=StoreStatus.choices)
    reason = serializers.CharField(required=False, allow_blank=True, max_length=255)


class AdminStoresView(generics.ListAPIView):
    permission_classes = [IsManagement]
    serializer_class = serializers.Serializer
    pagination_class = StandardPagination

    def list(self, request, *args, **kwargs):
        qs = Store.objects.select_related("address", "category").order_by("name")
        if request.query_params.get("status"):
            qs = qs.filter(status=request.query_params["status"])
        if request.query_params.get("q"):
            qs = qs.filter(Q(name__icontains=request.query_params["q"]) | Q(store_code__icontains=request.query_params["q"]))
        page = self.paginate_queryset(qs)
        ratings = {a.target_id: a for a in RatingAggregate.objects.filter(target_type=TargetType.STORE, target_id__in=[s.pk for s in page])}
        return self.get_paginated_response([
            {"id": s.pk, "store_code": s.store_code, "name": s.name, "status": s.status, "is_active": s.is_active, "city": s.address.city,
             "category": s.category.name if s.category_id else None,
             "rating": {"average": float(ratings[s.pk].average), "count": ratings[s.pk].count} if s.pk in ratings else {"average": 0.0, "count": 0}}
            for s in page])


class AdminStoreStatusView(APIView):
    permission_classes = [IsManagement]

    @extend_schema(request=StoreStatusSerializer, responses=dict)
    def post(self, request, pk):
        store = get_object_or_404(Store, pk=pk)
        data = StoreStatusSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        from stores.status import permission_for_transition

        perm = permission_for_transition(store.status, data.validated_data["status"])
        if perm:
            _require(request.user, user_has_store_permission, perm)
        record_status_change(store=store, new_status=data.validated_data["status"], changed_by=request.user,
                             reason=data.validated_data.get("reason", ""), request=request._request)  # raises 400 on invalid transitions
        store.refresh_from_db()
        return Response({"id": store.pk, "status": store.status})


# ------------------------------------------------------------------ orders

class AdminOrdersView(generics.ListAPIView):
    permission_classes = [IsManagement]
    serializer_class = serializers.Serializer
    pagination_class = StandardPagination

    def list(self, request, *args, **kwargs):
        _require(request.user, user_has_order_permission, "orders.view_order")
        qs = Order.objects.select_related("customer__user").annotate(item_count=Sum("store_orders__items__quantity")).order_by("-placed_at")
        p = request.query_params
        for key, lookup in (("status", "status"), ("fulfillment_type", "fulfillment_type"), ("payment_status", "payment_status"),
                            ("store", "store_orders__store_id")):
            if p.get(key):
                qs = qs.filter(**{lookup: p[key]})
        if p.get("q"):
            qs = qs.filter(Q(order_number__icontains=p["q"]) | Q(customer__user__username__icontains=p["q"]) | Q(delivery_phone_number__icontains=p["q"]))
        if p.get("from"):
            qs = qs.filter(placed_at__date__gte=p["from"])
        if p.get("to"):
            qs = qs.filter(placed_at__date__lte=p["to"])
        page = self.paginate_queryset(qs.distinct())
        rows = []
        for o in page:
            row = order_summary(o)
            row["customer"] = o.customer.user.get_username()
            rows.append(row)
        return self.get_paginated_response(rows)


class AdminOrderDetailView(APIView):
    permission_classes = [IsManagement]

    @extend_schema(responses=dict)
    def get(self, request, pk):
        _require(request.user, user_has_order_permission, "orders.view_order")
        order = get_object_or_404(Order.objects.select_related("customer__user"), pk=pk)
        data = order_detail(order)
        data["customer"] = {"id": order.customer_id, "username": order.customer.user.get_username(), "email": order.customer.user.email,
                            "phone": order.delivery_phone_number}
        data["audit_history"] = [{"old": h.old_status, "new": h.new_status, "by": h.changed_by.get_username() if h.changed_by_id else None,
                                  "reason": h.reason, "at": h.created_at} for h in order.status_history.select_related("changed_by")]
        data["deliveries"] = [{"id": d.pk, "status": d.status, "attempt": d.attempt_number, "needs_attention": d.needs_attention}
                              for d in Delivery.objects.filter(store_order__order=order)]
        return Response(data)


class OrderStatusSerializer(serializers.Serializer):
    status = serializers.ChoiceField(choices=OrderStatus.choices)
    reason = serializers.CharField(required=False, allow_blank=True, max_length=500)
    correction_note = serializers.CharField(required=False, allow_blank=True, max_length=500)


class AdminOrderStatusView(APIView):
    permission_classes = [IsManagement]

    @extend_schema(request=OrderStatusSerializer, responses=dict)
    def post(self, request, pk):
        _require(request.user, user_has_order_permission, "orders.change_order")
        order = get_object_or_404(Order, pk=pk)
        data = OrderStatusSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        v = data.validated_data
        if v["status"] == OrderStatus.CANCELLED:
            raise serializers.ValidationError({"status": "Use the cancel endpoint to cancel an order."})
        update_order_status(order=order, new_status=v["status"], actor=request.user, reason=v.get("reason", ""),
                            correction_note=v.get("correction_note", ""), request=request._request)
        return Response(order_summary(Order.objects.get(pk=pk)))


class AdminOrderCancelView(APIView):
    permission_classes = [IsManagement]

    @extend_schema(request=ReasonSerializer, responses=dict)
    def post(self, request, pk):
        _require(request.user, user_has_order_permission, "orders.cancel_order")
        order = get_object_or_404(Order, pk=pk)
        data = ReasonSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        admin_cancel_order(order=order, actor=request.user, reason=data.validated_data["reason"], request=request._request)
        return Response(order_summary(Order.objects.get(pk=pk)))


# ------------------------------------------------------------------ reports and audit

class AdminOverviewView(APIView):
    permission_classes = [IsManagement]

    @extend_schema(responses=dict)
    def get(self, request):
        since = timezone.now() - timezone.timedelta(days=30)
        orders = Order.objects.filter(placed_at__gte=since)
        completed = orders.filter(status=OrderStatus.COMPLETED)
        platform = RatingAggregate.objects.filter(target_type=TargetType.STORE).aggregate(count=Sum("count"), total=Sum("total"))
        return Response({
            "window_days": 30,
            "orders": {"by_status": dict(orders.values_list("status").annotate(n=Count("pk"))), "total": orders.count(),
                       "delivered_value": str(completed.aggregate(v=Sum("grand_total"))["v"] or 0)},
            "deliveries": {"by_status": dict(Delivery.objects.filter(created_at__gte=since).values_list("status").annotate(n=Count("pk"))),
                           "needs_attention": Delivery.objects.filter(needs_attention=True).count(),
                           "partners_online": DeliveryPartner.objects.filter(is_online=True, status="APPROVED").count(),
                           "partners_pending": DeliveryPartner.objects.filter(status="PENDING").count()},
            "support": {"open_tickets": Ticket.objects.exclude(status__in=["RESOLVED", "CLOSED"]).count(),
                        "open_complaints": Complaint.objects.exclude(status__in=["RESOLVED", "REJECTED", "CLOSED"]).count()},
            "stores": {"active": Store.objects.filter(status=StoreStatus.ACTIVE).count(), "pending": Store.objects.filter(status=StoreStatus.PENDING).count(),
                       "average_rating": round(platform["total"] / platform["count"], 2) if platform["count"] else 0.0},
        })


class AuditEventSerializer(serializers.ModelSerializer):
    actor = serializers.CharField(source="actor.username", default=None)

    class Meta:
        model = AuditEvent
        fields = ["id", "actor", "action", "object_type", "object_id", "summary", "metadata", "created_at"]


class AuditEventsView(generics.ListAPIView):
    permission_classes = [IsManagement]
    serializer_class = AuditEventSerializer
    pagination_class = StandardPagination

    def get_queryset(self):
        qs = AuditEvent.objects.select_related("actor")
        p = self.request.query_params
        for key in ("action", "object_type", "object_id"):
            if p.get(key):
                qs = qs.filter(**{key: p[key]})
        if p.get("actor"):
            qs = qs.filter(actor__username=p["actor"])
        return qs
