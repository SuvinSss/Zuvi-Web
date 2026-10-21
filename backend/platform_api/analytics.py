"""Back-office analytics for the admin dashboard. Every figure is aggregated in the database over real rows;
nothing is estimated. Money figures count only orders that were actually delivered (COMPLETED)."""
import csv
from decimal import Decimal
from datetime import date, datetime, timedelta

from django.db.models import Avg, Count, DurationField, ExpressionWrapper, F, Max, Q, Sum
from django.db.models.functions import TruncDate
from django.http import StreamingHttpResponse
from django.utils import timezone
from drf_spectacular.utils import extend_schema
from rest_framework import generics, serializers
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts.models import Role
from catalog.models import Product, ProductCategory
from core.pagination import StandardPagination
from core.permissions import IsManagement
from customers.models import Customer
from deliveries.models import Delivery, DeliveryPartner
from feedback.models import Feedback
from orders.decorators import user_has_order_permission
from orders.models import Order, OrderItem, OrderStatus, StoreOrder
from reviews.models import Review
from stores.models import Store
from support.models import Complaint, Ticket

from .customer import order_summary

MAX_DAYS = 366
OPEN_TICKET = ~Q(status__in=["RESOLVED", "CLOSED"])
OPEN_COMPLAINT = ~Q(status__in=["RESOLVED", "REJECTED", "CLOSED"])
ACTIVE_DELIVERY = ["OFFERED", "ACCEPTED", "AT_STORE", "IN_TRANSIT", "ARRIVED"]


def _day(value, field):
    try:
        return date.fromisoformat(value)
    except (TypeError, ValueError):
        raise ValidationError({field: "Use a date like 2026-10-31."})


def period(params):
    """Inclusive local-date range (default: last 30 days) and the equally long period just before it."""
    today = timezone.localdate()
    end = _day(params["to"], "to") if params.get("to") else today
    start = _day(params["from"], "from") if params.get("from") else end - timedelta(days=29)
    if start > end:
        raise ValidationError({"from": "The start date must not be after the end date."})
    if (end - start).days + 1 > MAX_DAYS:
        raise ValidationError({"from": f"Choose a range of at most {MAX_DAYS} days."})
    days = (end - start).days + 1
    return start, end, start - timedelta(days=days), start - timedelta(days=1)


def _bounds(start, end):
    tz = timezone.get_current_timezone()
    return (timezone.make_aware(datetime.combine(start, datetime.min.time()), tz),
            timezone.make_aware(datetime.combine(end + timedelta(days=1), datetime.min.time()), tz))


def _money(value):
    return str(Decimal(value or 0).quantize(Decimal("0.01")))


def _change(now, before):
    """Percent change, or None when the earlier period has no data to compare against."""
    return None if not before else round((now - before) * 100 / before, 1)


def _orders_in(start, end, field="placed_at"):
    lo, hi = _bounds(start, end)
    return Order.objects.filter(**{f"{field}__gte": lo, f"{field}__lt": hi})


