from decimal import Decimal
from urllib.parse import parse_qs, urlparse

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.test import Client, TestCase
from django.urls import reverse

from accounts.models import Role
from catalog.models import Product, ProductCategory, ProductStatus, ProductUnit
from catalog.pricing import MarginType
from customers.models import Customer, RegistrationSource
from customers.services import create_customer_with_user
from inventory.services import record_manual_stock_in
from locations.models import Address
from stores.models import Store, StoreCategory, StoreStatus, StoreType

from .models import Cart, CartItem
from .services import (
    add_product_to_cart,
    build_cart_view_context,
    clear_cart,
    remove_cart_item,
    update_cart_item_quantity,
)

User = get_user_model()


class CartModelTestMixin:
    def create_customer(self, username="customer"):
        user = User.objects.create_user(
            username=username,
            email=f"{username}@example.com",
            password="secure-password-123",
            role=Role.CUSTOMER,
            is_staff=False,
            is_superuser=False,
        )
        customer = Customer(
            user=user,
            registration_source=RegistrationSource.WEBSITE,
        )
        customer.full_clean()
        customer.save()
        return customer

    def create_address(self, **overrides):
        defaults = {
            "line1": "12 MG Road",
            "city": "Bengaluru",
            "state": "Karnataka",
            "postal_code": "560001",
            "latitude": Decimal("12.971600"),
            "longitude": Decimal("77.594600"),
        }
        defaults.update(overrides)
        return Address.objects.create(**defaults)

    def create_store(self, **overrides):
        if "address" not in overrides:
            overrides["address"] = self.create_address(
                line1=f"Store addr {Address.objects.count() + 1}"
            )
        if "category" not in overrides:
            overrides["category"] = StoreCategory.objects.create(
                name=f"Cat-{StoreCategory.objects.count() + 1}"
            )
        defaults = {
            "name": "Zoop Mart",
            "store_type": StoreType.OWN_STORE,
            "status": StoreStatus.ACTIVE,
            "is_active": True,
        }
        defaults.update(overrides)
        return Store.objects.create(**defaults)

    def create_product(self, store=None, *, stock=Decimal("10.000"), **overrides):
        store = store or self.create_store()
        if "category" not in overrides:
            overrides["category"] = ProductCategory.objects.create(
                name=f"PCat-{ProductCategory.objects.count() + 1}"
            )
        defaults = {
            "store": store,
            "name": "Sample Product",
            "sku": f"SKU-{Product.objects.count() + 1}",
            "store_price": Decimal("100.00"),
            "profit_margin_type": MarginType.FIXED,
            "profit_margin": Decimal("20.00"),
            "status": ProductStatus.APPROVED,
            "is_active": True,
            "unit": ProductUnit.PIECE,
            "unit_value": Decimal("1.000"),
        }
        defaults.update(overrides)
        product = Product(**defaults)
        product.full_clean()
        product.save()
        if stock and stock > 0:
            record_manual_stock_in(
                product=product,
                store=store,
                quantity=stock,
                actor=None,
                reason="Test stock",
            )
            product.refresh_from_db()
        return product

    def create_cart(self, customer=None):
        customer = customer or self.create_customer()
        cart = Cart(customer=customer)
        cart.full_clean()
        cart.save()
        return cart


