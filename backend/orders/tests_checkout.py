from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.test import Client, TestCase
from django.urls import reverse

from accounts.models import Role
from cart.services import add_product_to_cart
from catalog.models import Product, ProductCategory, ProductStatus, ProductUnit
from catalog.pricing import MarginType
from customers.models import AddressLabel, RegistrationSource
from customers.services import create_customer_delivery_address, create_customer_with_user
from inventory.services import record_manual_stock_in
from locations.models import Address
from stores.models import Store, StoreCategory, StoreStatus, StoreType

from .models import FulfillmentType, Order, PaymentMethod, PickupLocation
from .services import (
    build_checkout_preview,
    get_owned_active_delivery_address,
    get_valid_pickup_location,
    place_order,
    validate_checkout_selections,
)

User = get_user_model()


class CheckoutTestMixin:
    def create_store(self, **overrides):
        if "address" not in overrides:
            overrides["address"] = Address.objects.create(
                line1=f"Store {Address.objects.count() + 1}",
                city="Bengaluru",
                state="Karnataka",
                postal_code="560001",
                latitude=Decimal("12.971600"),
                longitude=Decimal("77.594600"),
            )
        if "category" not in overrides:
            overrides["category"] = StoreCategory.objects.create(
                name=f"StoreCat-{StoreCategory.objects.count() + 1}"
            )
        defaults = {
            "name": f"Store {Store.objects.count() + 1}",
            "store_type": StoreType.OWN_STORE,
            "status": StoreStatus.ACTIVE,
            "is_active": True,
        }
        defaults.update(overrides)
        return Store.objects.create(**defaults)

    def create_public_product(self, store=None, *, stock=Decimal("10.000"), **overrides):
        store = store or self.create_store()
        if "category" not in overrides:
            overrides["category"] = ProductCategory.objects.create(
                name=f"PCat-{ProductCategory.objects.count() + 1}"
            )
        defaults = {
            "store": store,
            "name": f"Product {Product.objects.count() + 1}",
            "sku": f"CHK-{Product.objects.count() + 1}",
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
                reason="Checkout test stock",
            )
            product.refresh_from_db()
        return product

    def create_pickup(self, store, **overrides):
        defaults = {
            "store": store,
            "name": "Main Counter",
            "code": f"PK-{PickupLocation.objects.count() + 1}",
            "address": Address.objects.create(
                line1=f"Pickup {Address.objects.count() + 1}",
                city="Bengaluru",
                state="Karnataka",
                postal_code="560001",
                latitude=Decimal("12.971600"),
                longitude=Decimal("77.594600"),
            ),
            "contact_phone": "9000000000",
            "hours": "Mon–Sat 9:00–20:00",
            "instructions": "Collect from counter",
            "is_active": True,
        }
        defaults.update(overrides)
        location = PickupLocation(**defaults)
        location.full_clean()
        location.save()
        return location


class CheckoutServiceTests(CheckoutTestMixin, TestCase):
    def setUp(self):
        self.customer, self.user = create_customer_with_user(
            user_data={
                "username": "checkout-customer",
                "email": "checkout@example.com",
                "first_name": "Check",
                "last_name": "Out",
                "phone_number": "9000000201",
                "password": "secure-password-123",
            },
            registration_source=RegistrationSource.WEBSITE,
        )
        self.store = self.create_store(name="Checkout Mart")
        self.product = self.create_public_product(store=self.store, name="Checkout Milk")
        self.address = create_customer_delivery_address(
            customer=self.customer,
            data={
                "label": AddressLabel.HOME,
                "recipient_name": "Check Out",
                "phone_number": "9000000201",
                "line1": "10 Checkout Street",
                "line2": "",
                "landmark": "",
                "city": "Bengaluru",
                "district": "",
                "state": "Karnataka",
                "postal_code": "560001",
                "latitude": "12.971600",
                "longitude": "77.594600",
                "delivery_instructions": "",
                "is_default": True,
            },
        )
        self.pickup = self.create_pickup(self.store)
        add_product_to_cart(
            customer=self.customer,
            product_code=self.product.product_code,
            quantity=Decimal("2.000"),
        )

    def test_preview_recalculates_subtotal_from_final_price(self):
        preview = build_checkout_preview(self.customer)
        self.assertFalse(preview["is_empty"])
        self.assertEqual(len(preview["store_groups"]), 1)
        expected = (self.product.final_price * Decimal("2.000")).quantize(
            Decimal("0.01")
        )
        self.assertEqual(preview["items_subtotal"], expected)
        self.assertEqual(preview["grand_total"], expected)
        row = preview["store_groups"][0]["items"][0]
        self.assertEqual(row["unit_price"], self.product.final_price)
        self.assertEqual(row["line_total"], expected)

    def test_rejects_other_customers_delivery_address(self):
        other, _user = create_customer_with_user(
            user_data={
                "username": "other-checkout",
                "email": "other-checkout@example.com",
                "first_name": "Other",
                "last_name": "Customer",
                "phone_number": "9000000202",
                "password": "secure-password-123",
            },
            registration_source=RegistrationSource.WEBSITE,
        )
        other_address = create_customer_delivery_address(
            customer=other,
            data={
                "label": AddressLabel.HOME,
                "recipient_name": "Other",
                "phone_number": "9000000202",
                "line1": "99 Secret Lane",
                "line2": "",
                "landmark": "",
                "city": "Mysuru",
                "district": "",
                "state": "Karnataka",
                "postal_code": "570001",
                "latitude": "12.295800",
                "longitude": "76.639400",
                "delivery_instructions": "",
                "is_default": True,
            },
        )
        with self.assertRaises(ValidationError) as ctx:
            get_owned_active_delivery_address(
                customer=self.customer,
                address_id=other_address.pk,
            )
        self.assertIn("delivery_address_id", ctx.exception.message_dict)

        with self.assertRaises(ValidationError):
            validate_checkout_selections(
                customer=self.customer,
                fulfillment_type=FulfillmentType.DELIVERY,
                payment_method=PaymentMethod.COD,
                delivery_address_id=other_address.pk,
            )

    def test_rejects_inactive_and_wrong_store_pickup_locations(self):
        inactive = self.create_pickup(
            self.store,
            name="Closed Desk",
            code="PK-CLOSED",
            is_active=False,
        )
        other_store = self.create_store(name="Other Store")
        foreign = self.create_pickup(other_store, name="Foreign Desk", code="PK-FOREIGN")

        with self.assertRaises(ValidationError):
            get_valid_pickup_location(
                store_id=self.store.pk,
                pickup_location_id=inactive.pk,
            )
        with self.assertRaises(ValidationError):
            get_valid_pickup_location(
                store_id=self.store.pk,
                pickup_location_id=foreign.pk,
            )

        with self.assertRaises(ValidationError):
            validate_checkout_selections(
                customer=self.customer,
                fulfillment_type=FulfillmentType.FACILITY_PICKUP,
                payment_method=PaymentMethod.PAY_AT_PICKUP,
                pickup_post_data={f"pickup_location_{self.store.pk}": inactive.pk},
            )
        with self.assertRaises(ValidationError):
            validate_checkout_selections(
                customer=self.customer,
                fulfillment_type=FulfillmentType.FACILITY_PICKUP,
                payment_method=PaymentMethod.PAY_AT_PICKUP,
                pickup_post_data={f"pickup_location_{self.store.pk}": foreign.pk},
            )

    def test_place_delivery_order_ignores_forged_customer_and_totals(self):
        order = place_order(
            customer=self.customer,
            checkout_token="token-delivery-1",
            fulfillment_type=FulfillmentType.DELIVERY,
            payment_method=PaymentMethod.COD,
            delivery_address_id=self.address.pk,
            customer_notes="Leave at door",
            actor=self.user,
        )
        self.assertEqual(order.customer_id, self.customer.pk)
        self.assertEqual(order.payment_method, PaymentMethod.COD)
        self.assertEqual(order.payment_status, "PENDING")
        self.assertEqual(order.delivery_line1, "10 Checkout Street")
        expected = (self.product.final_price * Decimal("2.000")).quantize(
            Decimal("0.01")
        )
        self.assertEqual(order.items_subtotal, expected)
        self.assertEqual(order.grand_total, expected)
        self.product.refresh_from_db()
        self.assertEqual(self.product.stock_quantity, Decimal("8.000"))
        from cart.models import CartItem

        self.assertFalse(
            CartItem.objects.filter(cart__customer=self.customer).exists()
        )


