"""Django admin: access control, rendering, bulk actions through the service layer, and data hygiene."""
from django.contrib import admin
from django.contrib.auth.models import Group, Permission
from django.test import Client
from django.urls import reverse

from accounts.models import Role, User
from core.models import AuditEvent
from deliveries.models import Delivery, DeliveryPartner, PartnerStatus
from deliveries.tests import DeliveryBase
from feedback.models import Feedback
from notifications.models import Notification
from reviews.models import Review, ReviewStatus
from support.models import Complaint, Ticket

PW = "Local-test-only-password-492!"
NEW_MODELS = (Delivery, DeliveryPartner, Review, Feedback, Ticket, Complaint, Notification, AuditEvent)


def url(model, kind, obj=None):
    o = model._meta
    return reverse(f"admin:{o.app_label}_{o.model_name}_{kind}", args=[obj.pk] if obj is not None else None)


class AdminBase(DeliveryBase):
    def setUp(self):
        super().setUp()
        self.boss = User.objects.create_superuser(username="adm-boss", email="boss@example.com", password=PW)
        self.boss.role = Role.SUPER_ADMIN
        self.boss.save()
        self.http = Client()
        self.http.force_login(self.boss)

    def post_action(self, model, action, objs, **extra):
        data = {"action": action, "_selected_action": [o.pk for o in objs], **extra}
        return self.http.post(url(model, "changelist"), data)


class AccessTests(AdminBase):
    def test_login_page_loads_and_anonymous_is_redirected(self):
        anon = Client()
        self.assertEqual(anon.get(reverse("admin:login")).status_code, 200)
        self.assertEqual(anon.get(reverse("admin:index")).status_code, 302)
        self.assertEqual(anon.get(url(Delivery, "changelist")).status_code, 302)

    def test_customer_and_non_management_staff_are_refused(self):
        for user in (self.customer_user, self.store_user):
            c = Client()
            c.force_login(user)
            self.assertEqual(c.get(url(Delivery, "changelist")).status_code, 302, user.role)
        support = User.objects.create_user(username="adm-support", email="s@example.com", password=PW,
                                           role=Role.SUPPORT_AGENT, is_staff=True)
        support.user_permissions.set(Permission.objects.all())
        c = Client()
        c.force_login(support)
        for model in NEW_MODELS:
            self.assertEqual(c.get(url(model, "changelist")).status_code, 403, model.__name__)

    def test_staff_admin_without_permission_sees_nothing_and_cannot_act(self):
        admin_user = User.objects.create_user(username="adm-plain", email="p@example.com", password=PW, role=Role.ADMIN, is_staff=True)
        c = Client()
        c.force_login(admin_user)
        self.assertEqual(c.get(url(Delivery, "changelist")).status_code, 403)
        admin_user.user_permissions.add(Permission.objects.get(codename="view_deliverypartner"))
        admin_user = User.objects.get(pk=admin_user.pk)
        c.force_login(admin_user)
        partner = self.make_partner("adm-view", status=PartnerStatus.PENDING, online=False)
        self.assertEqual(c.get(url(DeliveryPartner, "changelist")).status_code, 200)
        c.post(url(DeliveryPartner, "changelist"), {"action": "approve", "_selected_action": [partner.pk], "apply": "1"})
        partner.refresh_from_db()
        self.assertEqual(partner.status, PartnerStatus.PENDING)

    def test_all_new_models_registered_read_only(self):
        for model in NEW_MODELS:
            registered = admin.site._registry[model]
            request = self.http.get("/django-admin/").wsgi_request
            request.user = self.boss
            with self.subTest(model=model.__name__):
                self.assertTrue(registered.has_view_permission(request))
                self.assertFalse(registered.has_add_permission(request))
                self.assertFalse(registered.has_change_permission(request))
                self.assertFalse(registered.has_delete_permission(request))
                self.assertNotIn("delete_selected", registered.get_actions(request))

    def test_static_theme_loads(self):
        from django.contrib.staticfiles import finders

        self.assertTrue(finders.find("admin/zuuvi/admin.css"))
        self.assertContains(self.http.get(reverse("admin:index")), "admin/zuuvi/admin.css")


class DashboardTests(AdminBase):
    def test_counts_come_from_the_database(self):
        self.make_partner("dash-pending", status=PartnerStatus.PENDING, online=False)
        self.ready_order()
        dash = {i["label"]: i["value"] for g in self.http.get(reverse("admin:index")).context["dashboard"] for i in g["items"]}
        self.assertEqual(dash["Partners awaiting approval"], 1)
        self.assertEqual(dash["Deliveries waiting for a partner"], Delivery.objects.filter(status="PENDING_ASSIGNMENT").count())
        self.assertEqual(dash["Total orders"], self.order.__class__.objects.count())
        self.assertEqual(dash["Customers"], self.customer.__class__.objects.count())

    def test_navigation_is_grouped_by_business_module(self):
        names = [a["name"] for a in self.http.get(reverse("admin:index")).context["app_list"]]
        self.assertEqual(names[:3], ["Operations", "Customer care", "Stores and catalog"])
        self.assertContains(self.http.get(reverse("admin:index")), "Delivery partners")

    def test_dashboard_query_count_is_small_and_constant(self):
        from django.db import connection
        from django.test.utils import CaptureQueriesContext

        with CaptureQueriesContext(connection) as ctx:
            self.http.get(reverse("admin:index"))
        self.assertLess(len(ctx), 20)


