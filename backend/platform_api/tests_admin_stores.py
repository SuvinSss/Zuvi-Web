"""Store creation wizard, approval rules, editing, staff, documents, verification, list filters."""
from django.contrib.auth.models import Permission
from django.core.files.uploadedfile import SimpleUploadedFile

from accounts.models import AdminAuditLog, Role, User
from deliveries.tests import DeliveryBase
from stores.models import Store, StoreCategory, StoreDocument, StoreStatus, VerificationStatus

HOURS = {d: [{"open": "09:00", "close": "21:00"}] for d in ("mon", "tue", "wed", "thu", "fri", "sat")}
OWNER = {"username": "wiz-owner", "email": "wiz-owner@example.com", "password": "Wiz-Owner-Pass-91!", "first_name": "Wiz"}


def payload(**extra):
    base = {
        "name": "Green Basket", "store_type": "PARTNER_STORE", "contact_phone": "9876543210",
        "address": {"line1": "12 Market Rd", "city": "Kochi", "state": "Kerala", "postal_code": "682001", "latitude": "9.931233", "longitude": "76.267303"},
        "offers_delivery": True, "service_radius_km": "5", "opening_hours": HOURS,
    }
    base.update(extra)
    return base


class StoreWizardBase(DeliveryBase):
    def setUp(self):
        super().setUp()
        self.cat = StoreCategory.objects.create(name="Wizard grocery")
        self.boss = User.objects.create_superuser(username="wz-boss", email="wz-boss@example.com", password="x")
        self.boss.role = Role.SUPER_ADMIN
        self.boss.save()
        self.perm_admin = User.objects.create_user(username="wz-perm", email="wz-perm@example.com", password="x", role=Role.ADMIN, is_staff=True)
        for code in ("add_store", "change_store", "view_store"):
            self.perm_admin.user_permissions.add(Permission.objects.get(content_type__app_label="stores", codename=code))

    def post(self, user, body, path="admin/stores/"):
        return self.as_user(user).post(f"/api/v1/{path}", body, format="json")


class CreateStoreTests(StoreWizardBase):
    def test_super_admin_complete_store_is_approved_with_approver_recorded(self):
        r = self.post(self.boss, payload(category=self.cat.pk, owner=OWNER))
        self.assertEqual(r.status_code, 201, r.content)
        self.assertEqual(r.json()["status"], "ACTIVE")
        store = Store.objects.get(pk=r.json()["id"])
        self.assertEqual(store.approved_by, self.boss)
        self.assertIsNotNone(store.approved_at)
        self.assertEqual(store.creation_source, "ADMIN")
        self.assertTrue(store.slug.startswith("green-basket"))
        self.assertTrue(store.ordering_enabled)
        self.assertEqual(store.verification_status, VerificationStatus.UNVERIFIED)  # never auto-verified
        self.assertTrue(AdminAuditLog.objects.filter(action="STORE_CREATED", metadata__store_id=store.pk, metadata__auto_approved=True).exists())

    def test_client_cannot_force_status_approval_or_verification(self):
        r = self.post(self.boss, payload(category=self.cat.pk, owner=OWNER, status="ACTIVE", verification_status="VERIFIED", approved_by=1, ordering_enabled=True, save_draft=True))
        self.assertEqual(r.status_code, 201)
        store = Store.objects.get(pk=r.json()["id"])
        self.assertEqual(store.status, StoreStatus.DRAFT)
        self.assertIsNone(store.approved_by)
        self.assertEqual(store.verification_status, VerificationStatus.UNVERIFIED)

    def test_admin_without_approve_permission_creates_pending(self):
        r = self.post(self.perm_admin, payload(category=self.cat.pk, owner=OWNER, commission_percentage="12"))
        self.assertEqual(r.status_code, 201, r.content)
        self.assertEqual(r.json()["status"], "PENDING")
        store = Store.objects.get(pk=r.json()["id"])
        self.assertIsNone(store.approved_by)
        self.assertEqual(str(store.commission_percentage), "0.00")  # commercial terms need approval rights

    def test_missing_requirements_give_needs_information(self):
        r = self.post(self.boss, payload(contact_phone="", category=self.cat.pk))
        self.assertEqual(r.json()["status"], "NEEDS_INFO")
        self.assertIn("Contact phone", r.json()["missing"])
        self.assertIn("Store owner account", r.json()["missing"])
        self.assertEqual(self.post(self.boss, payload()).status_code, 400)  # category is mandatory

    def test_unset_location_is_never_treated_as_complete(self):
        body = payload(category=self.cat.pk, owner=OWNER)
        body["address"].pop("latitude"); body["address"].pop("longitude")
        r = self.post(self.boss, body)
        self.assertEqual(r.json()["status"], "NEEDS_INFO")
        self.assertIn("Map location (latitude and longitude)", r.json()["missing"])

    def test_approved_store_without_hours_cannot_take_orders(self):
        r = self.post(self.boss, payload(category=self.cat.pk, owner=OWNER, opening_hours={}))
        store = Store.objects.get(pk=r.json()["id"])
        self.assertEqual(store.status, StoreStatus.ACTIVE)
        self.assertFalse(store.ordering_enabled)
        self.assertIn("Opening hours", r.json()["operational_gaps"])

    def test_validation_errors(self):
        c = self.cat.pk
        self.assertEqual(self.post(self.boss, payload(category=c, gstin="NOT-A-GSTIN")).status_code, 400)
        self.assertEqual(self.post(self.boss, payload(category=c, opening_hours={"mon": [{"open": "21:00", "close": "09:00"}]})).status_code, 400)
        self.assertEqual(self.post(self.boss, payload(category=c, opening_hours={"mon": [{"open": "09:00", "close": "12:00"}, {"open": "11:00", "close": "14:00"}]})).status_code, 400)
        bad = payload(category=c); bad["address"]["latitude"] = "123"
        self.assertEqual(self.post(self.boss, bad).status_code, 400)
        weak = self.post(self.boss, payload(category=c, owner={**OWNER, "password": "123"}))
        self.assertEqual(weak.status_code, 400)
        self.assertEqual(Store.objects.filter(name="Green Basket").count(), 0)  # rolled back, no half-created store

    def test_permissions(self):
        self.assertEqual(self.post(self.admin, payload()).status_code, 403)  # admin without stores.add_store
        self.assertEqual(self.post(self.store_user, payload()).status_code, 403)
        self.assertEqual(self.post(self.customer_user, payload()).status_code, 403)
        self.api.force_authenticate(None)
        self.assertIn(self.api.post("/api/v1/admin/stores/", payload(), format="json").status_code, (401, 403))

    def test_duplicate_names_get_unique_slugs(self):
        a = self.post(self.boss, payload(category=self.cat.pk)).json()["id"]
        b = self.post(self.boss, payload(category=self.cat.pk)).json()["id"]
        self.assertNotEqual(Store.objects.get(pk=a).slug, Store.objects.get(pk=b).slug)


