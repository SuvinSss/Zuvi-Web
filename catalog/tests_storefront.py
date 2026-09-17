"""Behavior and query regressions for the shared customer catalogue."""
from decimal import Decimal
from html.parser import HTMLParser
from io import StringIO
from types import SimpleNamespace

from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from django.urls import reverse

from cart.models import CartItem
from catalog.management.commands.seed_catalog_departments import DEPARTMENTS
from catalog.models import ProductCategory, ProductStatus
from catalog.public import public_category_navigation, public_product_card, public_products_queryset
from catalog.tests_public import PublicCatalogueTestMixin


class StorefrontBrowsingTests(PublicCatalogueTestMixin, TestCase):
    def setUp(self):
        self.department = self.create_product_category(name="Groceries & Daily Essentials")
        self.child = self.create_product_category(name="Rice", parent=self.department)
        self.grandchild = self.create_product_category(name="Brown Rice", parent=self.child)
        self.store = self.create_store(name="Private Fulfilling Merchant")
        self.brand = self.create_brand(name="Synthetic Kitchen")
        self.root_product = self.create_public_product(name="Department Pick", store=self.store, category=self.department, brand=self.brand)
        self.child_product = self.create_public_product(name="Rice Pick", store=self.store, category=self.child, brand=self.brand)
        self.grandchild_product = self.create_public_product(name="Brown Rice Pick", store=self.store, category=self.grandchild, brand=self.brand)
        self.other = self.create_public_product(name="Unrelated Pick", store=self.store, brand=self.brand)
        self.list_url = reverse("catalog:public_product_list")
        self.department_url = reverse("catalog:public_category_detail", args=[self.department.slug])

    def test_department_includes_direct_child_and_grandchild_once(self):
        response = self.client.get(self.department_url)
        codes = [product["product_code"] for product in response.context["products"]]
        self.assertCountEqual(codes, [self.root_product.product_code, self.child_product.product_code, self.grandchild_product.product_code])
        self.assertEqual(len(codes), len(set(codes)))
        self.assertContains(response, reverse("catalog:public_category_detail", args=[self.child.slug]))

    def test_category_filter_includes_descendants(self):
        response = self.client.get(self.list_url, {"category": self.child.slug})
        self.assertCountEqual([row["id"] for row in response.context["products"]], [self.child_product.pk, self.grandchild_product.pk])

    def test_route_department_cannot_be_escaped_with_other_category(self):
        response = self.client.get(self.department_url, {"category": self.other.category.slug})
        self.assertNotContains(response, self.other.name)
        self.assertEqual(response.context["result_count"], 3)

    def test_pending_descendant_is_not_exposed(self):
        self.grandchild_product.status = ProductStatus.PENDING
        self.grandchild_product.save(update_fields=["status"])
        response = self.client.get(self.department_url)
        self.assertNotContains(response, self.grandchild_product.name)
        self.assertEqual(response.context["result_count"], 2)

    def test_inactive_leaf_is_not_exposed(self):
        self.grandchild.is_active = False
        self.grandchild.save(update_fields=["is_active"])
        self.assertNotContains(self.client.get(self.department_url), self.grandchild_product.name)

    def test_unknown_category_filter_is_an_error_not_all_products(self):
        response = self.client.get(self.list_url, {"category": "not-a-category"})
        self.assertContains(response, "Please check your filters")
        self.assertEqual(response.context["result_count"], 0)
        self.assertNotContains(response, self.root_product.name)

    def test_invalid_prices_are_retained_and_do_not_broaden_results(self):
        for values in ({"min_price": "oops"}, {"min_price": "-1"}, {"min_price": "NaN"}, {"min_price": "Infinity"}, {"min_price": "100", "max_price": "1"}):
            with self.subTest(values=values):
                response = self.client.get(self.list_url, values)
                self.assertEqual(response.status_code, 200)
                self.assertContains(response, "Please check your filters")
                self.assertEqual(response.context["result_count"], 0)
                self.assertTrue(response.context["filter_form"].errors)

    def test_unknown_sort_is_explained(self):
        response = self.client.get(self.list_url, {"sort": "bogus"})
        self.assertContains(response, "Please check your filters")
        self.assertEqual(response.context["result_count"], 0)

    def test_price_sort_is_stable(self):
        for sort, expected in (("price", "pk"), ("price_desc", "pk"), ("name", "name"), ("name_desc", "-name"), ("newest", "-created_at")):
            with self.subTest(sort=sort):
                response = self.client.get(self.list_url, {"sort": sort})
                products = [row["id"] for row in response.context["products"]]
                self.assertEqual(products, list(public_products_queryset().order_by(expected, "pk").values_list("pk", flat=True)))

    def test_merchant_name_is_not_a_public_search_key(self):
        response = self.client.get(self.list_url, {"q": self.store.name})
        self.assertEqual(response.context["result_count"], 0)
        self.assertNotContains(response, self.root_product.name)

    def test_safe_card_omits_merchant_identity(self):
        card = public_product_card(public_products_queryset().get(pk=self.child_product.pk))
        for key in ("store_name", "store_id", "store_code", "store_price", "profit_margin"):
            self.assertNotIn(key, card)

    def test_pagination_preserves_department_search_brand_price_and_sort(self):
        for index in range(14):
            self.create_public_product(name=f"Rice fixture {index:02}", store=self.store, category=self.child, brand=self.brand)
        response = self.client.get(self.department_url, {"q": "Rice", "brand": self.brand.slug, "min_price": "10", "sort": "name", "page": "2"})
        self.assertEqual(response.context["page_obj"].number, 2)
        self.assertEqual(len(response.context["products"]), 4)
        for part in ("q=Rice", "brand=synthetic-kitchen", "min_price=10", "sort=name"):
            self.assertIn(part, response.context["querystring"])
        self.assertNotIn("page=", response.context["querystring"])

    def test_image_prefetch_covers_missing_primary_and_no_image(self):
        self.attach_image(self.child_product, primary=False)
        self.attach_image(self.grandchild_product)
        with self.assertNumQueries(2):
            cards = [public_product_card(product) for product in public_products_queryset()]
        by_id = {card["id"]: card for card in cards}
        self.assertTrue(by_id[self.child_product.pk]["primary_image_url"])
        self.assertEqual(by_id[self.root_product.pk]["primary_image_url"], "")

    def test_listing_queries_do_not_grow_with_page_items(self):
        with CaptureQueriesContext(connection) as initial:
            self.client.get(self.list_url)
        for index in range(10):
            self.create_public_product(name=f"Scale fixture {index}", store=self.store, category=self.child, brand=self.brand)
        with CaptureQueriesContext(connection) as expanded:
            response = self.client.get(self.list_url)
        self.assertEqual(len(response.context["products"]), 12)
        self.assertLessEqual(len(expanded), len(initial) + 1)
        self.assertLessEqual(len(expanded), 12)

    def test_navigation_reuses_one_request_query(self):
        request = SimpleNamespace()
        with self.assertNumQueries(1):
            first = public_category_navigation(request)
            second = public_category_navigation(request)
        self.assertIs(first, second)
        root = next(row for row in first["departments"] if row["pk"] == self.department.pk)
        self.assertEqual(root["children"][0]["children"][0]["pk"], self.grandchild.pk)

    def test_home_sections_are_bounded(self):
        for index in range(12):
            self.create_public_product(name=f"Featured fixture {index}", store=self.store, category=self.child, brand=self.brand, is_featured=True)
        response = self.client.get(reverse("catalog:public_home"))
        self.assertEqual(len(response.context["featured_products"]), 8)
        self.assertEqual(len(response.context["newest_products"]), 8)
        self.assertNotContains(response, self.store.name)

    def test_gallery_keeps_all_photos_and_keyboard_links(self):
        self.attach_image(self.child_product)
        self.attach_image(self.child_product, primary=False)
        response = self.client.get(reverse("catalog:public_product_detail", args=[self.child_product.slug]))
        self.assertEqual(len(response.context["product"]["images"]), 2)
        self.assertContains(response, 'data-sf-gallery-photo', count=2)
        self.assertContains(response, 'id="sf-gallery-status"')
        self.assertNotContains(response, self.store.name)


