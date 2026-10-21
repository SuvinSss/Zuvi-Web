"""Zuuvi admin site: business-module navigation and a dashboard built from real database counts."""
from django.contrib import admin
from django.db.models import Count, Q
from django.urls import reverse

SECTIONS = (
    ("Operations", "orders", [("orders", "Order"), ("orders", "StoreOrder"), ("deliveries", "Delivery"), ("deliveries", "DeliveryPartner"),
                              ("deliveries", "DeliveryAssignment"), ("deliveries", "DeliveryAttempt"), ("deliveries", "DeliveryEvidence"),
                              ("deliveries", "LocationPing"), ("orders", "OrderItem"), ("orders", "OrderStatusHistory"),
                              ("orders", "StoreOrderStatusHistory"), ("orders", "OrderPaymentHistory"), ("orders", "PickupLocation")]),
    ("Customer care", "care", [("support", "Ticket"), ("support", "Complaint"), ("support", "TicketMessage"), ("feedback", "Feedback"),
                               ("reviews", "Review"), ("reviews", "ReviewReport"), ("reviews", "RatingAggregate")]),
    ("Stores and catalog", "catalog", [("stores", "Store"), ("stores", "StoreUser"), ("stores", "StoreCategory"), ("stores", "StoreStatusHistory"),
                                       ("catalog", "Product"), ("catalog", "ProductCategory"), ("catalog", "Brand"), ("catalog", "Tag"),
                                       ("catalog", "ProductImage"), ("catalog", "ProductStatusHistory"), ("catalog", "ProductPriceHistory"),
                                       ("inventory", "InventoryTransaction"), ("inventory", "PurchaseEntry")]),
    ("People and access", "people", [("accounts", "User"), ("customers", "Customer"), ("customers", "CustomerAddress"), ("locations", "Address"),
                                     ("accounts", "AdminProfile"), ("auth", "Group"), ("cart", "Cart"), ("cart", "CartItem")]),
    ("Records and notices", "records", [("core", "AuditEvent"), ("accounts", "AdminAuditLog"), ("notifications", "Notification"),
                                        ("notifications", "NotificationPreference")]),
)


class ZuuviAdminSite(admin.AdminSite):
    site_header = "Zuuvi administration"
    site_title = "Zuuvi admin"
    index_title = "Dashboard"
    final_catch_all_view = True

    def get_app_list(self, request, app_label=None):
        native = super().get_app_list(request, app_label)
        if app_label:  # /admin/<app>/ keeps Django's own per-app page
            return native
        by_key = {(m["object_name"], a["app_label"]): m for a in native for m in a["models"]}
        placed, grouped = set(), []
        for name, slug, members in SECTIONS:
            models = []
            for app, obj in members:
                model = by_key.get((obj, app))
                if model:
                    models.append(model)
                    placed.add((obj, app))
            if models:
                grouped.append({"name": name, "app_label": slug, "app_url": "", "has_module_perms": True, "models": models})
        rest = [m for key, m in by_key.items() if key not in placed]
        if rest:
            grouped.append({"name": "Other", "app_label": "other", "app_url": "", "has_module_perms": True, "models": rest})
        return grouped

    def index(self, request, extra_context=None):
        extra_context = {**(extra_context or {}), "dashboard": self.dashboard(request)}
        return super().index(request, extra_context)

    def _link(self, request, app, model, **query):
        registered = next((m for m in self._registry if m._meta.app_label == app and m._meta.model_name == model), None)
        if not registered:
            return None
        admin_obj = self._registry[registered]
        if not admin_obj.has_view_permission(request):
            return None
        url = reverse(f"admin:{app}_{model}_changelist")
        return url + ("?" + "&".join(f"{k}={v}" for k, v in query.items()) if query else "")

    def dashboard(self, request):
        """Counts only: a handful of indexed aggregate queries, never row lists."""
        from customers.models import Customer
        from catalog.models import Product
        from deliveries.models import Delivery, DeliveryPartner
        from orders.models import Order, OrderStatus
        from stores.models import Store
        from support.models import Complaint, Ticket

        def cards(title, items):
            return {"title": title, "items": [i for i in items if i["value"] is not None]}

        def item(label, value, url, hint="", attention=False):
            return {"label": label, "value": value, "url": url, "hint": hint, "attention": attention and bool(value)}

        link = lambda *a, **q: self._link(request, *a, **q)  # noqa: E731
        orders = Order.objects.aggregate(
            total=Count("pk"),
            awaiting=Count("pk", filter=Q(status=OrderStatus.PLACED)),
            processing=Count("pk", filter=Q(status__in=[OrderStatus.CONFIRMED, OrderStatus.IN_PROGRESS])),
        )
        deliveries = Delivery.objects.aggregate(
            active=Count("pk", filter=Q(status__in=["OFFERED", "ACCEPTED", "AT_STORE", "IN_TRANSIT", "ARRIVED"])),
            waiting=Count("pk", filter=Q(status="PENDING_ASSIGNMENT")),
            done=Count("pk", filter=Q(status="DELIVERED")),
            attention=Count("pk", filter=Q(needs_attention=True)),
        )
        partners = DeliveryPartner.objects.aggregate(pending=Count("pk", filter=Q(status="PENDING")), online=Count("pk", filter=Q(status="APPROVED", is_online=True)),
                                                     approved=Count("pk", filter=Q(status="APPROVED")))
        stores = Store.objects.aggregate(active=Count("pk", filter=Q(status="ACTIVE")), pending=Count("pk", filter=Q(status="PENDING")))
        open_tickets = Ticket.objects.exclude(status__in=["RESOLVED", "CLOSED"]).count()
        open_complaints = Complaint.objects.exclude(status__in=["RESOLVED", "REJECTED", "CLOSED"]).count()
        pending_products = Product.objects.filter(status="PENDING").count()
        return [
            cards("Needs attention", [
                item("Orders awaiting action", orders["awaiting"], link("orders", "order", status__exact="PLACED"), "Placed, not yet confirmed", True),
                item("Deliveries waiting for a partner", deliveries["waiting"], link("deliveries", "delivery", status__exact="PENDING_ASSIGNMENT"), "", True),
                item("Deliveries flagged for attention", deliveries["attention"], link("deliveries", "delivery", needs_attention__exact=1), "", True),
                item("Partners awaiting approval", partners["pending"], link("deliveries", "deliverypartner", status__exact="PENDING"), "", True),
                item("Stores awaiting approval", stores["pending"], link("stores", "store", status__exact="PENDING"), "", True),
                item("Products awaiting approval", pending_products, link("catalog", "product", status__exact="PENDING"), "", True),
                item("Open support tickets", open_tickets, link("support", "ticket"), "Not resolved or closed", True),
                item("Unresolved complaints", open_complaints, link("support", "complaint"), "", True),
            ]),
            cards("Platform", [
                item("Customers", Customer.objects.count(), link("customers", "customer")),
                item("Active stores", stores["active"], link("stores", "store", status__exact="ACTIVE")),
                item("Approved delivery partners", partners["approved"], link("deliveries", "deliverypartner", status__exact="APPROVED"), f"{partners['online']} online now"),
                item("Total orders", orders["total"], link("orders", "order")),
                item("Orders being processed", orders["processing"], link("orders", "order", status__exact="IN_PROGRESS")),
                item("Active deliveries", deliveries["active"], link("deliveries", "delivery")),
                item("Completed deliveries", deliveries["done"], link("deliveries", "delivery", status__exact="DELIVERED")),
            ]),
        ]
