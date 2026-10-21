"""REST API: sessions, permissions, product CRUD, images, pagination."""
from decimal import Decimal
from unittest import mock

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client, TestCase
from django.test.utils import override_settings
from django.urls import reverse

from accounts.models import Role

from .models import Product, ProductImage, ProductStatus
from .tests import CatalogTestMixin

User = get_user_model()
PASSWORD = "secure-password-123"


class ApiBase(CatalogTestMixin, TestCase):
    expect_login = True

    def setUp(self):
        cache.clear()  # throttle counters live in the cache
        self.store = self.create_store()
        self.category = self.create_product_category(name="Groceries")
        self.superuser = User.objects.create_superuser("root", "root@example.com", PASSWORD)
        self.admin = User.objects.create_user("mgr", "mgr@example.com", PASSWORD, role=Role.ADMIN, is_staff=True)
        self.client = Client(enforce_csrf_checks=True)

    def csrf(self, client=None):
        client = client or self.client
        client.get(reverse("api_auth_session"))
        return client.cookies["csrftoken"].value

    def login(self, username="root", client=None):
        client = client or self.client
        token = self.csrf(client)
        response = client.post(reverse("api_auth_login"), {"username": username, "password": PASSWORD},
                               content_type="application/json", HTTP_X_CSRFTOKEN=token)
        assert response.status_code == 200 or not self.expect_login, response.content
        return response, client.cookies["csrftoken"].value

    def post(self, url, data, token, **kwargs):
        return self.client.post(url, data, content_type="application/json", HTTP_X_CSRFTOKEN=token, **kwargs)

    def payload(self, **overrides):
        data = {"store": self.store.pk, "name": "Rice 5kg", "sku": "RICE-5", "category": self.category.pk,
                "store_price": "245.00", "unit": "KG", "unit_value": "5"}
        data.update(overrides)
        return data


class AuthSessionTests(ApiBase):
    def test_anonymous_session_is_not_authenticated_and_sets_csrf_cookie(self):
        response = self.client.get(reverse("api_auth_session"))
        body = response.json()
        self.assertEqual((body["authenticated"], body["user"]), (False, None))
        self.assertIn("csrftoken", response.cookies)
        # The body token is a masked copy (for cross-origin clients that cannot read the cookie);
        # it must unmask to the cookie secret, i.e. be accepted as X-CSRFToken.
        from django.middleware.csrf import _unmask_cipher_token
        self.assertEqual(_unmask_cipher_token(body["csrf_token"]), response.cookies["csrftoken"].value)

    def test_login_requires_csrf(self):
        response = self.client.post(reverse("api_auth_login"), {"username": "root", "password": PASSWORD},
                                    content_type="application/json")
        self.assertEqual(response.status_code, 403)

    def test_login_restores_session_and_logout_destroys_it(self):
        response, token = self.login()
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.cookies["sessionid"]["httponly"])
        self.assertEqual(self.client.get(reverse("api_auth_session")).json()["user"]["role"], "SUPER_ADMIN")
        self.assertEqual(self.post(reverse("api_auth_logout"), {}, token).status_code, 204)
        self.assertFalse(self.client.get(reverse("api_auth_session")).json()["authenticated"])

    def test_session_survives_a_new_client_with_the_same_cookie(self):
        """Server restart / page refresh: the DB-backed session is what matters."""
        self.login()
        other = Client()
        other.cookies["sessionid"] = self.client.cookies["sessionid"].value
        self.assertTrue(other.get(reverse("api_auth_session")).json()["authenticated"])

    def test_wrong_password_and_non_management_users_are_rejected(self):
        token = self.csrf()
        bad = self.post(reverse("api_auth_login"), {"username": "root", "password": "nope"}, token)
        self.assertEqual(bad.status_code, 400)
        User.objects.create_user("cust", "c@example.com", PASSWORD, role=Role.CUSTOMER)
        customer = self.post(reverse("api_auth_login"), {"username": "cust", "password": PASSWORD}, token)
        self.assertEqual(customer.status_code, 403)
        self.assertFalse(self.client.get(reverse("api_auth_session")).json()["authenticated"])

    @override_settings(SESSION_COOKIE_AGE=60)
    def test_cookie_lifetime_follows_setting(self):
        response, _ = self.login()
        self.assertEqual(response.cookies["sessionid"]["max-age"], 60)

    def test_login_is_throttled(self):
        from rest_framework.settings import api_settings
        rates = dict(api_settings.DEFAULT_THROTTLE_RATES, login="2/min")
        with mock.patch("rest_framework.throttling.ScopedRateThrottle.THROTTLE_RATES", rates):
            token = self.csrf()
            codes = [self.post(reverse("api_auth_login"), {"username": "root", "password": "x"}, token).status_code
                     for _ in range(4)]
        self.assertIn(429, codes)