class DashboardView(APIView):
    permission_classes = [IsManagement]

    @extend_schema(responses=dict)
    def get(self, request):
        if not user_has_order_permission(request.user, "orders.view_order"):
            return Response({"detail": "You do not have permission to view the dashboard."}, status=403)
        start, end, prev_start, prev_end = period(request.query_params)
        lo, hi = _bounds(start, end)
        days = (end - start).days + 1

        def window(s, e):
            placed = _orders_in(s, e)
            delivered = _orders_in(s, e, "delivered_at").filter(status=OrderStatus.COMPLETED)
            cancelled = _orders_in(s, e, "cancelled_at").filter(status__in=[OrderStatus.CANCELLED, OrderStatus.PARTIALLY_CANCELLED])
            clo, chi = _bounds(s, e)
            return {
                "orders": placed.count(),
                "delivered": delivered.count(),
                "revenue": delivered.aggregate(v=Sum("grand_total"))["v"] or 0,
                "cancelled": cancelled.count(),
                "new_customers": Customer.objects.filter(created_at__gte=clo, created_at__lt=chi).count(),
            }

        cur, prev = window(start, end), window(prev_start, prev_end)
        kpis = {k: {"value": _money(cur[k]) if k == "revenue" else cur[k],
                    "previous": _money(prev[k]) if k == "revenue" else prev[k],
                    "change_percent": _change(float(cur[k]), float(prev[k]))} for k in cur}

        # Live snapshot (not tied to the selected period): what needs doing right now.
        now = Order.objects.aggregate(
            awaiting_confirmation=Count("pk", filter=Q(status=OrderStatus.PLACED)),
            confirmed=Count("pk", filter=Q(status=OrderStatus.CONFIRMED)),
            in_progress=Count("pk", filter=Q(status=OrderStatus.IN_PROGRESS)),
        )
        so = StoreOrder.objects.aggregate(
            preparing=Count("pk", filter=Q(status__in=["ACCEPTED", "PREPARING"])),
            ready=Count("pk", filter=Q(status__in=["READY", "READY_FOR_PICKUP"])),
        )
        dl = Delivery.objects.aggregate(
            waiting=Count("pk", filter=Q(status="PENDING_ASSIGNMENT")),
            active=Count("pk", filter=Q(status__in=ACTIVE_DELIVERY)),
            in_transit=Count("pk", filter=Q(status="IN_TRANSIT")),
            attention=Count("pk", filter=Q(needs_attention=True)),
        )
        live = {
            "orders_awaiting_confirmation": now["awaiting_confirmation"],
            "orders_being_prepared": so["preparing"],
            "orders_awaiting_delivery": so["ready"] + dl["waiting"],
            "orders_in_transit": dl["in_transit"],
            "deliveries_active": dl["active"],
            "deliveries_waiting_for_partner": dl["waiting"],
            "deliveries_needing_attention": dl["attention"],
            "customers_total": Customer.objects.count(),
            "stores_active": Store.objects.filter(status="ACTIVE").count(),
            "partners_active": DeliveryPartner.objects.filter(status="APPROVED").count(),
            "partners_online": DeliveryPartner.objects.filter(status="APPROVED", is_online=True).count(),
            "products_total": Product.objects.count(),
            "products_active": Product.objects.filter(is_active=True, status="APPROVED").count(),
            "tickets_open": Ticket.objects.filter(OPEN_TICKET).count(),
            "complaints_open": Complaint.objects.filter(OPEN_COMPLAINT).count(),
        }

        # Daily series, zero-filled so charts have no gaps.
        def per_day(qs, field, **agg):
            return {r["d"]: r for r in qs.annotate(d=TruncDate(field)).values("d").annotate(**agg)}

        placed = per_day(_orders_in(start, end), "placed_at", n=Count("pk"))
        delivered = per_day(_orders_in(start, end, "delivered_at").filter(status=OrderStatus.COMPLETED), "delivered_at",
                            n=Count("pk"), revenue=Sum("grand_total"))
        cancelled = per_day(_orders_in(start, end, "cancelled_at").filter(status__in=[OrderStatus.CANCELLED, OrderStatus.PARTIALLY_CANCELLED]),
                            "cancelled_at", n=Count("pk"))
        joined = per_day(Customer.objects.filter(created_at__gte=lo, created_at__lt=hi), "created_at", n=Count("pk"))
        failed = per_day(Delivery.objects.filter(status="FAILED", updated_at__gte=lo, updated_at__lt=hi), "updated_at", n=Count("pk"))
        series = []
        for i in range(days):
            d = start + timedelta(days=i)
            series.append({
                "date": d.isoformat(),
                "orders": placed.get(d, {}).get("n", 0),
                "delivered": delivered.get(d, {}).get("n", 0),
                "revenue": _money(delivered.get(d, {}).get("revenue")),
                "cancelled": cancelled.get(d, {}).get("n", 0),
                "new_customers": joined.get(d, {}).get("n", 0),
                "failed_deliveries": failed.get(d, {}).get("n", 0),
            })

        in_range = _orders_in(start, end)
        status_distribution = [{"status": r["status"], "count": r["n"]} for r in in_range.values("status").annotate(n=Count("pk")).order_by("-n")]

        done_store_orders = StoreOrder.objects.filter(order__delivered_at__gte=lo, order__delivered_at__lt=hi, order__status=OrderStatus.COMPLETED,
                                                      status="COMPLETED")
        top_stores = [{"store_id": r["store_id"], "name": r["store_name"], "orders": r["n"], "revenue": _money(r["revenue"])}
                      for r in done_store_orders.values("store_id", "store_name").annotate(n=Count("pk"), revenue=Sum("store_total")).order_by("-revenue")[:5]]
        best_products = [{"product_id": r["product_id"], "name": r["product_name"], "quantity": str(r["qty"]), "revenue": _money(r["revenue"])}
                         for r in OrderItem.objects.filter(store_order__order__placed_at__gte=lo, store_order__order__placed_at__lt=hi,
                                                           is_cancelled=False, is_rejected=False)
                         .exclude(store_order__status__in=["CANCELLED", "REJECTED"])
                         .values("product_id", "product_name").annotate(qty=Sum("quantity"), revenue=Sum("line_total")).order_by("-qty")[:5]]

        dwin = Delivery.objects.filter(created_at__gte=lo, created_at__lt=hi)
        perf = dwin.aggregate(
            total=Count("pk"), delivered=Count("pk", filter=Q(status="DELIVERED")), failed=Count("pk", filter=Q(status="FAILED")),
            cancelled=Count("pk", filter=Q(status="CANCELLED")), retried=Count("pk", filter=Q(attempt_number__gt=1)),
            avg=Avg(ExpressionWrapper(F("delivered_at") - F("assigned_at"), output_field=DurationField()), filter=Q(status="DELIVERED", assigned_at__isnull=False)),
        )
        avg_minutes = round(perf["avg"].total_seconds() / 60, 1) if perf["avg"] else None
        delivery_performance = {
            "total": perf["total"], "delivered": perf["delivered"], "failed": perf["failed"], "cancelled": perf["cancelled"], "retried": perf["retried"],
            "success_rate_percent": round(perf["delivered"] * 100 / (perf["delivered"] + perf["failed"]), 1) if perf["delivered"] + perf["failed"] else None,
            "average_minutes_assignment_to_delivery": avg_minutes,
        }

        cutoff = timezone.now() - timedelta(minutes=15)
        queues = {
            "recent_orders": [{**order_summary(o), "customer": o.customer.user.get_username()}
                              for o in Order.objects.select_related("customer__user").order_by("-placed_at")[:6]],
            "needs_attention": {
                "orders_unconfirmed_15_min": list(Order.objects.filter(status=OrderStatus.PLACED, placed_at__lt=cutoff).order_by("placed_at")
                                                  .values("id", "order_number", "placed_at")[:5]),
                "deliveries": list(Delivery.objects.filter(needs_attention=True).values("id", "status", "store_order__store_order_number")[:5]),
            },
            "new_customers": list(Customer.objects.select_related("user").order_by("-created_at")
                                  .values("id", "customer_code", "created_at", username=F("user__username"))[:5]),
            "pending_stores": list(Store.objects.filter(status="PENDING").order_by("-created_at").values("id", "name", "created_at")[:5]),
            "pending_partners": list(DeliveryPartner.objects.filter(status="PENDING").order_by("-created_at")
                                     .values("id", "created_at", username=F("user__username"))[:5]),
            "pending_complaints": list(Complaint.objects.filter(OPEN_COMPLAINT).order_by("-created_at")
                                       .values("id", "reference", "category", "severity", "created_at")[:5]),
            "recent_reviews": list(Review.objects.order_by("-created_at").values("id", "rating", "target_type", "comment", "status", "created_at")[:5]),
            "recent_feedback": list(Feedback.objects.order_by("-created_at").values("id", "reference", "kind", "message", "status", "created_at")[:5]),
        }
        return Response({
            "range": {"from": start, "to": end, "days": days, "previous": {"from": prev_start, "to": prev_end}},
            "kpis": kpis, "live": live, "series": series, "status_distribution": status_distribution, "top_stores": top_stores,
            "best_products": best_products, "delivery_performance": delivery_performance, "queues": queues,
            "notes": {"revenue": "Value of orders delivered in the period. Online payment and refund records do not exist yet, so none are included."},
        })