class ManageStoreTests(StoreWizardBase):
    def make(self, **extra):
        return Store.objects.get(pk=self.post(self.boss, payload(category=self.cat.pk, **extra)).json()["id"])

    def test_edit_recomputes_requirements_and_moves_needs_info_to_pending(self):
        store = self.make(owner=OWNER, contact_phone="")
        self.assertEqual(store.status, StoreStatus.NEEDS_INFO)
        r = self.as_user(self.boss).patch(f"/api/v1/admin/stores/{store.pk}/", {"contact_phone": "9876500000"}, format="json")
        self.assertEqual(r.status_code, 200, r.content)
        store.refresh_from_db()
        self.assertEqual(store.status, StoreStatus.PENDING)
        self.assertEqual(store.missing_requirements, [])

    def test_edit_cannot_set_status_and_audits_field_names_only(self):
        store = self.make(owner=OWNER)
        self.as_user(self.boss).patch(f"/api/v1/admin/stores/{store.pk}/", {"status": "SUSPENDED", "description": "secret text"}, format="json")
        store.refresh_from_db()
        self.assertEqual(store.status, StoreStatus.ACTIVE)
        log = AdminAuditLog.objects.filter(action="STORE_UPDATED", metadata__store_id=store.pk).latest("pk")
        self.assertEqual(log.metadata["fields"], ["description"])
        self.assertNotIn("secret text", str(log.metadata))

    def test_commercial_terms_need_approval_permission(self):
        store = self.make(owner=OWNER)
        r = self.as_user(self.perm_admin).patch(f"/api/v1/admin/stores/{store.pk}/", {"commission_percentage": "20"}, format="json")
        self.assertEqual(r.status_code, 400)
        self.assertEqual(self.as_user(self.boss).patch(f"/api/v1/admin/stores/{store.pk}/", {"commission_percentage": "20"}, format="json").status_code, 200)

    def test_admin_without_change_permission_cannot_edit(self):
        store = self.make(owner=OWNER)
        self.assertEqual(self.as_user(self.admin).patch(f"/api/v1/admin/stores/{store.pk}/", {"description": "x"}, format="json").status_code, 403)

    def test_approve_pending_created_store_stamps_approver_and_blocks_incomplete(self):
        store = self.make(owner=OWNER, save_draft=True, contact_phone="")
        self.assertEqual(self.post(self.boss, {"status": "ACTIVE"}, f"admin/stores/{store.pk}/status/").status_code, 400)
        self.as_user(self.boss).patch(f"/api/v1/admin/stores/{store.pk}/", {"contact_phone": "9876500000"}, format="json")
        r = self.post(self.boss, {"status": "ACTIVE"}, f"admin/stores/{store.pk}/status/")
        self.assertEqual(r.status_code, 200, r.content)
        store.refresh_from_db()
        self.assertEqual(store.approved_by, self.boss)

    def test_adding_owner_clears_needs_info(self):
        store = self.make()
        self.assertEqual(store.status, StoreStatus.NEEDS_INFO)
        r = self.post(self.boss, {**OWNER, "is_primary": True}, f"admin/stores/{store.pk}/staff/")
        self.assertEqual(r.status_code, 201, r.content)
        store.refresh_from_db()
        self.assertEqual(store.status, StoreStatus.PENDING)
        self.assertEqual(self.as_user(self.boss).get(f"/api/v1/admin/stores/{store.pk}/staff/").json()[0]["username"], "wiz-owner")
        self.assertNotIn("password", str(self.as_user(self.boss).get(f"/api/v1/admin/stores/{store.pk}/staff/").json()))

    def test_documents_validate_type_and_never_verify(self):
        store = self.make(owner=OWNER)
        api = self.as_user(self.boss)
        bad = api.post(f"/api/v1/admin/stores/{store.pk}/documents/", {"kind": "GST", "file": SimpleUploadedFile("x.exe", b"MZ")}, format="multipart")
        self.assertEqual(bad.status_code, 400)
        fake = api.post(f"/api/v1/admin/stores/{store.pk}/documents/", {"kind": "GST", "file": SimpleUploadedFile("x.pdf", b"not a pdf at all")}, format="multipart")
        self.assertEqual(fake.status_code, 400)
        ok = api.post(f"/api/v1/admin/stores/{store.pk}/documents/", {"kind": "GST", "file": SimpleUploadedFile("gst.pdf", b"%PDF-1.4 test")}, format="multipart")
        self.assertEqual(ok.status_code, 201, ok.content)
        store.refresh_from_db()
        self.assertEqual(store.verification_status, VerificationStatus.UNVERIFIED)
        StoreDocument.objects.all().delete()

    def test_verification_is_explicit_and_permissioned(self):
        store = self.make(owner=OWNER)
        self.assertEqual(self.post(self.perm_admin, {"verification_status": "VERIFIED"}, f"admin/stores/{store.pk}/verify/").status_code, 403)
        self.assertEqual(self.post(self.boss, {"verification_status": "UNVERIFIED"}, f"admin/stores/{store.pk}/verify/").status_code, 400)
        self.assertEqual(self.post(self.boss, {"verification_status": "VERIFIED"}, f"admin/stores/{store.pk}/verify/").status_code, 200)
        store.refresh_from_db()
        self.assertEqual((store.verification_status, store.verified_by), ("VERIFIED", self.boss))

    def test_detail_list_filters_and_export(self):
        store = self.make(owner=OWNER)
        d = self.as_user(self.boss).get(f"/api/v1/admin/stores/{store.pk}/").json()
        self.assertEqual(d["address"]["city"], "Kochi")
        self.assertEqual(d["counts"]["staff"], 1)
        self.assertEqual(d["history"][0]["new"], "ACTIVE")
        lst = lambda **p: self.as_user(self.boss).get("/api/v1/admin/stores/", p).json()["count"]
        self.assertEqual(lst(city="kochi", category=self.cat.pk), 1)
        self.assertEqual(lst(status="DRAFT"), 0)
        self.assertEqual(lst(q="green"), 1)
        self.assertEqual(lst(verification="VERIFIED"), 0)
        csv_resp = self.as_user(self.boss).get("/api/v1/admin/stores/export/", {"q": "green"})
        body = b"".join(csv_resp.streaming_content).decode()
        self.assertIn("Green Basket", body)
        self.assertEqual(self.as_user(self.admin).get("/api/v1/admin/stores/export/").status_code, 403)

    def test_checkout_gate_uses_ordering_enabled(self):
        from orders.checkout import _validate_sellable_product
        from django.core.exceptions import ValidationError
        product = self.product
        product.store.ordering_enabled = False
        product.store.save()
        with self.assertRaises(ValidationError) as ctx:
            _validate_sellable_product(product, 1)
        self.assertIn("not taking orders", str(ctx.exception))