class ProductApiPermissionTests(ApiBase):
    def test_anonymous_and_store_users_are_refused(self):
        self.assertIn(self.client.get(reverse("api_product_list")).status_code, (401, 403))
        store_user = self.create_store_user(self.store)
        c = Client()
        c.force_login(store_user)
        self.assertEqual(c.get(reverse("api_product_list")).status_code, 403)

    def test_admin_needs_explicit_catalog_permissions(self):
        c = Client()
        c.force_login(self.admin)
        self.assertEqual(c.get(reverse("api_product_list")).status_code, 403)
        self.grant_catalog_perms(self.admin, "view_product")
        c = Client()
        c.force_login(self.admin)
        self.assertEqual(c.get(reverse("api_product_list")).status_code, 200)
        c.get(reverse("api_auth_session"))
        denied = c.post(reverse("api_product_list"), self.payload(), content_type="application/json",
                        HTTP_X_CSRFTOKEN=c.cookies["csrftoken"].value)
        self.assertEqual(denied.status_code, 403)


class ProductApiTests(ApiBase):
    def setUp(self):
        super().setUp()
        self.login()
        self.token = self.client.cookies["csrftoken"].value

    def test_create_uses_services_and_never_accepts_prices_or_stock(self):
        response = self.post(reverse("api_product_list"),
                             self.payload(final_price="1.00", selling_price="1.00", stock_quantity="99", status="APPROVED"),
                             self.token)
        self.assertEqual(response.status_code, 201, response.content)
        product = Product.objects.get(sku="RICE-5")
        self.assertEqual(product.status, ProductStatus.PENDING)
        self.assertEqual(product.stock_quantity, Decimal("0"))
        self.assertIsNone(product.final_price)
        self.assertTrue(product.product_code.startswith("PR"))
        self.assertEqual(product.created_by, self.superuser)

    def test_validation_errors_are_field_keyed(self):
        response = self.post(reverse("api_product_list"), self.payload(store_price="-1", name=""), self.token)
        self.assertEqual(response.status_code, 400)
        self.assertIn("store_price", response.json())
        self.assertIn("name", response.json())

    def test_duplicate_sku_in_store_is_rejected(self):
        self.post(reverse("api_product_list"), self.payload(), self.token)
        response = self.post(reverse("api_product_list"), self.payload(name="Other"), self.token)
        self.assertEqual(response.status_code, 400)

    def test_patch_updates_and_store_cannot_change(self):
        product = self.create_product(store=self.store, category=self.category, sku="A1")
        url = reverse("api_product_detail", args=[product.pk])
        response = self.client.patch(url, {"name": "Renamed"}, content_type="application/json", HTTP_X_CSRFTOKEN=self.token)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["name"], "Renamed")
        other = self.create_store(name="Other", category_name="x2")
        moved = self.client.patch(url, {"store": other.pk}, content_type="application/json", HTTP_X_CSRFTOKEN=self.token)
        self.assertEqual(moved.status_code, 400)

    def test_writes_require_csrf_token(self):
        response = self.client.post(reverse("api_product_list"), self.payload(), content_type="application/json")
        self.assertEqual(response.status_code, 403)

    def test_list_filters_search_sort_and_paginate_without_n_plus_one(self):
        for i in range(25):
            self.create_product(store=self.store, category=self.category, sku=f"S{i:02d}", name=f"Item {i:02d}")
        self.create_product(store=self.store, category=self.category, sku="ZZ", name="Special Tea")
        url = reverse("api_product_list")
        with self.assertNumQueries(6):  # session, user, count, page, prefetch tags, prefetch images
            page = self.client.get(url, {"ordering": "name"})
        data = page.json()
        self.assertEqual((data["count"], len(data["results"])), (26, 20))
        self.assertEqual(data["results"][0]["name"], "Item 00")
        self.assertEqual(self.client.get(url, {"q": "special"}).json()["count"], 1)
        self.assertEqual(self.client.get(url, {"page_size": 500}).json()["results"].__len__(), 26)  # capped at 100
        self.assertEqual(self.client.get(url, {"ordering": "drop table"}).status_code, 200)
        self.assertEqual(self.client.get(url, {"category": "abc"}).json()["count"], 0)

    def test_products_without_images_report_a_fallback_never_a_broken_url(self):
        self.create_product(store=self.store, category=self.category, sku="NOIMG")
        image = self.client.get(reverse("api_product_list")).json()["results"][0]["image"]
        self.assertEqual(image["source"], "fallback")
        self.assertIsNone(image["thumbnail_url"])
        self.assertEqual(image["fallback"]["category"], "Groceries")

    def test_has_image_filter(self):
        with_image = self.create_product(store=self.store, category=self.category, sku="WI")
        self.attach_product_image(with_image)
        self.create_product(store=self.store, category=self.category, sku="WO")
        url = reverse("api_product_list")
        self.assertEqual([p["sku"] for p in self.client.get(url, {"has_image": "true"}).json()["results"]], ["WI"])
        self.assertEqual([p["sku"] for p in self.client.get(url, {"has_image": "false"}).json()["results"]], ["WO"])

    def test_meta_lists_reference_data(self):
        data = self.client.get(reverse("api_product_meta")).json()
        self.assertEqual(data["stores"][0]["store_code"], self.store.store_code)
        self.assertTrue(data["can"]["add"])