class ListAndDetailTests(AdminBase):
    def test_every_new_list_and_detail_page_renders(self):
        partner = self.make_partner("adm-list")
        delivery = self.accepted_delivery(partner)
        self.api.force_authenticate(self.customer_user)
        self.api.post("/api/v1/support/tickets/", {"category": "ORDER", "subject": "Late", "description": "x"}, format="json")
        fb = self.api.post("/api/v1/feedback/", {"kind": "SUGGESTION", "subject_type": "PLATFORM", "message": "The app is lovely to use."}, format="json")
        self.assertEqual(fb.status_code, 201, fb.content)
        Notification.objects.create(recipient=self.customer_user, kind="IN_TRANSIT", title="On the way", body="secret body")
        AuditEvent.objects.create(actor=self.boss, action="x.y", object_type="T", object_id="1")
        for model in NEW_MODELS:
            with self.subTest(model=model.__name__):
                self.assertEqual(self.http.get(url(model, "changelist")).status_code, 200)
                obj = model.objects.first()
                if obj is not None:
                    self.assertEqual(self.http.get(url(model, "change", obj)).status_code, 200)
        self.assertEqual(self.http.get(url(Delivery, "change", delivery)).status_code, 200)

    def test_search_and_filters_work(self):
        partner = self.make_partner("adm-search", status=PartnerStatus.PENDING, online=False)
        self.make_partner("adm-other")
        r = self.http.get(url(DeliveryPartner, "changelist"), {"q": "adm-search"})
        self.assertEqual([p.pk for p in r.context["cl"].result_list], [partner.pk])
        r = self.http.get(url(DeliveryPartner, "changelist"), {"status__exact": "PENDING"})
        self.assertEqual([p.pk for p in r.context["cl"].result_list], [partner.pk])
        delivery = self.ready_order()
        r = self.http.get(url(Delivery, "changelist"), {"q": self.store_order.store_order_number})
        self.assertEqual([d.pk for d in r.context["cl"].result_list], [delivery.pk])

    def test_otp_and_coordinates_are_not_rendered(self):
        partner = self.make_partner("adm-secret")
        delivery = self.accepted_delivery(partner)
        delivery.refresh_from_db()
        page = self.http.get(url(Delivery, "change", delivery)).content.decode()
        if delivery.otp_nonce:
            self.assertNotIn(delivery.otp_nonce, page)
        for label in ("otp", "latitude", "longitude"):
            self.assertNotIn(label, page.lower().replace("&lt;", ""), label)
        partner_page = self.http.get(url(DeliveryPartner, "change", partner)).content.decode().lower()
        self.assertNotIn("latitude", partner_page)

    def test_notification_body_is_not_shown(self):
        n = Notification.objects.create(recipient=self.customer_user, kind="IN_TRANSIT", title="Heads up", body="PRIVATE-BODY-TEXT")
        self.assertNotContains(self.http.get(url(Notification, "change", n)), "PRIVATE-BODY-TEXT")

    def test_direct_mutation_is_forbidden(self):
        partner = self.make_partner("adm-forbid")
        for kind in ("add", "change", "delete"):
            r = self.http.post(url(DeliveryPartner, kind, None if kind == "add" else partner), {"status": "SUSPENDED", "post": "yes"})
            self.assertEqual(r.status_code, 403, kind)
        partner.refresh_from_db()
        self.assertEqual(partner.status, PartnerStatus.APPROVED)


