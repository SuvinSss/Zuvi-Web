"""Admin dashboard analytics, customers, export, search and categories."""
from datetime import timedelta

from django.utils import timezone

from accounts.models import Role, User
from deliveries.tests import DROP_LAT, DROP_LON, DeliveryBase, jpeg
from deliveries import services as ds
from orders.models import Order, OrderStatus


class AnalyticsBase(DeliveryBase):
    def setUp(self):
        super().setUp()
        self.boss = User.objects.create_superuser(username="an-boss", email="an-boss@example.com", password="x")
        self.boss.role = Role.SUPER_ADMIN
        self.boss.save()

    def get(self, path, user=None, **params):
        return self.as_user(user or self.boss).get(f"/api/v1/{path}", params)

    def deliver(self):
        partner = self.make_partner("an-rider")
        delivery = self.accepted_delivery(partner)
        self.pickup(delivery, partner)
        ds.complete_delivery(delivery.pk, partner, photos=[jpeg()], latitude=DROP_LAT, longitude=DROP_LON)
        self.order.refresh_from_db()
        return delivery


class DashboardTests(AnalyticsBase):
    def test_requires_management_access(self):
        self.assertEqual(self.get("admin/dashboard/", self.customer_user).status_code, 403)
        self.assertEqual(self.get("admin/dashboard/", self.store_user).status_code, 403)
        self.api.force_authenticate(None)
        self.assertIn(self.api.get("/api/v1/admin/dashboard/").status_code, (401, 403))

    def test_admin_without_order_permission_is_refused(self):
        self.assertEqual(self.get("admin/dashboard/", self.admin).status_code, 403)
        self.assertEqual(self.get("admin/customers/", self.admin).status_code, 403)
        self.assertEqual(self.as_user(self.admin).get("/api/v1/admin/orders/export/").status_code, 403)
        self.assertEqual(self.get("admin/search/", self.admin, q="abc").json()["results"], [])

    def test_numbers_match_the_database(self):
        self.deliver()
        r = self.get("admin/dashboard/").json()
        self.assertEqual(r["kpis"]["orders"]["value"], Order.objects.count())
        self.assertEqual(r["kpis"]["delivered"]["value"], Order.objects.filter(status=OrderStatus.COMPLETED).count())
        self.assertEqual(r["kpis"]["revenue"]["value"], str(self.order.grand_total))
        self.assertEqual(r["live"]["customers_total"], 1)
        self.assertEqual(r["range"]["days"], 30)
        self.assertEqual(len(r["series"]), 30)
        self.assertEqual(sum(d["orders"] for d in r["series"]), Order.objects.count())
        self.assertEqual(sum(float(d["revenue"]) for d in r["series"]), float(self.order.grand_total))
        self.assertEqual(r["status_distribution"][0]["status"], "COMPLETED")
        self.assertEqual(r["top_stores"][0]["name"], self.store.name)
        self.assertTrue(r["best_products"])
        self.assertEqual(r["delivery_performance"]["delivered"], 1)
        self.assertEqual(r["delivery_performance"]["success_rate_percent"], 100.0)

    def test_range_filter_changes_the_charts_and_previous_period_is_reported(self):
        self.deliver()
        old = timezone.localdate() - timedelta(days=200)
        r = self.get("admin/dashboard/", **{"from": old.isoformat(), "to": (old + timedelta(days=6)).isoformat()}).json()
        self.assertEqual(r["kpis"]["orders"]["value"], 0)
        self.assertEqual(sum(d["orders"] for d in r["series"]), 0)
        self.assertEqual(len(r["series"]), 7)
        self.assertEqual(r["live"]["customers_total"], 1)  # live snapshot ignores the period
        self.assertIsNone(r["kpis"]["orders"]["change_percent"])  # nothing to compare against: unavailable, not 0
        today = self.get("admin/dashboard/", **{"from": timezone.localdate().isoformat(), "to": timezone.localdate().isoformat()}).json()
        self.assertEqual(today["kpis"]["orders"]["value"], 1)
        self.assertEqual(today["range"]["previous"]["to"], (timezone.localdate() - timedelta(days=1)).isoformat())

    def test_bad_ranges_are_rejected(self):
        self.assertEqual(self.get("admin/dashboard/", **{"from": "nope"}).status_code, 400)
        self.assertEqual(self.get("admin/dashboard/", **{"from": "2026-02-01", "to": "2026-01-01"}).status_code, 400)
        self.assertEqual(self.get("admin/dashboard/", **{"from": "2020-01-01", "to": "2026-01-01"}).status_code, 400)

    def test_query_count_does_not_grow_with_data(self):
        from django.db import connection
        from django.test.utils import CaptureQueriesContext

        with CaptureQueriesContext(connection) as ctx:
            self.get("admin/dashboard/")
        self.assertLess(len(ctx), 60)

    def test_counts_endpoint(self):
        r = self.get("admin/counts/").json()
        self.assertIn("orders_awaiting_confirmation", r)
        self.assertEqual(self.get("admin/counts/", self.customer_user).status_code, 403)