class ProductImageApiTests(ApiBase):
    def setUp(self):
        super().setUp()
        self.login()
        self.token = self.client.cookies["csrftoken"].value
        self.product = self.create_product(store=self.store, category=self.category, sku="IMG")

    def upload(self, name="p.jpg", content=None, **extra):
        file = SimpleUploadedFile(name, content or self._jpeg_bytes((900, 600)), content_type="image/jpeg")
        return self.client.post(reverse("api_product_images", args=[self.product.pk]),
                                {"image": file, **extra}, HTTP_X_CSRFTOKEN=self.token)

    def test_upload_returns_derivative_urls_and_becomes_card_image(self):
        response = self.upload(alt_text="Rice bag")
        self.assertEqual(response.status_code, 201, response.content)
        body = response.json()
        self.assertTrue(body["thumbnail_url"].endswith(".webp"))
        self.assertTrue(body["is_primary"])
        detail = self.client.get(reverse("api_product_detail", args=[self.product.pk])).json()
        self.assertEqual(detail["image"]["source"], "uploaded")
        self.assertEqual(detail["image"]["alt_text"], "Rice bag")

    def test_invalid_image_is_a_clear_400_and_stores_nothing(self):
        response = self.upload(name="x.jpg", content=b"definitely not an image")
        self.assertEqual(response.status_code, 400)
        self.assertFalse(ProductImage.objects.exists())

    def test_missing_file_is_a_400(self):
        response = self.client.post(reverse("api_product_images", args=[self.product.pk]), {}, HTTP_X_CSRFTOKEN=self.token)
        self.assertEqual(response.status_code, 400)

    def test_storage_failure_is_503_and_leaves_no_record(self):
        with mock.patch("catalog.services.mutate_product_images", side_effect=OSError("disk full")):
            response = self.upload()
        self.assertEqual(response.status_code, 503)
        self.assertFalse(ProductImage.objects.exists())

    def test_set_primary_and_delete(self):
        first = self.upload().json()
        second = self.upload(content=self._png_bytes((50, 50)), name="b.png").json()
        self.assertTrue(first["is_primary"] and not second["is_primary"])
        primary = self.client.post(reverse("api_product_image_primary", args=[self.product.pk, second["id"]]),
                                   HTTP_X_CSRFTOKEN=self.token)
        self.assertTrue(primary.json()["is_primary"])
        deleted = self.client.delete(reverse("api_product_image", args=[self.product.pk, first["id"]]),
                                     HTTP_X_CSRFTOKEN=self.token)
        self.assertEqual(deleted.status_code, 204)
        self.assertEqual(self.product.images.count(), 1)

    def test_suggestions_are_inert_without_a_licensed_source(self):
        data = self.client.get(reverse("api_image_suggestions", args=[self.product.pk])).json()
        self.assertFalse(data["available"])
        self.assertEqual(data["candidates"], [])
