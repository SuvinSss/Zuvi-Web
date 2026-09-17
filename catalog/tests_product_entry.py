"""Batch A HTTP integration: permissions, atomic services, receipts and uploads."""
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
from threading import Barrier
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.core.exceptions import ValidationError
from django.core.files.storage import default_storage
from django.db import close_old_connections
from django.test import Client, TestCase, TransactionTestCase
from django.urls import reverse

from accounts.models import AdminAuditLog, Role
from inventory.models import InventoryTransaction
from stores.models import StoreUser, StoreStatus
from .models import Product, ProductImage, ProductPriceHistory, ProductStatus, ProductStatusHistory
from .services import add_product_image, apply_admin_pricing, record_product_status_change
from .tests import CatalogTestMixin

User = get_user_model()
AJAX = {"HTTP_X_REQUESTED_WITH": "XMLHttpRequest"}


class EntryFixtures(CatalogTestMixin):
    def setUp(self):
        super().setUp()
        self.admin = User.objects.create_superuser('entry-admin', email='entry-admin@example.com', password='synthetic-test-only')
        self.store = self.create_store()
        self.category = self.create_product_category()
        self.merchant = self.create_store_user(self.store)
        self.product = self.create_product(store=self.store, category=self.category)
        self.client.force_login(self.admin)

    def url(self, merchant=False, product=None):
        prefix = 'store_product_' if merchant else 'product_'
        return reverse('catalog:' + prefix + ('edit' if product else 'create'), args=[product.pk] if product else [])

    def payload(self, product=None, **overrides):
        data = {'store': self.store.pk, 'name': 'Entry test', 'sku': 'ENTRY-NEW',
                'category': self.category.pk, 'store_price': '100.00',
                'unit': 'PIECE', 'unit_value': '1.000', 'low_stock_threshold': '0.000',
                'description': '', 'is_active': 'on', 'entry_action': 'submit'}
        if product:
            data.update(name=product.name, sku=product.sku, description=product.description,
                        slug=product.slug, store_price=str(product.store_price), entry_action='save')
        data.update(overrides)
        return data

    def token(self, url):
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        return response.context['entry_token']

    def image(self, name='entry.jpg'):
        return self._uploaded_image(name=name)

    def approve(self):
        self.first = add_product_image(product=self.product, image=self.image('first.jpg'), changed_by=self.admin)
        apply_admin_pricing(product=self.product, profit_margin_type='FIXED', profit_margin=Decimal('20'), changed_by=self.admin)
        record_product_status_change(product=self.product, new_status=ProductStatus.APPROVED, changed_by=self.admin)
        self.product.refresh_from_db()