class CountsView(APIView):
    """Small, cheap payload for the sidebar badges."""

    permission_classes = [IsManagement]

    @extend_schema(responses=dict)
    def get(self, request):
        return Response({
            "orders_awaiting_confirmation": Order.objects.filter(status=OrderStatus.PLACED).count(),
            "deliveries_needing_attention": Delivery.objects.filter(needs_attention=True).count(),
            "partners_pending": DeliveryPartner.objects.filter(status="PENDING").count(),
            "stores_pending": Store.objects.filter(status="PENDING").count(),
            "products_pending": Product.objects.filter(status="PENDING").count(),
            "tickets_open": Ticket.objects.filter(OPEN_TICKET).count(),
            "complaints_open": Complaint.objects.filter(OPEN_COMPLAINT).count(),
            "stores_needs_info": Store.objects.filter(status="NEEDS_INFO").count(),
        })


# ---------------------------------------------------------------- customers

class CustomerRowSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    customer_code = serializers.CharField()
    username = serializers.CharField(source="user.username")
    name = serializers.SerializerMethodField()
    email = serializers.CharField(source="user.email")
    phone_number = serializers.CharField(source="user.phone_number")
    is_active = serializers.BooleanField(source="user.is_active")
    user_id = serializers.IntegerField()
    created_at = serializers.DateTimeField()
    order_count = serializers.IntegerField()
    delivered_value = serializers.SerializerMethodField()
    last_order_at = serializers.DateTimeField(allow_null=True)

    def get_name(self, c):
        return c.user.get_full_name() or c.user.get_username()

    def get_delivered_value(self, c):
        return _money(c.delivered_value)