class CategorySeedTests(TestCase):
    def seed(self, apply=False):
        output = StringIO()
        call_command("seed_catalog_departments", apply=apply, stdout=output)
        return output.getvalue()

    def test_default_is_dry_run(self):
        self.assertIn("Dry run", self.seed())
        self.assertFalse(ProductCategory.objects.exists())

    def test_apply_and_repeat_are_additive(self):
        self.seed(apply=True)
        expected = sum(1 + len(children) for _, children in DEPARTMENTS)
        self.assertEqual(ProductCategory.objects.count(), expected)
        before = list(ProductCategory.objects.values())
        self.assertIn("0 additions", self.seed(apply=True))
        self.assertEqual(list(ProductCategory.objects.values()), before)

    def test_unrelated_existing_category_is_unchanged(self):
        category = ProductCategory.objects.create(name="Existing local category", slug="existing-local")
        self.seed(apply=True)
        category.refresh_from_db()
        self.assertEqual((category.name, category.slug, category.parent_id), ("Existing local category", "existing-local", None))

    def test_conflicting_slug_aborts_before_any_creation(self):
        ProductCategory.objects.create(name="Existing different name", slug="mobiles-accessories")
        with self.assertRaisesMessage(CommandError, "Category conflicts"):
            self.seed(apply=True)
        self.assertEqual(ProductCategory.objects.count(), 1)

    def test_same_name_different_slug_is_not_renamed(self):
        row = ProductCategory.objects.create(name="Groceries & Daily Essentials", slug="legacy-groceries")
        with self.assertRaises(CommandError):
            self.seed(apply=True)
        row.refresh_from_db()
        self.assertEqual(row.slug, "legacy-groceries")
        self.assertEqual(ProductCategory.objects.count(), 1)

    def test_existing_child_is_not_reparented(self):
        row = ProductCategory.objects.create(name="Earrings", slug="earrings")
        with self.assertRaises(CommandError):
            self.seed(apply=True)
        row.refresh_from_db()
        self.assertIsNone(row.parent_id)
        self.assertEqual(ProductCategory.objects.count(), 1)

    def test_inactive_matching_category_is_not_reactivated(self):
        row = ProductCategory.objects.create(name="Home & Kitchen", slug="home-kitchen", is_active=False)
        with self.assertRaises(CommandError):
            self.seed(apply=True)
        row.refresh_from_db()
        self.assertFalse(row.is_active)
        self.assertEqual(ProductCategory.objects.count(), 1)