class ActionTests(AdminBase):
    def test_partner_approve_uses_service_and_audit_fields(self):
        partner = self.make_partner("adm-approve", status=PartnerStatus.PENDING, online=False)
        step1 = self.post_action(DeliveryPartner, "approve", [partner])
        self.assertContains(step1, "Confirm")  # confirmation page first
        partner.refresh_from_db()
        self.assertEqual(partner.status, PartnerStatus.PENDING)
        self.post_action(DeliveryPartner, "approve", [partner], apply="1")
        partner.refresh_from_db()
        self.assertEqual(partner.status, PartnerStatus.APPROVED)
        self.assertEqual(partner.approved_by, self.boss)

    def test_suspend_requires_reason_and_reports_failures(self):
        ok = self.make_partner("adm-susp")
        pending = self.make_partner("adm-susp-pending", status=PartnerStatus.PENDING, online=False)
        r = self.post_action(DeliveryPartner, "suspend", [ok], apply="1")  # no reason
        self.assertContains(r, "required")
        ok.refresh_from_db()
        self.assertEqual(ok.status, PartnerStatus.APPROVED)
        r = self.http.post(url(DeliveryPartner, "changelist"), {"action": "suspend", "_selected_action": [ok.pk, pending.pk],
                                                                 "apply": "1", "reason": "Complaints"}, follow=True)
        ok.refresh_from_db(); pending.refresh_from_db()
        self.assertEqual(ok.status, PartnerStatus.SUSPENDED)
        self.assertFalse(ok.is_online)
        self.assertEqual(pending.status, PartnerStatus.PENDING)  # skipped, not silently
        self.assertContains(r, "Skipped")

    def test_review_moderation_follows_service_rules(self):
        partner = self.make_partner("adm-review")
        delivery = self.accepted_delivery(partner)
        self.pickup(delivery, partner)
        from deliveries import services as ds
        from deliveries.tests import DROP_LAT, DROP_LON, jpeg

        ds.complete_delivery(delivery.pk, partner, photos=[jpeg()], latitude=DROP_LAT, longitude=DROP_LON)
        self.store_order.refresh_from_db()
        self.api.force_authenticate(self.customer_user)
        resp = self.api.post("/api/v1/reviews/", {"store_order": self.store_order.pk, "target_type": "STORE", "rating": 2, "comment": "Bad"}, format="json")
        self.assertEqual(resp.status_code, 201, resp.content)
        review = Review.objects.get()
        self.http.post(url(Review, "changelist"), {"action": "hide", "_selected_action": [review.pk], "apply": "1"})
        review.refresh_from_db()
        self.assertEqual(review.status, ReviewStatus.PUBLISHED)  # reason missing
        self.http.post(url(Review, "changelist"), {"action": "hide", "_selected_action": [review.pk], "apply": "1", "reason": "Abusive"})
        review.refresh_from_db()
        self.assertEqual(review.status, ReviewStatus.HIDDEN)
        self.assertEqual(review.moderated_by, self.boss)
        self.assertTrue(AuditEvent.objects.filter(action="review.hide").exists())

    def test_ticket_assign_and_escalate(self):
        agent = User.objects.create_user(username="adm-agent", email="agent@example.com", password=PW, role=Role.SUPPORT_AGENT)
        self.api.force_authenticate(self.customer_user)
        self.api.post("/api/v1/support/tickets/", {"category": "ORDER", "subject": "Late", "description": "x"}, format="json")
        ticket = Ticket.objects.get()
        self.http.post(url(Ticket, "changelist"), {"action": "assign", "_selected_action": [ticket.pk], "apply": "1", "assignee": agent.pk})
        ticket.refresh_from_db()
        self.assertEqual(ticket.assigned_to, agent)
        self.http.post(url(Ticket, "changelist"), {"action": "escalate", "_selected_action": [ticket.pk], "apply": "1", "reason": "VIP"})
        ticket.refresh_from_db()
        self.assertTrue(ticket.escalated)

    def test_actions_need_change_permission_on_the_server(self):
        viewer = User.objects.create_user(username="adm-viewer", email="v@example.com", password=PW, role=Role.ADMIN, is_staff=True)
        viewer.user_permissions.add(Permission.objects.get(codename="view_deliverypartner"))
        partner = self.make_partner("adm-noperm", status=PartnerStatus.PENDING, online=False)
        c = Client()
        c.force_login(User.objects.get(pk=viewer.pk))
        c.post(url(DeliveryPartner, "changelist"), {"action": "approve", "_selected_action": [partner.pk], "apply": "1"})
        partner.refresh_from_db()
        self.assertEqual(partner.status, PartnerStatus.PENDING)
        self.assertEqual(admin.site._registry[DeliveryPartner].get_actions(self._req(viewer)), {})

    def _req(self, user):
        r = self.http.get("/django-admin/").wsgi_request
        r.user = User.objects.get(pk=user.pk)
        return r

    def test_retry_and_cancel_delivery(self):
        partner = self.make_partner("adm-cancel")
        delivery = self.accepted_delivery(partner)
        self.http.post(url(Delivery, "changelist"), {"action": "cancel", "_selected_action": [delivery.pk], "apply": "1"})
        delivery.refresh_from_db()
        self.assertEqual(delivery.status, "ACCEPTED")  # reason missing -> unchanged
        self.http.post(url(Delivery, "changelist"), {"action": "cancel", "_selected_action": [delivery.pk], "apply": "1", "reason": "Customer asked"})
        delivery.refresh_from_db()
        self.assertEqual(delivery.status, "CANCELLED")


class ApiUnchangedTests(AdminBase):
    def test_partner_api_contract_still_holds(self):
        partner = self.make_partner("adm-api", status=PartnerStatus.PENDING, online=False)
        self.api.force_authenticate(self.admin)
        r = self.api.post(f"/api/v1/admin/delivery-partners/{partner.pk}/reject/", {}, format="json")
        self.assertEqual(r.status_code, 400)
        self.assertEqual(r.json(), {"reason": ["A reason is required."]})
        r = self.api.post(f"/api/v1/admin/delivery-partners/{partner.pk}/approve/", {}, format="json")
        self.assertEqual(r.status_code, 200)
        r = self.api.post(f"/api/v1/admin/delivery-partners/{partner.pk}/approve/", {}, format="json")
        self.assertEqual(r.status_code, 400)
        self.assertIn("status", r.json())