class CheckoutViewIsolationTests(CheckoutTestMixin, TestCase):
    def setUp(self):
        self.client = Client(enforce_csrf_checks=True)
        self.customer_a, self.user_a = create_customer_with_user(
            user_data={
                "username": "chk-a",
                "email": "chk-a@example.com",
                "first_name": "Alice",
                "last_name": "A",
                "phone_number": "9000000301",
                "password": "secure-password-123",
            },
            registration_source=RegistrationSource.WEBSITE,
        )
        self.customer_b, self.user_b = create_customer_with_user(
            user_data={
                "username": "chk-b",
                "email": "chk-b@example.com",
                "first_name": "Bob",
                "last_name": "B",
                "phone_number": "9000000302",
                "password": "secure-password-123",
            },
            registration_source=RegistrationSource.WEBSITE,
        )
        self.store = self.create_store(name="View Mart")
        self.product = self.create_public_product(store=self.store, name="View Item")
        self.pickup = self.create_pickup(self.store)
        self.address_a = create_customer_delivery_address(
            customer=self.customer_a,
            data={
                "label": AddressLabel.HOME,
                "recipient_name": "Alice A",
                "phone_number": "9000000301",
                "line1": "1 Alice Road",
                "line2": "",
                "landmark": "",
                "city": "Bengaluru",
                "district": "",
                "state": "Karnataka",
                "postal_code": "560001",
                "latitude": "12.971600",
                "longitude": "77.594600",
                "delivery_instructions": "",
                "is_default": True,
            },
        )
        self.address_b = create_customer_delivery_address(
            customer=self.customer_b,
            data={
                "label": AddressLabel.HOME,
                "recipient_name": "Bob Secret",
                "phone_number": "9000000302",
                "line1": "99 Bob Secret",
                "line2": "",
                "landmark": "",
                "city": "Mysuru",
                "district": "",
                "state": "Karnataka",
                "postal_code": "570001",
                "latitude": "12.295800",
                "longitude": "76.639400",
                "delivery_instructions": "",
                "is_default": True,
            },
        )
        add_product_to_cart(
            customer=self.customer_a,
            product_code=self.product.product_code,
            quantity=Decimal("1.000"),
        )

    def _csrf(self, url):
        return self.client.get(url).cookies["csrftoken"].value








class CheckoutAddressGateTests(CheckoutTestMixin, TestCase):
    def setUp(self):
        self.client = Client()
        self.customer, self.user = create_customer_with_user(
            user_data={
                "username": "no-address-customer",
                "email": "no-address@example.com",
                "first_name": "No",
                "last_name": "Address",
                "phone_number": "9000000401",
                "password": "secure-password-123",
            },
            registration_source=RegistrationSource.WEBSITE,
        )
        self.store = self.create_store(name="Gate Mart")
        self.product = self.create_public_product(store=self.store, name="Gate Item")
        add_product_to_cart(
            customer=self.customer,
            product_code=self.product.product_code,
            quantity=Decimal("1.000"),
        )