class CustomerShellAndCartTests(PublicCatalogueTestMixin, TestCase):
    def setUp(self):
        self.product = self.create_public_product(name="Synthetic Cart Rice")
        self.customer = self.create_customer()
        self.client.force_login(self.customer.user)
        self.client.post(reverse("cart:cart_add_item", args=[self.product.product_code]), {"quantity": "2"})

    def test_shared_header_and_original_customer_routes(self):
        response = self.client.get(reverse("cart:cart_detail"))
        for name in ("customer_portal_dashboard", "customer_portal_profile", "customer_portal_address_list", "customer_portal_logout"):
            self.assertContains(response, reverse("customers:" + name))
        self.assertContains(response, 'class="zuuvi-storefront"')
        self.assertContains(response, 'id="sf-search"')
        self.assertContains(response, "Preview subtotal")

    def test_cart_views_hide_merchant_and_internal_stock(self):
        for route in ("cart:cart_detail", "cart:cart_mini"):
            response = self.client.get(reverse(route))
            self.assertContains(response, self.product.name)
            self.assertNotContains(response, self.product.store.name)
            self.assertNotContains(response, 'data-stock=')
            self.assertNotContains(response, self.product.sku)

    def test_cart_reading_does_not_change_stock_or_quantity(self):
        before = self.product.stock_quantity
        self.client.get(reverse("cart:cart_detail"))
        self.client.get(reverse("cart:cart_mini"))
        self.product.refresh_from_db()
        self.assertEqual(self.product.stock_quantity, before)
        self.assertEqual(CartItem.objects.get(product=self.product).quantity, Decimal("2"))

    def test_shared_forms_do_not_nest(self):
        class Forms(HTMLParser):
            depth = 0
            nested = False
            def handle_starttag(self, tag, attrs):
                if tag == "form":
                    self.depth += 1
                    self.nested |= self.depth > 1
            def handle_endtag(self, tag):
                if tag == "form":
                    self.depth -= 1
        for url in (reverse("catalog:public_home"), reverse("catalog:public_product_list"), reverse("catalog:public_product_detail", args=[self.product.slug]), reverse("cart:cart_detail")):
            parser = Forms()
            parser.feed(self.client.get(url).content.decode())
            self.assertFalse(parser.nested, url)
            self.assertEqual(parser.depth, 0, url)