def _customer_qs():
    return (Customer.objects.select_related("user")
            .annotate(order_count=Count("orders", distinct=True),
                      delivered_value=Sum("orders__grand_total", filter=Q(orders__status=OrderStatus.COMPLETED)),
                      last_order_at=Max("orders__placed_at")))


class AdminCustomersView(generics.ListAPIView):
    permission_classes = [IsManagement]
    serializer_class = CustomerRowSerializer
    pagination_class = StandardPagination
    ORDERING = {"created": "-created_at", "orders": "-order_count", "value": "-delivered_value", "name": "user__username"}

    def get_queryset(self):
        p = self.request.query_params
        qs = _customer_qs()
        if p.get("q"):
            q = p["q"]
            qs = qs.filter(Q(user__username__icontains=q) | Q(user__email__icontains=q) | Q(user__phone_number__icontains=q)
                           | Q(customer_code__icontains=q) | Q(user__first_name__icontains=q) | Q(user__last_name__icontains=q))
        if p.get("active") in {"1", "true", "0", "false"}:
            qs = qs.filter(user__is_active=p["active"] in {"1", "true"})
        if p.get("from"):
            qs = qs.filter(created_at__date__gte=_day(p["from"], "from"))
        if p.get("to"):
            qs = qs.filter(created_at__date__lte=_day(p["to"], "to"))
        return qs.order_by(self.ORDERING.get(p.get("ordering"), "-created_at"), "-pk")

    def list(self, request, *args, **kwargs):
        if not user_has_order_permission(request.user, "orders.view_order"):
            return Response({"detail": "You do not have permission to view customers."}, status=403)
        return super().list(request, *args, **kwargs)


class AdminCustomerDetailView(APIView):
    permission_classes = [IsManagement]

    @extend_schema(responses=dict)
    def get(self, request, pk):
        if not user_has_order_permission(request.user, "orders.view_order"):
            return Response({"detail": "You do not have permission to view customers."}, status=403)
        from django.shortcuts import get_object_or_404

        customer = get_object_or_404(_customer_qs(), pk=pk)
        user = customer.user
        orders = list(Order.objects.filter(customer=customer).order_by("-placed_at")[:10])
        by_status = {r["status"]: r["n"] for r in Order.objects.filter(customer=customer).values("status").annotate(n=Count("pk"))}
        return Response({
            **CustomerRowSerializer(customer).data,
            "orders_by_status": by_status,
            "recent_orders": [order_summary(o) for o in orders],
            "tickets": Ticket.objects.filter(requester=user).count(),
            "complaints": Complaint.objects.filter(complainant=user).count(),
            "reviews": Review.objects.filter(customer=customer).count(),
            "registration_source": customer.registration_source,
        })


# ------------------------------------------------------------------- export

class Echo:
    def write(self, value):
        return value


def _safe(value):
    """Neutralise spreadsheet formulas in text that customers control."""
    text = "" if value is None else str(value)
    return "'" + text if text[:1] in ("=", "+", "-", "@") else text