class CartModelTests(CartModelTestMixin, TestCase):
    def test_cart_is_unique_per_customer(self):
        customer = self.create_customer(username="ada")
        self.create_cart(customer=customer)
        duplicate = Cart(customer=customer)
        with self.assertRaises(ValidationError):
            duplicate.full_clean()
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                duplicate.save()

    def test_cart_str_includes_customer_code(self):
        cart = self.create_cart(customer=self.create_customer(username="bob"))
        self.assertIn(cart.customer.customer_code, str(cart))

    def test_cart_item_unique_per_cart_and_product(self):
        cart = self.create_cart()
        product = self.create_product()
        CartItem.objects.create(cart=cart, product=product, quantity=Decimal("1.000"))
        duplicate = CartItem(
            cart=cart,
            product=product,
            quantity=Decimal("2.000"),
        )
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                duplicate.save()

    def test_cart_item_quantity_must_be_positive(self):
        cart = self.create_cart()
        product = self.create_product()
        item = CartItem(cart=cart, product=product, quantity=Decimal("0.000"))
        with self.assertRaises(ValidationError) as ctx:
            item.full_clean()
        self.assertIn("quantity", ctx.exception.message_dict)

        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                CartItem.objects.create(
                    cart=cart,
                    product=product,
                    quantity=Decimal("0.000"),
                )

    def test_cart_item_rejects_negative_quantity_constraint(self):
        cart = self.create_cart()
        product = self.create_product()
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                CartItem.objects.create(
                    cart=cart,
                    product=product,
                    quantity=Decimal("-1.000"),
                )

    def test_cart_item_str(self):
        cart = self.create_cart()
        product = self.create_product()
        item = CartItem.objects.create(
            cart=cart,
            product=product,
            quantity=Decimal("2.500"),
        )
        self.assertIn(product.product_code, str(item))
        self.assertIn("2.500", str(item))

    def test_cart_item_does_not_store_trusted_checkout_prices(self):
        field_names = {field.name for field in CartItem._meta.fields}
        sensitive = {
            "store_price",
            "final_price",
            "profit_margin",
            "selling_price",
        }
        self.assertFalse(field_names & sensitive)
        self.assertIn("unit_price_snapshot", field_names)

    def test_deleting_cart_cascades_items_only(self):
        cart = self.create_cart()
        product = self.create_product()
        CartItem.objects.create(cart=cart, product=product, quantity=Decimal("1.000"))
        cart_id = cart.pk
        cart.delete()
        self.assertFalse(Cart.objects.filter(pk=cart_id).exists())
        self.assertFalse(CartItem.objects.filter(cart_id=cart_id).exists())
        self.assertTrue(Product.objects.filter(pk=product.pk).exists())


class CartServiceTests(CartModelTestMixin, TestCase):
    def setUp(self):
        self.customer = self.create_customer(username="shopper")
        self.store_a = self.create_store(name="Alpha Store")
        self.store_b = self.create_store(name="Beta Store")
        self.product_a = self.create_product(
            store=self.store_a,
            name="Alpha Milk",
            sku="A-MILK",
        )
        self.product_b = self.create_product(
            store=self.store_b,
            name="Beta Bread",
            sku="B-BREAD",
        )

    def test_add_increases_quantity_for_existing_product(self):
        add_product_to_cart(
            customer=self.customer,
            product_code=self.product_a.product_code,
            quantity=Decimal("1.000"),
        )
        item = add_product_to_cart(
            customer=self.customer,
            product_code=self.product_a.product_code,
            quantity=Decimal("2.000"),
        )
        self.assertEqual(item.quantity, Decimal("3.000"))
        self.assertEqual(CartItem.objects.filter(cart__customer=self.customer).count(), 1)

    def test_add_rejects_zero_quantity_and_overstock(self):
        with self.assertRaises(ValidationError):
            add_product_to_cart(
                customer=self.customer,
                product_code=self.product_a.product_code,
                quantity=Decimal("0"),
            )
        with self.assertRaises(ValidationError):
            add_product_to_cart(
                customer=self.customer,
                product_code=self.product_a.product_code,
                quantity=Decimal("99.000"),
            )

    def test_add_rejects_unapproved_inactive_suspended_and_expired(self):
        self.product_a.status = ProductStatus.PENDING
        self.product_a.save(update_fields=["status", "updated_at"])
        with self.assertRaises(ValidationError):
            add_product_to_cart(
                customer=self.customer,
                product_code=self.product_a.product_code,
                quantity=Decimal("1"),
            )

        self.product_a.status = ProductStatus.APPROVED
        self.product_a.is_active = False
        self.product_a.save(update_fields=["status", "is_active", "updated_at"])
        with self.assertRaises(ValidationError):
            add_product_to_cart(
                customer=self.customer,
                product_code=self.product_a.product_code,
                quantity=Decimal("1"),
            )

        self.product_a.is_active = True
        self.product_a.save(update_fields=["is_active", "updated_at"])
        self.store_a.status = StoreStatus.SUSPENDED
        self.store_a.save(update_fields=["status", "updated_at"])
        with self.assertRaises(ValidationError):
            add_product_to_cart(
                customer=self.customer,
                product_code=self.product_a.product_code,
                quantity=Decimal("1"),
            )

    def test_cart_groups_by_store_and_warns_on_price_change(self):
        add_product_to_cart(
            customer=self.customer,
            product_code=self.product_a.product_code,
            quantity=Decimal("1"),
        )
        add_product_to_cart(
            customer=self.customer,
            product_code=self.product_b.product_code,
            quantity=Decimal("2"),
        )
        item = CartItem.objects.get(product=self.product_a)
        item.unit_price_snapshot = item.unit_price_snapshot + Decimal("5.00")
        item.save(update_fields=["unit_price_snapshot", "updated_at"])

        context = build_cart_view_context(self.customer)
        self.assertEqual(len(context["store_groups"]), 2)
        self.assertTrue(context["has_warnings"])
        names = {group["store_name"] for group in context["store_groups"]}
        self.assertEqual(names, {"Alpha Store", "Beta Store"})
        self.assertGreater(context["preview_subtotal"], Decimal("0"))

    def test_update_remove_and_clear(self):
        item = add_product_to_cart(
            customer=self.customer,
            product_code=self.product_a.product_code,
            quantity=Decimal("2"),
        )
        updated = update_cart_item_quantity(
            customer=self.customer,
            cart_item_id=item.pk,
            quantity=Decimal("1.500"),
        )
        self.assertEqual(updated.quantity, Decimal("1.500"))

        remove_cart_item(customer=self.customer, cart_item_id=item.pk)
        self.assertFalse(CartItem.objects.filter(pk=item.pk).exists())

        add_product_to_cart(
            customer=self.customer,
            product_code=self.product_b.product_code,
            quantity=Decimal("1"),
        )
        clear_cart(customer=self.customer)
        self.assertFalse(
            CartItem.objects.filter(cart__customer=self.customer).exists()
        )