class ProductEntryTests(EntryFixtures, TestCase):
    def test_shared_create_pages_have_uploads_and_role_fields(self):
        for user, merchant in [(self.admin, False), (self.merchant, True)]:
            self.client.force_login(user)
            response = self.client.get(self.url(merchant))
            self.assertContains(response, 'multipart/form-data')
            self.assertContains(response, 'entry-photo-count')
            self.assertContains(response, 'Submit and add another')
            self.assertContains(response, 'category-search')
            self.assertEqual('name="apply_pricing"' in response.content.decode(), not merchant)
            self.assertNotContains(response, 'name="stock_quantity"')
            self.assertNotContains(response, 'name="final_price"')

    def test_edit_pricing_fields_show_saved_values(self):
        apply_admin_pricing(product=self.product,profit_margin_type='FIXED',profit_margin=Decimal('25'),discount_type='FIXED',discount_value=Decimal('4'),changed_by=self.admin)
        response=self.client.get(self.url(product=self.product))
        pricing=response.context['pricing_form']
        self.assertEqual(pricing['profit_margin'].value(),Decimal('25'))
        self.assertEqual(pricing['discount_value'].value(),Decimal('4'))

    def test_evicted_receipt_token_cannot_replay(self):
        from django.core import signing
        token=self.token(self.url())
        decoded=signing.loads(token,salt='catalog.product-entry')
        session=self.client.session
        session['catalog_entry_receipts_floor']=decoded['issued']
        session.save()
        response=self.client.post(self.url(),self.payload(entry_token=token),**AJAX)
        self.assertEqual(response.status_code,422)
        self.assertFalse(Product.objects.filter(sku='ENTRY-NEW').exists())

    def test_expired_token_cannot_replay(self):
        from time import time
        token=self.token(self.url())
        with patch('django.core.signing.time.time',return_value=time()+7201):
            response=self.client.post(self.url(),self.payload(entry_token=token),**AJAX)
        self.assertEqual(response.status_code,422)
        self.assertFalse(Product.objects.filter(sku='ENTRY-NEW').exists())

    def test_management_create_two_photos_primary_pricing_and_opening(self):
        data = self.payload(images=[self.image('one.jpg'), self.image('two.jpg')], main_photo='new:1',
            opening_stock='3.250', apply_pricing='1', **{'pricing-profit_margin_type':'FIXED',
            'pricing-profit_margin':'20', 'pricing-discount_type':'FIXED', 'pricing-discount_value':'5'})
        response = self.client.post(self.url(), data, **AJAX)
        self.assertEqual(response.status_code, 200, response.content)
        product = Product.objects.get(sku='ENTRY-NEW')
        self.assertEqual(product.status, ProductStatus.PENDING)
        self.assertEqual(product.final_price, Decimal('115.00'))
        self.assertEqual(product.stock_quantity, Decimal('3.250'))
        self.assertEqual(product.images.count(), 2)
        self.assertEqual(product.images.get(is_primary=True).sort_order, 1)
        self.assertEqual(InventoryTransaction.objects.filter(product=product).count(), 1)

    def test_merchant_create_two_photos_and_draft(self):
        self.client.force_login(self.merchant)
        response = self.client.post(self.url(True), self.payload(entry_action='draft',images=[self.image('a.jpg'),self.image('b.jpg')]), **AJAX)
        self.assertEqual(response.status_code, 200, response.content)
        product = Product.objects.get(sku='ENTRY-NEW')
        self.assertEqual(product.status, ProductStatus.DRAFT)
        self.assertEqual(product.images.count(), 2)
        self.assertIsNone(product.final_price)

    def test_submit_another_is_explicitly_pending_and_returns_create(self):
        response = self.client.post(self.url(), self.payload(entry_action='submit_another'), **AJAX)
        self.assertEqual(response.json()['redirect'], self.url())
        self.assertEqual(Product.objects.get(sku='ENTRY-NEW').status, ProductStatus.PENDING)

    def test_invalid_action_cannot_approve_or_create(self):
        response = self.client.post(self.url(), self.payload(entry_action='approve'), **AJAX)
        self.assertEqual(response.status_code, 422)
        self.assertFalse(Product.objects.filter(sku='ENTRY-NEW').exists())

    def test_forged_management_pricing_rejected_for_merchant(self):
        self.client.force_login(self.merchant)
        response = self.client.post(self.url(True), self.payload(apply_pricing='1', **{'pricing-profit_margin':'900'}), **AJAX)
        self.assertEqual(response.status_code, 422)
        self.assertFalse(Product.objects.filter(sku='ENTRY-NEW').exists())

    def test_legacy_merchant_fields_cannot_change_role_restricted_values(self):
        other = self.create_store()
        self.client.force_login(self.merchant)
        response = self.client.post(self.url(True), self.payload(store=other.pk, final_price='1', profit_margin='999',stock_quantity='999',status='APPROVED',is_featured='on'), **AJAX)
        self.assertEqual(response.status_code, 200, response.content)
        product = Product.objects.get(sku='ENTRY-NEW')
        self.assertEqual(product.store, self.store)
        self.assertEqual(product.status, ProductStatus.PENDING)
        self.assertEqual(product.stock_quantity, 0)
        self.assertFalse(product.is_featured)
        self.assertIsNone(product.final_price)

    def test_merchant_inventory_permission_rechecked(self):
        self.client.force_login(self.merchant)
        token = self.token(self.url(True))
        StoreUser.objects.filter(user=self.merchant).update(can_manage_inventory=False)
        response = self.client.post(self.url(True), self.payload(entry_token=token, opening_stock='5'), **AJAX)
        self.assertEqual(response.status_code, 422)
        self.assertFalse(Product.objects.filter(sku='ENTRY-NEW').exists())
        self.assertNotContains(self.client.get(self.url(True)), 'name="opening_stock"')

    def test_admin_pricing_and_inventory_require_separate_permissions(self):
        admin = User.objects.create_user('limited-entry',email='limited-entry@example.com',role=Role.ADMIN,is_staff=True)
        self.grant_catalog_perms(admin, 'add_product')
        self.client.force_login(admin)
        for extras in [dict(opening_stock='3'), dict(apply_pricing='1', **{'pricing-profit_margin':'20'})]:
            response = self.client.post(self.url(), self.payload(**extras), **AJAX)
            self.assertEqual(response.status_code, 422, response.content)
        self.assertFalse(Product.objects.filter(sku='ENTRY-NEW').exists())

    def test_merchant_foreign_product_404(self):
        self.client.force_login(self.merchant)
        other = self.create_product()
        self.assertEqual(self.client.post(self.url(True, other), self.payload(other), **AJAX).status_code, 404)

    def test_suspended_store_is_denied_after_form_open(self):
        self.client.force_login(self.merchant)
        token = self.token(self.url(True))
        self.store.status = StoreStatus.SUSPENDED
        self.store.save()
        response = self.client.post(self.url(True), self.payload(entry_token=token), **AJAX)
        self.assertEqual(response.status_code, 403)
        self.assertFalse(Product.objects.filter(sku='ENTRY-NEW').exists())

    def test_customer_and_unpermitted_admin_cannot_create(self):
        for role, staff in [(Role.CUSTOMER, False), (Role.ADMIN, True)]:
            user = User.objects.create_user('entry-'+role,email=role+'@example.com',role=role,is_staff=staff)
            self.client.force_login(user)
            self.assertEqual(self.client.post(self.url(), self.payload(), **AJAX).status_code, 403)

    def test_zero_and_negative_opening_rejected(self):
        for quantity in ['0', '-1']:
            response = self.client.post(self.url(), self.payload(opening_stock=quantity), **AJAX)
            self.assertEqual(response.status_code, 422)
        self.assertFalse(Product.objects.filter(sku='ENTRY-NEW').exists())

    def test_opening_once_only_even_on_new_form(self):
        self.client.post(self.url(product=self.product), self.payload(self.product,opening_stock='5'), **AJAX)
        response = self.client.post(self.url(product=self.product), self.payload(self.product,opening_stock='5'), **AJAX)
        self.assertEqual(response.status_code, 422)
        self.product.refresh_from_db()
        self.assertEqual(self.product.stock_quantity, 5)
        self.assertEqual(InventoryTransaction.objects.filter(product=self.product).count(), 1)

    def test_repeated_create_with_receipt_returns_original_result(self):
        token = self.token(self.url())
        responses = [self.client.post(self.url(), self.payload(entry_token=token,images=[self.image()], opening_stock='4'), **AJAX) for _ in range(2)]
        self.assertEqual(responses[0].status_code, 200, responses[0].content)
        self.assertEqual(responses[0].json(), responses[1].json())
        product = Product.objects.get(sku='ENTRY-NEW')
        self.assertEqual(product.images.count(), 1)
        self.assertEqual(InventoryTransaction.objects.filter(product=product).count(), 1)

    def test_repeated_edit_does_not_append_same_upload(self):
        url = self.url(product=self.product)
        token = self.token(url)
        for _ in range(2):
            response = self.client.post(url, self.payload(self.product,entry_token=token,images=[self.image()]), **AJAX)
            self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(self.product.images.count(), 1)

    def test_reused_receipt_with_different_payload_is_conflict(self):
        token = self.token(self.url())
        self.client.post(self.url(),self.payload(entry_token=token),**AJAX)
        response = self.client.post(self.url(),self.payload(entry_token=token,sku='OTHER-SKU'),**AJAX)
        self.assertEqual(response.status_code,422)
        self.assertFalse(Product.objects.filter(sku='OTHER-SKU').exists())

    def test_invalid_submission_then_correction_uses_same_token(self):
        token = self.token(self.url())
        bad = self.client.post(self.url(),self.payload(entry_token=token,name='',images=[self.image()],main_photo='new:0'),**AJAX)
        self.assertEqual(bad.status_code,422)
        self.assertTrue(any(error['field']=='name' for error in bad.json()['errors']))
        good = self.client.post(self.url(),self.payload(entry_token=token,images=[self.image()],main_photo='new:0'),**AJAX)
        self.assertEqual(good.status_code,200,good.content)
        self.assertEqual(Product.objects.get(sku='ENTRY-NEW').images.count(),1)

    def test_existing_sku_conflict_without_receipt_is_field_error(self):
        response = self.client.post(self.url(),self.payload(sku=self.product.sku),**AJAX)
        self.assertEqual(response.status_code,422)
        self.assertEqual(Product.objects.filter(store=self.store,sku=self.product.sku).count(),1)

    def test_forged_and_cross_form_tokens_rejected(self):
        token = self.token(self.url())
        for url, data in [(self.url(),self.payload(entry_token=token+'bad')),
                          (self.url(product=self.product),self.payload(self.product,entry_token=token))]:
            self.assertEqual(self.client.post(url,data,**AJAX).status_code,422)

    def test_full_html_reload_keeps_values_and_warns_about_files(self):
        response = self.client.post(self.url(),self.payload(name='',description='Keep this text',images=[self.image()]))
        self.assertContains(response,'Keep this text')
        self.assertContains(response,'please select any new files again')

    def test_advanced_errors_expand_details(self):
        response = self.client.post(self.url(),self.payload(manufacturing_date='2099-01-01'))
        self.assertTrue(response.context['advanced_errors'])
        self.assertContains(response,'id="entry-advanced" open')

    def test_six_images_rejected_server_side(self):
        response = self.client.post(self.url(),self.payload(images=[self.image(f'{i}.jpg') for i in range(6)]),**AJAX)
        self.assertEqual(response.status_code,422)
        self.assertFalse(Product.objects.filter(sku='ENTRY-NEW').exists())

    def test_existing_plus_new_limit_rejected(self):
        for _ in range(4):
            add_product_image(product=self.product,image=self.image(),changed_by=self.admin)
        response = self.client.post(self.url(product=self.product),self.payload(self.product,images=[self.image(),self.image()]),**AJAX)
        self.assertEqual(response.status_code,422)
        self.assertEqual(self.product.images.count(),4)

    def test_invalid_image_content_rejected(self):
        response = self.client.post(self.url(),self.payload(images=[self._uploaded_image(content=b'not an image')]),**AJAX)
        self.assertEqual(response.status_code,422)

    def test_foreign_image_selection_rejected(self):
        other = self.create_product()
        image = add_product_image(product=other,image=self.image(),changed_by=self.admin)
        for extras in [dict(remove_images=[image.pk]),dict(main_photo=f'existing:{image.pk}')]:
            response=self.client.post(self.url(product=self.product),self.payload(self.product,**extras),**AJAX)
            self.assertEqual(response.status_code,422)
        self.assertTrue(ProductImage.objects.filter(pk=image.pk).exists())

    def test_removed_primary_choice_is_rejected(self):
        image=add_product_image(product=self.product,image=self.image(),changed_by=self.admin)
        response=self.client.post(self.url(product=self.product),self.payload(self.product,remove_images=[image.pk],main_photo=f'existing:{image.pk}'),**AJAX)
        self.assertEqual(response.status_code,422)
        self.assertTrue(ProductImage.objects.filter(pk=image.pk).exists())

    def test_combined_edit_preserves_image_reapproval_and_single_history(self):
        self.approve()
        before=self.product.status_history.count()
        response=self.client.post(self.url(product=self.product),self.payload(self.product,name='Updated name',images=[self.image('new.jpg')]),**AJAX)
        self.assertEqual(response.status_code,200,response.content)
        self.product.refresh_from_db()
        self.assertEqual(self.product.status,ProductStatus.PENDING)
        self.assertIsNone(self.product.approved_by_id)
        self.assertEqual(self.product.status_history.count(),before+1)

    def test_unchanged_and_primary_only_edits_do_not_resubmit(self):
        self.approve()
        second=add_product_image(product=self.product,image=self.image('second.jpg'),changed_by=self.admin)
        record_product_status_change(product=self.product,new_status=ProductStatus.APPROVED,changed_by=self.admin)
        before=self.product.status_history.count()
        for user,merchant,extra in [(self.admin,False,{}),(self.merchant,True,{'main_photo':f'existing:{second.pk}'})]:
            self.client.force_login(user)
            response=self.client.post(self.url(merchant,self.product),self.payload(self.product,**extra),**AJAX)
            self.assertEqual(response.status_code,200,response.content)
            self.product.refresh_from_db()
            self.assertEqual(self.product.status,ProductStatus.APPROVED)
            self.assertEqual(self.product.status_history.count(),before)
        self.assertTrue(self.product.images.get(pk=second.pk).is_primary)

    def test_metadata_only_merchant_edit_does_not_resubmit(self):
        self.approve();before=self.product.status_history.count()
        self.client.force_login(self.merchant)
        response=self.client.post(self.url(True,self.product),self.payload(self.product,low_stock_threshold='2'),**AJAX)
        self.assertEqual(response.status_code,200,response.content)
        self.product.refresh_from_db()
        self.assertEqual(self.product.status,ProductStatus.APPROVED)
        self.assertEqual(self.product.status_history.count(),before)

    def test_last_image_protected_before_sensitive_merchant_edit(self):
        self.approve();before=self.product.status_history.count()
        self.client.force_login(self.merchant)
        response=self.client.post(self.url(True,self.product),self.payload(self.product,name='Changed',remove_images=[self.first.pk]),**AJAX)
        self.assertEqual(response.status_code,422,response.content)
        self.product.refresh_from_db()
        self.assertEqual(self.product.status,ProductStatus.APPROVED)
        self.assertNotEqual(self.product.name,'Changed')
        self.assertEqual(self.product.status_history.count(),before)
        self.assertTrue(ProductImage.objects.filter(pk=self.first.pk).exists())

    def test_replace_last_photo_in_combined_edit_is_allowed(self):
        self.approve()
        response=self.client.post(self.url(product=self.product),self.payload(self.product,remove_images=[self.first.pk],images=[self.image('replacement.jpg')],main_photo='new:0'),**AJAX)
        self.assertEqual(response.status_code,200,response.content)
        self.product.refresh_from_db()
        self.assertEqual(self.product.status,ProductStatus.PENDING)
        self.assertEqual(self.product.images.count(),1)

    def test_edit_cannot_draft_an_approved_product(self):
        self.approve()
        response=self.client.post(self.url(product=self.product),self.payload(self.product,entry_action='draft'),**AJAX)
        self.assertEqual(response.status_code,422)
        self.product.refresh_from_db();self.assertEqual(self.product.status,ProductStatus.APPROVED)

    def test_draft_edit_submission_does_not_approve(self):
        self.product.status=ProductStatus.DRAFT;self.product.save()
        self.client.force_login(self.merchant)
        response=self.client.post(self.url(True,self.product),self.payload(self.product,entry_action='submit'),**AJAX)
        self.assertEqual(response.status_code,200,response.content)
        self.product.refresh_from_db();self.assertEqual(self.product.status,ProductStatus.PENDING)

    def test_invalid_existing_discount_returns_global_validation_error(self):
        apply_admin_pricing(product=self.product,profit_margin_type='FIXED',profit_margin=Decimal('10'),discount_type='FIXED',discount_value=Decimal('90'),changed_by=self.admin)
        response=self.client.post(self.url(product=self.product),self.payload(self.product,store_price='20'),**AJAX)
        self.assertEqual(response.status_code,422,response.content)
        self.product.refresh_from_db();self.assertEqual(self.product.store_price,Decimal('100'))

    def test_merchant_price_edit_preserves_approved_price_pending_review(self):
        self.approve()
        apply_admin_pricing(product=self.product,profit_margin_type='FIXED',profit_margin=Decimal('10'),discount_type='FIXED',discount_value=Decimal('90'),changed_by=self.admin)
        self.client.force_login(self.merchant)
        response=self.client.post(self.url(True,self.product),self.payload(self.product,store_price='20'),**AJAX)
        self.assertEqual(response.status_code,200,response.content)
        self.product.refresh_from_db()
        self.assertEqual(self.product.status,ProductStatus.PENDING)
        self.assertEqual(self.product.final_price,Decimal('20'))
        self.assertEqual(self.product.store_price,Decimal('20'))

    def test_simultaneous_price_and_discount_update_validates_new_combination(self):
        apply_admin_pricing(product=self.product,profit_margin_type='FIXED',profit_margin=Decimal('10'),discount_type='FIXED',discount_value=Decimal('90'),changed_by=self.admin)
        response=self.client.post(self.url(product=self.product),self.payload(self.product,store_price='20',apply_pricing='1',**{'pricing-profit_margin_type':'FIXED','pricing-profit_margin':'5','pricing-discount_type':'FIXED','pricing-discount_value':'2'}),**AJAX)
        self.assertEqual(response.status_code,200,response.content)
        self.product.refresh_from_db();self.assertEqual(self.product.final_price,Decimal('23'))

    def test_late_stock_failure_rolls_back_product_images_pricing_and_history(self):
        self.approve()
        models=(Product,ProductImage,ProductStatusHistory,ProductPriceHistory,InventoryTransaction,AdminAuditLog)
        before=[model.objects.count() for model in models]
        with patch('catalog.product_entry.record_opening_stock',side_effect=ValidationError('Synthetic late failure')),patch.object(default_storage,'delete') as delete:
            response=self.client.post(self.url(product=self.product),self.payload(self.product,name='Must roll back',images=[self.image('orphan.jpg')],opening_stock='3',apply_pricing='1',**{'pricing-profit_margin_type':'FIXED','pricing-profit_margin':'30'}),**AJAX)
        self.assertEqual(response.status_code,422,response.content)
        self.assertEqual(before,[model.objects.count() for model in models])
        self.product.refresh_from_db();self.assertEqual(self.product.status,ProductStatus.APPROVED)
        self.assertNotEqual(self.product.name,'Must roll back');delete.assert_not_called()

    def test_storage_failure_rolls_back_creation_and_receipt_allows_retry(self):
        token=self.token(self.url())
        with patch.object(default_storage,'save',side_effect=OSError('Synthetic storage failure')),patch.object(default_storage,'delete') as delete:
            response=self.client.post(self.url(),self.payload(entry_token=token,images=[self.image()]),**AJAX)
        self.assertEqual(response.status_code,503,response.content)
        self.assertFalse(Product.objects.filter(sku='ENTRY-NEW').exists());delete.assert_not_called()
        response=self.client.post(self.url(),self.payload(entry_token=token,images=[self.image()]),**AJAX)
        self.assertEqual(response.status_code,200,response.content)

    def test_csrf_remains_required(self):
        client=Client(enforce_csrf_checks=True);client.force_login(self.admin)
        self.assertEqual(client.post(self.url(),self.payload(),**AJAX).status_code,403)


class ProductEntryConcurrencyTests(EntryFixtures, TransactionTestCase):
    def test_duplicate_requests_share_one_atomic_receipt(self):
        url=self.url();token=self.token(url);cookie=self.client.cookies['sessionid'].value
        barrier=Barrier(2)
        def submit():
            close_old_connections()
            try:
                client=Client();client.cookies['sessionid']=cookie
                barrier.wait(timeout=10)
                response=client.post(url,self.payload(entry_token=token,images=[self.image()],opening_stock='5'),**AJAX)
                return response.status_code,response.json()
            finally:
                close_old_connections()
        with ThreadPoolExecutor(max_workers=2) as pool:
            results=list(pool.map(lambda _:submit(),range(2)))
        self.assertEqual(results[0][0],200,results)
        self.assertEqual(results[0],results[1])
        product=Product.objects.get(sku='ENTRY-NEW')
        self.assertEqual(product.images.count(),1)
        self.assertEqual(InventoryTransaction.objects.filter(product=product).count(),1)