class OrdersExportView(APIView):
    """CSV of the orders matching the same filters as the orders list (streamed, capped)."""

    permission_classes = [IsManagement]
    LIMIT = 20000

    @extend_schema(responses=None)
    def get(self, request):
        if not user_has_order_permission(request.user, "orders.view_order"):
            return Response({"detail": "You do not have permission to export orders."}, status=403)
        p = request.query_params
        qs = Order.objects.select_related("customer__user").order_by("-placed_at")
        for key, lookup in (("status", "status"), ("fulfillment_type", "fulfillment_type"), ("payment_status", "payment_status"), ("store", "store_orders__store_id")):
            if p.get(key):
                qs = qs.filter(**{lookup: p[key]})
        if p.get("q"):
            qs = qs.filter(Q(order_number__icontains=p["q"]) | Q(customer__user__username__icontains=p["q"]) | Q(delivery_phone_number__icontains=p["q"]))
        if p.get("from"):
            qs = qs.filter(placed_at__date__gte=_day(p["from"], "from"))
        if p.get("to"):
            qs = qs.filter(placed_at__date__lte=_day(p["to"], "to"))
        qs = qs.distinct()[: self.LIMIT]
        writer = csv.writer(Echo())

        def rows():
            yield writer.writerow(["Order number", "Placed at", "Status", "Payment method", "Payment status", "Fulfilment", "Customer", "Total"])
            for o in qs.iterator(chunk_size=500):
                yield writer.writerow([_safe(o.order_number), timezone.localtime(o.placed_at).strftime("%Y-%m-%d %H:%M"), o.status, o.payment_method,
                                       o.payment_status, o.fulfillment_type, _safe(o.customer.user.get_username()), o.grand_total])

        response = StreamingHttpResponse(rows(), content_type="text/csv; charset=utf-8")
        response["Content-Disposition"] = 'attachment; filename="zuuvi-orders.csv"'
        return response


# ------------------------------------------------------------------- search

class AdminSearchView(APIView):
    permission_classes = [IsManagement]

    @extend_schema(responses=dict)
    def get(self, request):
        q = (request.query_params.get("q") or "").strip()
        if len(q) < 2:
            return Response({"query": q, "results": []})
        can_orders = user_has_order_permission(request.user, "orders.view_order")
        results = []
        if can_orders:
            for o in Order.objects.filter(Q(order_number__icontains=q) | Q(delivery_phone_number__icontains=q)).order_by("-placed_at")[:5]:
                results.append({"type": "Order", "label": o.order_number, "detail": o.status, "path": f"/admin/orders/{o.pk}"})
            for c in Customer.objects.select_related("user").filter(Q(user__username__icontains=q) | Q(user__email__icontains=q) | Q(user__phone_number__icontains=q)
                                                                     | Q(customer_code__icontains=q))[:5]:
                results.append({"type": "Customer", "label": c.user.get_username(), "detail": c.customer_code, "path": f"/admin/customers/{c.pk}"})
        for s in Store.objects.filter(Q(name__icontains=q) | Q(store_code__icontains=q))[:5]:
            results.append({"type": "Store", "label": s.name, "detail": s.status, "path": "/admin/stores"})
        for pr in Product.objects.filter(Q(name__icontains=q) | Q(product_code__icontains=q))[:5]:
            results.append({"type": "Product", "label": pr.name, "detail": pr.product_code, "path": f"/admin/products/{pr.pk}"})
        for t in Ticket.objects.filter(Q(reference__icontains=q) | Q(subject__icontains=q))[:5]:
            results.append({"type": "Ticket", "label": t.reference, "detail": t.subject, "path": f"/admin/support/tickets/{t.pk}"})
        for c in Complaint.objects.filter(reference__icontains=q)[:5]:
            results.append({"type": "Complaint", "label": c.reference, "detail": c.status, "path": f"/admin/support/complaints/{c.pk}"})
        return Response({"query": q, "results": results})


# --------------------------------------------------------------- categories

class AdminCategoriesView(APIView):
    permission_classes = [IsManagement]

    @extend_schema(responses=dict)
    def get(self, request):
        rows = (ProductCategory.objects.select_related("parent").annotate(product_count=Count("products"))
                .order_by("parent__name", "name").values("id", "name", "slug", "is_active", "product_count", parent_name=F("parent__name")))
        return Response({"results": list(rows)})