class CartIsolationTests(CartModelTestMixin, TestCase):
    """Customer A must never read or mutate Customer B's cart items."""

    def setUp(self):
        self.client = Client(enforce_csrf_checks=True)

        self.customer_a, self.user_a = create_customer_with_user(
            user_data={
                "username": "cart-customer-a",
                "email": "cart-a@example.com",
                "first_name": "Alice",
                "last_name": "Cart",
                "phone_number": "9000000101",
                "password": "secure-password-123",
            },
            registration_source=RegistrationSource.WEBSITE,
        )
        self.customer_b, self.user_b = create_customer_with_user(
            user_data={
                "username": "cart-customer-b",
                "email": "cart-b@example.com",
                "first_name": "Bob",
                "last_name": "Cart",
                "phone_number": "9000000102",
                "password": "secure-password-123",
            },
            registration_source=RegistrationSource.WEBSITE,
        )

        self.store = self.create_store(name="Shared Mart")
        self.product = self.create_product(store=self.store, name="Shared Item")
        self.product_b_only = self.create_product(
            store=self.store,
            name="Bob Secret Item",
            sku="BOB-SECRET",
        )

        self.item_a = add_product_to_cart(
            customer=self.customer_a,
            product_code=self.product.product_code,
            quantity=Decimal("1.000"),
        )
        self.item_b = add_product_to_cart(
            customer=self.customer_b,
            product_code=self.product_b_only.product_code,
            quantity=Decimal("2.000"),
        )

        self.cart_url = reverse("cart:cart_detail")
        self.add_url = reverse(
            "cart:cart_add_item",
            kwargs={"product_code": self.product.product_code},
        )
        self.update_b_url = reverse(
            "cart:cart_update_item",
            kwargs={"pk": self.item_b.pk},
        )
        self.remove_b_url = reverse(
            "cart:cart_remove_item",
            kwargs={"pk": self.item_b.pk},
        )
        self.clear_url = reverse("cart:cart_clear")
        self.login_url = reverse("customers:customer_portal_login")
        self.dashboard_url = reverse("customers:customer_portal_dashboard")

        self.store_user = User.objects.create_user(
            username="cart-store-user",
            email="cart-store@example.com",
            password="secure-password-123",
            role=Role.STORE_USER,
        )

    def _csrf(self, url):
        return self.client.get(url).cookies["csrftoken"].value

    def _login(self, user):
        self.client.force_login(user)
        self.client.get(self.dashboard_url)

    def _post(self, url, payload=None, *, seed_url=None):
        token = self._csrf(seed_url or self.cart_url)
        data = dict(payload or {})
        data["csrfmiddlewaretoken"] = token
        return self.client.post(url, data)

    def test_customer_a_sees_only_own_cart(self):
        self._login(self.user_a)
        response = self.client.get(self.cart_url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Shared Item")
        self.assertNotContains(response, "Bob Secret Item")
        self.assertEqual(response.context["item_count"], 1)

        sneaky = self.client.get(
            self.cart_url,
            {
                "customer_id": self.customer_b.pk,
                "cart_id": self.customer_b.cart.pk,
            },
        )
        self.assertEqual(sneaky.status_code, 200)
        self.assertEqual(sneaky.context["item_count"], 1)
        self.assertNotContains(sneaky, "Bob Secret Item")

    def test_customer_a_cannot_update_or_remove_customer_b_item(self):
        self._login(self.user_a)

        update = self._post(self.update_b_url, {"quantity": "9.000"})
        self.assertEqual(update.status_code, 404)

        remove = self._post(self.remove_b_url, {})
        self.assertEqual(remove.status_code, 404)

        self.item_b.refresh_from_db()
        self.assertEqual(self.item_b.quantity, Decimal("2.000"))
        self.assertTrue(CartItem.objects.filter(pk=self.item_b.pk).exists())

    def test_manipulated_customer_id_and_cart_id_ignored_on_add(self):
        self._login(self.user_a)
        response = self._post(
            self.add_url,
            {
                "quantity": "1.000",
                "customer_id": self.customer_b.pk,
                "cart_id": self.customer_b.cart.pk,
            },
        )
        self.assertEqual(response.status_code, 302)

        self.item_a.refresh_from_db()
        self.assertEqual(self.item_a.quantity, Decimal("2.000"))
        self.assertEqual(
            CartItem.objects.filter(cart__customer=self.customer_b).count(),
            1,
        )
        self.assertFalse(
            CartItem.objects.filter(
                cart__customer=self.customer_b,
                product=self.product,
            ).exists()
        )

    def test_clear_only_clears_own_cart(self):
        self._login(self.user_a)
        response = self._post(
            self.clear_url,
            {"customer_id": self.customer_b.pk, "cart_id": self.customer_b.cart.pk},
        )
        self.assertEqual(response.status_code, 302)
        self.assertFalse(
            CartItem.objects.filter(cart__customer=self.customer_a).exists()
        )
        self.assertTrue(CartItem.objects.filter(pk=self.item_b.pk).exists())

    def test_update_remove_clear_require_post(self):
        self._login(self.user_a)
        update_a = reverse("cart:cart_update_item", kwargs={"pk": self.item_a.pk})
        remove_a = reverse("cart:cart_remove_item", kwargs={"pk": self.item_a.pk})
        self.assertEqual(self.client.get(update_a).status_code, 405)
        self.assertEqual(self.client.get(remove_a).status_code, 405)
        self.assertEqual(self.client.get(self.clear_url).status_code, 405)
        self.assertEqual(self.client.get(self.add_url).status_code, 405)

    def test_csrf_required_for_mutations(self):
        self._login(self.user_a)
        plain = Client(enforce_csrf_checks=True)
        plain.force_login(self.user_a)
        response = plain.post(
            reverse("cart:cart_update_item", kwargs={"pk": self.item_a.pk}),
            {"quantity": "3.000"},
        )
        self.assertEqual(response.status_code, 403)

    def test_anonymous_cart_redirects_to_login(self):
        response = self.client.get(self.cart_url)
        self.assertEqual(response.status_code, 302)
        self.assertIn("/customer/login/", response.url)

    def test_anonymous_add_returns_to_product_after_login(self):
        product_path = reverse(
            "catalog:public_product_detail",
            kwargs={"slug": self.product.slug},
        )
        token = self.client.get(product_path).cookies["csrftoken"].value
        response = self.client.post(
            self.add_url,
            {"quantity": "1", "csrfmiddlewaretoken": token},
        )
        self.assertEqual(response.status_code, 302)
        self.assertIn("/customer/login/", response["Location"])

        parsed = urlparse(response["Location"])
        next_path = parse_qs(parsed.query).get("next", [""])[0]
        self.assertEqual(next_path, product_path)

        token = self.client.get(response["Location"]).cookies["csrftoken"].value
        login_response = self.client.post(
            self.login_url,
            {
                "username": "cart-customer-a",
                "password": "secure-password-123",
                "next": next_path,
                "csrfmiddlewaretoken": token,
            },
        )
        self.assertEqual(login_response.status_code, 302)
        self.assertEqual(login_response.url, product_path)

    def test_store_user_cannot_access_customer_cart(self):
        self.client.force_login(self.store_user)
        self.assertEqual(self.client.get(self.cart_url).status_code, 403)
