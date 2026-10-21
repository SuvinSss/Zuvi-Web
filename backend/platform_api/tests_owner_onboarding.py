"""Store owner accounts: invite link, existing-user assignment, boundaries, rollback."""
from django.core import mail
from django.test import override_settings
from rest_framework.test import APIClient

from accounts.models import AdminAuditLog, Role, User
from platform_api.tests_admin_stores import HOURS, StoreWizardBase, payload
from stores.models import Store, StoreUser

NEW_OWNER = {"username": "inv-owner", "email": "inv-owner@example.com", "first_name": "Inv"}


class OwnerInviteTests(StoreWizardBase):
    def create(self, **extra):
        return self.post(self.boss, payload(category=self.cat.pk, **extra))

    def test_owner_without_password_gets_one_time_link_and_unusable_password(self):
        r = self.create(owner=NEW_OWNER)
        self.assertEqual(r.status_code, 201, r.content)
        setup = r.json()["owner_setup"]
        self.assertIn("/setup-account?token=", setup["link"])
        self.assertFalse(setup["email_sent"])  # no mail server configured: never claim delivery
        user = User.objects.get(username="inv-owner")
        self.assertFalse(user.has_usable_password())
        self.assertEqual(user.role, Role.STORE_USER)
        self.assertTrue(StoreUser.objects.filter(user=user, is_primary=True).exists())

    def test_link_sets_password_once_then_owner_can_log_in(self):
        token = self.create(owner=NEW_OWNER).json()["owner_setup"]["link"].split("token=")[1]
        anon = APIClient()
        weak = anon.post("/api/v1/auth/invite/accept/", {"token": token, "new_password": "123"}, format="json")
        self.assertEqual(weak.status_code, 400)
        ok = anon.post("/api/v1/auth/invite/accept/", {"token": token, "new_password": "Fresh-Owner-Pass-77!"}, format="json")
        self.assertEqual(ok.status_code, 204, ok.content)
        again = anon.post("/api/v1/auth/invite/accept/", {"token": token, "new_password": "Another-Pass-88!"}, format="json")
        self.assertEqual(again.status_code, 400)  # single use
        self.assertTrue(User.objects.get(username="inv-owner").check_password("Fresh-Owner-Pass-77!"))

    def test_tampered_token_is_rejected(self):
        token = self.create(owner=NEW_OWNER).json()["owner_setup"]["link"].split("token=")[1]
        r = APIClient().post("/api/v1/auth/invite/accept/", {"token": token[:-3] + "abc", "new_password": "Fresh-Owner-Pass-77!"}, format="json")
        self.assertEqual(r.status_code, 400)

    def test_expired_token_is_rejected(self):
        from stores import management
        token = self.create(owner=NEW_OWNER).json()["owner_setup"]["link"].split("token=")[1]
        with override_settings():
            old = management.INVITE_MAX_AGE
            management.INVITE_MAX_AGE = -1
            try:
                r = APIClient().post("/api/v1/auth/invite/accept/", {"token": token, "new_password": "Fresh-Owner-Pass-77!"}, format="json")
            finally:
                management.INVITE_MAX_AGE = old
        self.assertEqual(r.status_code, 400)

    @override_settings(EMAIL_HOST="smtp.test", EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend", FRONTEND_BASE_URL="https://admin.zuuvi.test")
    def test_email_is_reported_sent_only_when_delivered(self):
        setup = self.create(owner=NEW_OWNER).json()["owner_setup"]
        self.assertTrue(setup["email_sent"])
        self.assertEqual(len(mail.outbox), 1)
        self.assertTrue(setup["link"].startswith("https://admin.zuuvi.test/setup-account?token="))

    def test_link_and_password_never_reach_audit_records(self):
        r = self.create(owner={**NEW_OWNER, "password": "Admin-Chosen-Pass-55!"})
        self.assertNotIn("owner_setup", r.json())  # admin set a password: no link issued
        link_run = self.create(owner={**NEW_OWNER, "username": "inv2", "email": "inv2@example.com"}, name="Second")
        token = link_run.json()["owner_setup"]["link"].split("token=")[1]
        blob = " ".join(str(m) for m in AdminAuditLog.objects.values_list("metadata", "description"))
        self.assertNotIn(token, blob)
        self.assertNotIn("Admin-Chosen-Pass-55!", blob)

    def test_duplicate_username_rolls_back_the_store(self):
        User.objects.create_user(username="inv-owner", email="other@example.com", password="x")
        before = Store.objects.count()
        r = self.create(owner=NEW_OWNER)
        self.assertEqual(r.status_code, 400)
        self.assertEqual(Store.objects.count(), before)

    def test_assign_existing_store_user(self):
        existing = User.objects.create_user(username="old-owner", email="old@example.com", password="x", role=Role.STORE_USER)
        found = self.as_user(self.boss).get("/api/v1/admin/stores/owner-candidates/?q=old-ow").json()
        self.assertEqual([c["id"] for c in found], [existing.pk])
        r = self.create(existing_owner=existing.pk)
        self.assertEqual(r.status_code, 201, r.content)
        self.assertTrue(StoreUser.objects.filter(user=existing, store_id=r.json()["id"], is_primary=True).exists())

    def test_ineligible_accounts_cannot_be_assigned(self):
        customer = User.objects.create_user(username="cust-x", email="cust-x@example.com", password="x", role=Role.CUSTOMER)
        self.assertEqual(self.create(existing_owner=customer.pk).status_code, 400)
        self.assertEqual(self.create(existing_owner=self.boss.pk).status_code, 400)  # never the acting admin
        self.assertEqual(self.create(existing_owner=customer.pk, owner=NEW_OWNER).status_code, 400)

    def test_candidate_search_needs_permission(self):
        plain = User.objects.create_user(username="no-perm", email="np@example.com", password="x", role=Role.ADMIN, is_staff=True)
        self.assertEqual(self.as_user(plain).get("/api/v1/admin/stores/owner-candidates/?q=ab").status_code, 403)

    def test_owner_is_limited_to_own_store(self):
        first = self.create(owner=NEW_OWNER).json()
        second = self.create(owner={**NEW_OWNER, "username": "inv-b", "email": "inv-b@example.com"}, name="Other Shop").json()
        owner = User.objects.get(username="inv-owner")
        api = self.as_user(owner)
        self.assertEqual(api.get("/api/v1/admin/stores/").status_code, 403)  # management API is closed to owners
        self.assertEqual(StoreUser.objects.filter(user=owner).values_list("store_id", flat=True).get(), first["id"])
        self.assertNotEqual(first["id"], second["id"])

    def test_resend_invite_only_for_members_without_password(self):
        r = self.create(owner=NEW_OWNER).json()
        uid = User.objects.get(username="inv-owner").pk
        again = self.post(self.boss, {"user": uid}, path=f"admin/stores/{r['id']}/invite/")
        self.assertEqual(again.status_code, 200, again.content)
        self.assertIn("token=", again.json()["owner_setup"]["link"])
        u = User.objects.get(pk=uid); u.set_password("Set-Already-Pass-12!"); u.save()
        self.assertEqual(self.post(self.boss, {"user": uid}, path=f"admin/stores/{r['id']}/invite/").status_code, 400)
