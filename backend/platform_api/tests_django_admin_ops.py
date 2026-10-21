from io import BytesIO

from django.contrib.admin.sites import site
from django.contrib.messages.storage.fallback import FallbackStorage
from django.test import RequestFactory, TestCase

from catalog.tests import CatalogTestMixin

from accounts.models import Role, User
from catalog.models import ProductImportBatch
from stores.admin import StoreAdmin
from stores.models import Store, StoreStatus, VerificationStatus


class DjangoAdminOpsTests(CatalogTestMixin, TestCase):
    def setUp(self):
        self.root = User.objects.create_superuser(username="root", email="r@x.test", password="Pw-12345-xyz!")
        self.root.role = Role.SUPER_ADMIN
        self.root.save()

    def _req(self, user):
        req = RequestFactory().post("/admin/stores/store/")
        req.user = user
        req.session = {}
        req._messages = FallbackStorage(req)
        return req

    def test_import_batches_are_read_only(self):
        admin_obj = site._registry[ProductImportBatch]
        req = self._req(self.root)
        self.assertFalse(admin_obj.has_add_permission(req))
        self.assertFalse(admin_obj.has_change_permission(req))
        self.assertFalse(admin_obj.has_delete_permission(req))

    def test_admin_without_approve_permission_cannot_bulk_approve(self):
        staff = User.objects.create_user(username="adm", email="a@x.test", password="Pw-12345-xyz!", is_staff=True)
        staff.role = Role.ADMIN
        staff.save()
        store = self.create_store(name='Admin Mart')
        Store.objects.filter(pk=store.pk).update(status=StoreStatus.PENDING)
        ma = StoreAdmin(Store, site)
        ma.approve_stores(self._req(staff), Store.objects.filter(pk=store.pk))
        store.refresh_from_db()
        self.assertEqual(store.status, StoreStatus.PENDING)

    def test_verify_action_never_changes_status(self):
        store = self.create_store(name='Admin Mart')
        Store.objects.filter(pk=store.pk).update(status=StoreStatus.PENDING)
        ma = StoreAdmin(Store, site)
        ma.verify_stores(self._req(self.root), Store.objects.filter(pk=store.pk))
        store.refresh_from_db()
        self.assertEqual(store.verification_status, VerificationStatus.VERIFIED)
        self.assertEqual(store.status, StoreStatus.PENDING)

    def test_workflow_fields_are_read_only_in_admin(self):
        ro = StoreAdmin(Store, site).readonly_fields
        for name in ("status", "verification_status", "approved_by", "ordering_enabled"):
            self.assertIn(name, ro)