class CustomerTests(AnalyticsBase):
    def test_list_search_and_detail(self):
        self.deliver()
        rows = self.get("admin/customers/").json()
        self.assertEqual(rows["count"], 1)
        row = rows["results"][0]
        self.assertEqual(row["order_count"], 1)
        self.assertEqual(row["delivered_value"], str(self.order.grand_total))
        self.assertNotIn("password", str(row).lower())
        self.assertEqual(self.get("admin/customers/", q="no-such-customer").json()["count"], 0)
        self.assertEqual(self.get("admin/customers/", q=self.customer_user.username[:5]).json()["count"], 1)
        detail = self.get(f"admin/customers/{row['id']}/").json()
        self.assertEqual(detail["recent_orders"][0]["order_number"], self.order.order_number)
        self.assertEqual(detail["orders_by_status"], {"COMPLETED": 1})

    def test_customers_endpoints_are_protected(self):
        self.assertEqual(self.get("admin/customers/", self.customer_user).status_code, 403)
        self.assertEqual(self.get("admin/customers/1/", self.store_user).status_code, 403)


class ExportSearchCategoryTests(AnalyticsBase):
    def test_csv_export_matches_filters_and_neutralises_formulas(self):
        r = self.as_user(self.boss).get("/api/v1/admin/orders/export/", {"status": "PLACED"})
        self.assertEqual(r.status_code, 200)
        body = b"".join(r.streaming_content).decode()
        self.assertTrue(body.startswith("Order number,"))
        self.assertIn(self.order.order_number, body)
        r = self.as_user(self.boss).get("/api/v1/admin/orders/export/", {"status": "CANCELLED"})
        self.assertEqual(len(b"".join(r.streaming_content).decode().strip().splitlines()), 1)
        from platform_api.analytics import _safe

        self.assertEqual(_safe("=HYPERLINK(1)"), "'=HYPERLINK(1)")
        self.assertEqual(self.as_user(self.customer_user).get("/api/v1/admin/orders/export/").status_code, 403)

    def test_global_search(self):
        r = self.get("admin/search/", q=self.order.order_number).json()
        self.assertEqual(r["results"][0]["type"], "Order")
        self.assertEqual(r["results"][0]["path"], f"/admin/orders/{self.order.pk}")
        self.assertEqual(self.get("admin/search/", q="a").json()["results"], [])
        self.assertEqual(self.get("admin/search/", self.customer_user, q="abc").status_code, 403)

    def test_categories_listing(self):
        r = self.get("admin/categories/").json()["results"]
        self.assertTrue(r)
        self.assertIn("product_count", r[0])
        self.assertEqual(self.get("admin/categories/", self.customer_user).status_code, 403)
