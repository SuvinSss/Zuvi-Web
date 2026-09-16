from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.test import Client, TestCase
from django.urls import reverse

from accounts.models import Role
from cart.services import add_product_to_cart
from catalog.models import Product, ProductCategory, ProductStatus, ProductUnit
from catalog.pricing import MarginType
from customers.models import AddressLabel, CustomerAddress, RegistrationSource
from customers.services import create_customer_delivery_address, create_customer_with_user
from inventory.models import InventoryTransaction
from inventory.services import record_manual_stock_in
from locations.models import Address
from stores.models import Store, StoreCategory, StoreStatus, StoreType

from .models import FulfillmentType, Order, OrderItem, PaymentMethod, PaymentStatus, PickupLocation, StoreOrder
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
        self.preview_url = reverse("orders:checkout_preview")
        self.place_url = reverse("orders:checkout_place")
        self.dashboard_url = reverse("customers:customer_portal_dashboard")

    def _csrf(self, url):
        return self.client.get(url).cookies["csrftoken"].value

    def _login(self, user):
        self.client.force_login(user)
        self.client.get(self.dashboard_url)

    def test_preview_shows_own_addresses_and_issues_token(self):
        self._login(self.user_a)
        response = self.client.get(self.preview_url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "View Item")
        self.assertContains(response, "1 Alice Road")
        self.assertNotContains(response, "99 Bob Secret")
        self.assertContains(response, "checkout_token")
        self.assertContains(response, "Cash on Delivery")
        self.assertContains(
            response,
            "Delivery eligibility will be confirmed based on your location",
        )
        self.assertIn("checkout_token", self.client.session)

    def test_cannot_place_with_other_customers_address(self):
        self._login(self.user_a)
        preview = self.client.get(self.preview_url)
        token = preview.context["checkout_token"]
        csrf = preview.cookies["csrftoken"].value
        response = self.client.post(
            self.place_url,
            {
                "csrfmiddlewaretoken": csrf,
                "checkout_token": token,
                "fulfillment_type": FulfillmentType.DELIVERY,
                "payment_method": PaymentMethod.COD,
                "delivery_address_id": self.address_b.pk,
                "customer_id": self.customer_b.pk,
                "items_subtotal": "1.00",
                "grand_total": "1.00",
            },
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(Order.objects.count(), 0)

    def test_rejects_invalid_pickup_location_on_place(self):
        self._login(self.user_a)
        preview = self.client.get(self.preview_url)
        token = preview.context["checkout_token"]
        csrf = preview.cookies["csrftoken"].value

        other_store = self.create_store(name="Foreign")
        foreign_pickup = self.create_pickup(other_store, code="PK-X")

        response = self.client.post(
            self.place_url,
            {
                "csrfmiddlewaretoken": csrf,
                "checkout_token": token,
                "fulfillment_type": FulfillmentType.FACILITY_PICKUP,
                "payment_method": PaymentMethod.PAY_AT_PICKUP,
                f"pickup_location_{self.store.pk}": foreign_pickup.pk,
            },
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(Order.objects.count(), 0)

    def test_place_requires_post_and_csrf(self):
        self._login(self.user_a)
        self.assertEqual(self.client.get(self.place_url).status_code, 405)
        plain = Client(enforce_csrf_checks=True)
        plain.force_login(self.user_a)
        response = plain.post(
            self.place_url,
            {
                "checkout_token": "x",
                "fulfillment_type": FulfillmentType.DELIVERY,
                "payment_method": PaymentMethod.COD,
                "delivery_address_id": self.address_a.pk,
            },
        )
        self.assertEqual(response.status_code, 403)

    def test_successful_delivery_place(self):
        self._login(self.user_a)
        preview = self.client.get(self.preview_url)
        token = preview.context["checkout_token"]
        csrf = preview.cookies["csrftoken"].value
        response = self.client.post(
            self.place_url,
            {
                "csrfmiddlewaretoken": csrf,
                "checkout_token": token,
                "fulfillment_type": FulfillmentType.DELIVERY,
                "payment_method": PaymentMethod.COD,
                "delivery_address_id": self.address_a.pk,
                "customer_notes": "Ring bell",
            },
        )
        self.assertEqual(response.status_code, 302)
        order = Order.objects.get()
        self.assertEqual(
            response.url,
            reverse(
                "orders:customer_order_detail",
                kwargs={"order_number": order.order_number},
            ),
        )
        self.assertEqual(order.customer_id, self.customer_a.pk)
        self.assertEqual(order.delivery_line1, "1 Alice Road")
        self.assertEqual(order.customer_notes, "Ring bell")
        self.assertNotIn("checkout_token", self.client.session)

    def test_successful_pickup_place(self):
        self._login(self.user_a)
        preview = self.client.get(self.preview_url)
        token = preview.context["checkout_token"]
        csrf = preview.cookies["csrftoken"].value
        response = self.client.post(
            self.place_url,
            {
                "csrfmiddlewaretoken": csrf,
                "checkout_token": token,
                "fulfillment_type": FulfillmentType.FACILITY_PICKUP,
                "payment_method": PaymentMethod.PAY_AT_PICKUP,
                f"pickup_location_{self.store.pk}": self.pickup.pk,
            },
        )
        self.assertEqual(response.status_code, 302)
        order = Order.objects.get()
        self.assertEqual(order.fulfillment_type, FulfillmentType.FACILITY_PICKUP)
        self.assertEqual(order.payment_method, PaymentMethod.PAY_AT_PICKUP)
        store_order = order.store_orders.get()
        self.assertEqual(store_order.pickup_location_id, self.pickup.pk)


class CheckoutAddressGateTests(CheckoutTestMixin, TestCase):
    def setUp(self):
        self.client = Client(enforce_csrf_checks=True)
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
        self.pickup = self.create_pickup(self.store)
        add_product_to_cart(
            customer=self.customer,
            product_code=self.product.product_code,
            quantity=Decimal("1.000"),
        )
        self.preview_url = reverse("orders:checkout_preview")
        self.place_url = reverse("orders:checkout_place")
        self.dashboard_url = reverse("customers:customer_portal_dashboard")

    def _login(self):
        self.client.force_login(self.user)
        self.client.get(self.dashboard_url)

    def _pickup_data(self, preview, **changes):
        data = {
            "csrfmiddlewaretoken": self.client.cookies["csrftoken"].value,
            "checkout_token": preview.context["checkout_token"],
            "fulfillment_type": FulfillmentType.FACILITY_PICKUP,
            "payment_method": PaymentMethod.PAY_AT_PICKUP,
            f"pickup_location_{self.store.pk}": self.pickup.pk,
            "customer_notes": "Synthetic collection note",
        }
        data.update(changes)
        return data

    def _assert_no_order_effects(self, inventory_before):
        self.assertEqual(Order.objects.count(), 0)
        self.assertEqual(StoreOrder.objects.count(), 0)
        self.assertEqual(OrderItem.objects.count(), 0)
        self.assertEqual(InventoryTransaction.objects.count(), inventory_before)
        self.product.refresh_from_db()
        self.assertEqual(self.product.stock_quantity, Decimal("10.000"))
        preview = build_checkout_preview(self.customer)
        self.assertFalse(preview["is_empty"])
        self.assertEqual(preview["item_count"], 1)

    def _create_address(self, customer=None):
        return create_customer_delivery_address(
            customer=customer or self.customer,
            data={
                "label": AddressLabel.HOME, "recipient_name": "Synthetic recipient",
                "phone_number": "9000000401", "line1": "Synthetic delivery address",
                "city": "Test", "state": "Test", "postal_code": "560001",
                "latitude": "12.971600", "longitude": "77.594600",
                "is_default": True,
            },
        )

    def test_addressless_preview_offers_pickup_and_delivery_warning(self):
        self._login()
        response = self.client.get(self.preview_url)
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "orders/checkout.html")
        self.assertTrue(response.context["checkout_token"])
        self.assertIn("checkout_token", self.client.session)
        self.assertEqual(response.context["selected_fulfillment"], FulfillmentType.DELIVERY)
        self.assertEqual(response.context["selected_payment"], PaymentMethod.COD)
        self.assertContains(response, "Facility pickup")
        for detail in (self.pickup.name, str(self.pickup.address), self.pickup.hours,
                       self.pickup.instructions, "You have no active delivery addresses.",
                       "before placing a delivery order."):
            self.assertContains(response, detail)
        self.assertEqual(CustomerAddress.objects.count(), 0)

    def test_addressless_pickup_creates_once_without_delivery_address(self):
        self._login()
        preview = self.client.get(self.preview_url)
        before = InventoryTransaction.objects.count()
        data = self._pickup_data(preview, grand_total="0.01", customer_id="999999",
                                 delivery_address_id="999999")
        response = self.client.post(self.place_url, data)
        order = Order.objects.get()
        self.assertRedirects(response, reverse("orders:customer_order_detail",
                             kwargs={"order_number": order.order_number}))
        self.assertEqual(order.customer_id, self.customer.pk)
        self.assertEqual(order.fulfillment_type, FulfillmentType.FACILITY_PICKUP)
        self.assertEqual(order.payment_method, PaymentMethod.PAY_AT_PICKUP)
        self.assertEqual(order.payment_status, PaymentStatus.PENDING)
        self.assertEqual(order.grand_total, self.product.final_price)
        self.assertIsNone(order.delivery_address_id)
        self.assertIsNone(order.delivery_latitude)
        self.assertIsNone(order.delivery_longitude)
        for field in ("recipient_name", "phone_number", "line1", "line2", "landmark",
                      "city", "district", "state", "postal_code", "country", "instructions"):
            self.assertEqual(getattr(order, f"delivery_{field}"), "")
        self.assertEqual(CustomerAddress.objects.count(), 0)
        store_order = order.store_orders.get()
        self.assertEqual(store_order.store_id, self.store.pk)
        self.assertEqual(store_order.pickup_location_id, self.pickup.pk)
        self.assertEqual(OrderItem.objects.count(), 1)
        self.product.refresh_from_db()
        self.assertEqual(self.product.stock_quantity, Decimal("9.000"))
        self.assertEqual(InventoryTransaction.objects.count(), before + 1)
        self.client.post(self.place_url, data)
        self.assertEqual(Order.objects.count(), 1)
        self.assertEqual(StoreOrder.objects.count(), 1)
        self.assertEqual(OrderItem.objects.count(), 1)
        self.assertEqual(InventoryTransaction.objects.count(), before + 1)

    def test_addressless_delivery_is_rejected_without_order_effects(self):
        self._login()
        preview = self.client.get(self.preview_url)
        before = InventoryTransaction.objects.count()
        response = self.client.post(self.place_url, self._pickup_data(preview,
            fulfillment_type=FulfillmentType.DELIVERY, payment_method=PaymentMethod.COD), follow=True)
        self.assertEqual(response.redirect_chain, [(self.preview_url, 302)])
        self.assertContains(response, "Select a delivery address.")
        self.assertEqual(response.context["selected_fulfillment"], FulfillmentType.DELIVERY)
        self._assert_no_order_effects(before)

    def test_switch_to_delivery_requires_address_and_cod(self):
        self._login()
        preview = self.client.get(self.preview_url)
        before = InventoryTransaction.objects.count()
        # Start with a failed pickup attempt, then change its recovered mode.
        response = self.client.post(self.place_url, self._pickup_data(preview,
            **{f"pickup_location_{self.store.pk}": ""}), follow=True)
        self.assertEqual(response.context["selected_fulfillment"], FulfillmentType.FACILITY_PICKUP)
        response = self.client.post(self.place_url, self._pickup_data(response,
            fulfillment_type=FulfillmentType.DELIVERY), follow=True)
        self.assertContains(response, "Select a delivery address.")
        self.assertContains(response, "Cash on Delivery is required for delivery orders.")
        self._assert_no_order_effects(before)
        address = self._create_address()
        response = self.client.post(self.place_url, self._pickup_data(response,
            fulfillment_type=FulfillmentType.DELIVERY, delivery_address_id=address.pk), follow=True)
        self.assertContains(response, "Cash on Delivery is required for delivery orders.")
        self._assert_no_order_effects(before)
        response = self.client.post(self.place_url, self._pickup_data(response,
            fulfillment_type=FulfillmentType.DELIVERY, delivery_address_id=address.pk,
            payment_method=PaymentMethod.COD))
        self.assertEqual(response.status_code, 302)
        order = Order.objects.get()
        self.assertEqual(order.delivery_address_id, address.pk)
        self.assertEqual(order.payment_method, PaymentMethod.COD)
        self.assertEqual(order.payment_status, PaymentStatus.PENDING)
        self.assertEqual(order.grand_total, self.product.final_price)
        self.assertIsNone(order.store_orders.get().pickup_location_id)
        self.assertEqual(InventoryTransaction.objects.count(), before + 1)

    def test_invalid_delivery_addresses_remain_rejected(self):
        other_customer, _ = create_customer_with_user(user_data={
            "username": "gate-other", "email": "gate-other@example.invalid",
            "first_name": "Synthetic", "last_name": "Other", "phone_number": "9000000402",
            "password": "test-password-only-123",
        }, registration_source=RegistrationSource.WEBSITE)
        foreign = self._create_address(other_customer)
        inactive = self._create_address()
        inactive.is_active = False
        inactive.save(update_fields=["is_active"])
        self._login()
        before = InventoryTransaction.objects.count()
        for address_id in (foreign.pk, inactive.pk, 99999999, "malformed"):
            with self.subTest(address=address_id):
                preview = self.client.get(self.preview_url)
                response = self.client.post(self.place_url, self._pickup_data(preview,
                    fulfillment_type=FulfillmentType.DELIVERY, payment_method=PaymentMethod.COD,
                    delivery_address_id=address_id), follow=True)
                self.assertEqual(response.redirect_chain, [(self.preview_url, 302)])
                self.assertTrue(response.context["recovering_checkout"])
                self.assertIsNone(response.context["selected_address_id"])
                self._assert_no_order_effects(before)

    def test_addressless_invalid_pickups_have_no_order_effects(self):
        inactive = self.create_pickup(self.store, is_active=False)
        foreign = self.create_pickup(self.create_store())
        self._login()
        before = InventoryTransaction.objects.count()
        for point_id in ("", inactive.pk, 99999999, "malformed", foreign.pk):
            with self.subTest(pickup=point_id):
                preview = self.client.get(self.preview_url)
                response = self.client.post(self.place_url, self._pickup_data(preview,
                    **{f"pickup_location_{self.store.pk}": point_id}), follow=True)
                self.assertEqual(response.redirect_chain, [(self.preview_url, 302)])
                self.assertContains(response, "Choose an available collection point")
                self._assert_no_order_effects(before)
                self.assertEqual(CustomerAddress.objects.count(), 0)

    def test_can_reach_checkout_once_address_exists(self):
        create_customer_delivery_address(
            customer=self.customer,
            data={
                "label": AddressLabel.HOME,
                "recipient_name": "No Address",
                "phone_number": "9000000401",
                "line1": "1 Gate Road",
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
        self._login()
        response = self.client.get(self.preview_url)
        self.assertEqual(response.status_code, 200)
        self.assertIn("checkout_token", self.client.session)


class CheckoutRecoveryTests(CheckoutTestMixin, TestCase):
    """Presentation and one-redirect recovery use existing commerce services."""

    def setUp(self):
        CheckoutViewIsolationTests.setUp(self)
        self.store.name = "INTERNAL-MERCHANT-ALPHA-73"
        self.store.save(update_fields=["name"])
        self.other_store = self.create_store(name="INTERNAL-MERCHANT-BETA-91")
        self.other_product = self.create_public_product(
            store=self.other_store, name="Synthetic Notebook", stock=Decimal("10")
        )
        add_product_to_cart(
            customer=self.customer_a, product_code=self.other_product.product_code,
            quantity=Decimal("2"),
        )
        self.selected = self.create_pickup(
            self.store, name="Z East Collection Counter", instructions="Use the east entrance"
        )
        self.other_pickup = self.create_pickup(
            self.other_store, name="West Collection Counter", instructions="Use the west entrance"
        )
        self.client.force_login(self.user_a)
        self.note = '<script>alert("synthetic")</script> Collect after lunch & call.'

    def _data(self, preview, **changes):
        data = {
            "csrfmiddlewaretoken": self.client.cookies["csrftoken"].value,
            "checkout_token": preview.context["checkout_token"],
            "fulfillment_type": FulfillmentType.FACILITY_PICKUP,
            "payment_method": PaymentMethod.PAY_AT_PICKUP,
            f"pickup_location_{self.store.pk}": str(self.selected.pk),
            "customer_notes": self.note,
        }
        data.update(changes)
        return data

    def _inputs(self, response):
        from html.parser import HTMLParser
        class Inputs(HTMLParser):
            def __init__(self):
                super().__init__()
                self.values = []
            def handle_starttag(self, tag, attrs):
                if tag == "input":
                    self.values.append(dict(attrs))
        parser = Inputs()
        parser.feed(response.content.decode())
        return parser.values

    def _checked(self, response, name):
        return [field.get("value") for field in self._inputs(response)
                if field.get("name") == name and "checked" in field]

    def _inventory_count(self):
        from inventory.models import InventoryTransaction
        return InventoryTransaction.objects.count()

    def test_hidden_markup_has_neutral_groups_and_preserves_collection_information(self):
        import re
        response = self.client.get(self.preview_url)
        for name in (self.store.name, self.other_store.name):
            self.assertNotContains(response, name)
        self.assertNotContains(response, "for each store")
        self.assertNotContains(response, "for this store")
        self.assertContains(response, 'id="pickup-panel" class="d-none"')
        groups = re.findall(r"<fieldset\b.*?</fieldset>", response.content.decode(), re.S)
        self.assertEqual(len(groups), 2)
        for store, product, quantity, locations in (
            (self.store, self.product, "1.000", [self.pickup, self.selected]),
            (self.other_store, self.other_product, "2.000", [self.other_pickup]),
        ):
            group = next(g for g in groups if f'name="pickup_location_{store.pk}"' in g)
            self.assertIn(product.name, group)
            self.assertIn(f"Qty: {quantity}", group)
            other = self.other_product if product == self.product else self.product
            self.assertNotIn(other.name, group)
            for pickup in locations:
                for text in (pickup.name, str(pickup.address), pickup.contact_phone,
                             pickup.hours, pickup.instructions,
                             f'id="pickup-{pickup.pk}"', f'for="pickup-{pickup.pk}"',
                             f'value="{pickup.pk}"'):
                    self.assertIn(text, group)
        self.assertEqual(self._checked(response, f"pickup_location_{self.store.pk}"), [str(self.pickup.pk)])
        # A real collection name must not be erased just because it names a shop.
        self.selected.name = self.store.name + " shop counter"
        self.selected.save(update_fields=["name"])
        response = self.client.get(self.preview_url)
        self.assertContains(response, self.selected.name)
        self.assertEqual(response.content.decode().count(self.store.name), 1)

    def test_missing_group_preserves_valid_choice_then_correction_creates_once(self):
        self._check_missing_group_recovery()

    def test_addressless_multistore_recovery_then_pickup_creates_once(self):
        CustomerAddress.objects.filter(customer=self.customer_a).delete()
        address_count = CustomerAddress.objects.count()
        self._check_missing_group_recovery()
        order = Order.objects.get()
        self.assertIsNone(order.delivery_address_id)
        self.assertEqual(order.delivery_line1, "")
        self.assertEqual(order.payment_status, PaymentStatus.PENDING)
        self.assertEqual(order.store_orders.count(), 2)
        self.assertEqual(OrderItem.objects.count(), 2)
        self.assertEqual(CustomerAddress.objects.count(), address_count)
        self.assertFalse(CustomerAddress.objects.filter(customer=self.customer_a).exists())

    def _check_missing_group_recovery(self):
        preview = self.client.get(self.preview_url)
        data = self._data(preview)
        before = self._inventory_count()
        response = self.client.post(self.place_url, data, follow=True)
        self.assertEqual(response.redirect_chain, [(self.preview_url, 302)])
        self.assertNotContains(response, "for each store")
        self.assertNotContains(response, "for this store")
        self.assertEqual(Order.objects.count(), 0)
        self.assertEqual(self._inventory_count(), before)
        self.assertEqual(self._checked(response, "fulfillment_type"), ["FACILITY_PICKUP"])
        self.assertEqual(self._checked(response, "payment_method"), ["PAY_AT_PICKUP"])
        self.assertEqual(self._checked(response, f"pickup_location_{self.store.pk}"), [str(self.selected.pk)])
        self.assertEqual(self._checked(response, f"pickup_location_{self.other_store.pk}"), [])
        self._assert_collection_focus_contract(response, {self.other_store.pk})
        self.assertContains(response, "Choose an available collection point for these items")
        from django.utils.html import escape
        self.assertContains(response, escape(self.note))
        self.assertNotContains(response, self.note)
        self.assertNotIn("checkout_recovery", self.client.session)
        self.assertNotEqual(response.context["checkout_token"], data["checkout_token"])
        corrected = self._data(response, **{
            f"pickup_location_{self.other_store.pk}": str(self.other_pickup.pk),
            "grand_total": "0.01", "customer_id": self.customer_b.pk,
        })
        done = self.client.post(self.place_url, corrected)
        self.assertEqual(done.status_code, 302)
        order = Order.objects.get()
        self.assertEqual(order.customer_id, self.customer_a.pk)
        self.assertEqual(order.customer_notes, self.note)
        self.assertEqual(order.payment_method, PaymentMethod.PAY_AT_PICKUP)
        self.assertEqual(order.grand_total, self.product.final_price + self.other_product.final_price * 2)
        self.assertEqual(order.store_orders.get(store=self.store).pickup_location_id, self.selected.pk)
        self.assertEqual(order.store_orders.get(store=self.other_store).pickup_location_id, self.other_pickup.pk)
        self.assertEqual(self._inventory_count() - before, 2)
        self.product.refresh_from_db(); self.other_product.refresh_from_db()
        self.assertEqual(self.product.stock_quantity, Decimal("9"))
        self.assertEqual(self.other_product.stock_quantity, Decimal("8"))
        self.assertNotIn("checkout_recovery", self.client.session)
        self.assertNotIn("checkout_token", self.client.session)
        self.client.post(self.place_url, corrected)
        self.assertEqual(Order.objects.count(), 1)
        self.assertEqual(self._inventory_count() - before, 2)

    def test_invalid_and_forged_choices_do_not_default_or_create_partial_orders(self):
        inactive = self.create_pickup(self.other_store, name="Inactive point", is_active=False)
        for invalid in (str(self.selected.pk), str(inactive.pk), "99999999", "forged", ""):
            with self.subTest(choice=invalid):
                preview = self.client.get(self.preview_url)
                before = self._inventory_count()
                data = self._data(preview, **{
                    f"pickup_location_{self.other_store.pk}": invalid,
                    "pickup_location_999999": str(self.other_pickup.pk),
                    "customer_id": self.customer_b.pk, "stock_quantity": "999",
                })
                response = self.client.post(self.place_url, data, follow=True)
                self.assertEqual(Order.objects.count(), 0)
                self.assertEqual(self._inventory_count(), before)
                self.assertEqual(self._checked(response, f"pickup_location_{self.store.pk}"), [str(self.selected.pk)])
                self.assertEqual(self._checked(response, f"pickup_location_{self.other_store.pk}"), [])

    def test_point_becoming_inactive_is_revalidated_on_redisplay_and_resubmit(self):
        preview = self.client.get(self.preview_url)
        data = self._data(preview)
        self.client.post(self.place_url, data)
        self.selected.is_active = False
        self.selected.save(update_fields=["is_active"])
        response = self.client.get(self.preview_url)
        self.assertEqual(self._checked(response, f"pickup_location_{self.store.pk}"), [])
        self.assertNotContains(response, self.selected.name)
        # It was valid in the previous page, but remains invalid at resubmission.
        stale = self._data(response, **{f"pickup_location_{self.other_store.pk}": self.other_pickup.pk})
        before = self._inventory_count()
        self.client.post(self.place_url, stale)
        self.assertEqual(Order.objects.count(), 0)
        self.assertEqual(self._inventory_count(), before)

    def test_changed_cart_groups_keep_only_current_choices(self):
        from cart.models import CartItem
        preview = self.client.get(self.preview_url)
        self.client.post(self.place_url, self._data(preview))
        CartItem.objects.filter(cart__customer=self.customer_a, product=self.other_product).delete()
        third_store = self.create_store(name="INTERNAL-THIRD")
        third_product = self.create_public_product(store=third_store, name="Newly added item")
        third_pickup = self.create_pickup(third_store, name="New counter")
        add_product_to_cart(customer=self.customer_a, product_code=third_product.product_code, quantity=Decimal("1"))
        response = self.client.get(self.preview_url)
        self.assertNotContains(response, f'name="pickup_location_{self.other_store.pk}"')
        self.assertEqual(self._checked(response, f"pickup_location_{self.store.pk}"), [str(self.selected.pk)])
        self.assertEqual(self._checked(response, f"pickup_location_{third_store.pk}"), [])
        self.assertContains(response, third_pickup.name)

    def test_recovery_is_allowlisted_json_scoped_and_consumed_once(self):
        import json
        preview = self.client.get(self.preview_url)
        session = self.client.session
        session["unrelated"] = "keep"
        session["delivery_location"] = {"label": "Synthetic existing location"}
        session.save()
        self.client.post(self.place_url, self._data(preview, password="never-retain", grand_total="1", permissions="all"))
        state = self.client.session["checkout_recovery"]
        self.assertEqual(set(state), {"customer_id", "cart_id", "token", "created_at", "fulfillment", "payment", "pickup_ids", "address_id", "note"})
        self.assertNotIn("never-retain", json.dumps(state))
        self.assertEqual(state["customer_id"], self.customer_a.pk)
        first = self.client.get(self.preview_url)
        self.assertEqual(first.context["customer_notes"], self.note)
        self.assertNotIn("checkout_recovery", self.client.session)
        fresh = self.client.get(self.preview_url)
        self.assertEqual(fresh.context["customer_notes"], "")
        self.assertEqual(self._checked(fresh, "fulfillment_type"), ["DELIVERY"])
        self.assertEqual(self.client.session["unrelated"], "keep")
        self.assertEqual(self.client.session["delivery_location"]["label"], "Synthetic existing location")

    def test_stale_foreign_or_completed_attempt_is_not_recovered(self):
        for kind in ("owner", "token", "expired", "cart", "completed"):
            with self.subTest(kind=kind):
                preview = self.client.get(self.preview_url)
                self.client.post(self.place_url, self._data(preview))
                session = self.client.session
                state = dict(session["checkout_recovery"])
                if kind == "owner": state["customer_id"] = self.customer_b.pk
                if kind == "token": state["token"] = "stale-attempt"
                if kind == "expired": state["created_at"] -= 601
                if kind == "cart": state["cart_id"] = -1
                session["checkout_recovery"] = state
                session.save()
                if kind == "completed":
                    # Simulate an independently committed checkout before redirect.
                    from .checkout import place_customer_order
                    place_customer_order(customer=self.customer_a, actor=self.user_a,
                        checkout_token=state["token"], fulfillment_type=FulfillmentType.DELIVERY,
                        payment_method=PaymentMethod.COD, delivery_address_id=self.address_a.pk)
                    add_product_to_cart(customer=self.customer_a, product_code=self.product.product_code, quantity=Decimal("1"))
                response = self.client.get(self.preview_url)
                self.assertEqual(response.context["customer_notes"], "")
                self.assertFalse(response.context["recovering_checkout"])
                self.assertNotIn("checkout_recovery", self.client.session)

    def test_other_customer_session_cannot_see_recovery_or_cart(self):
        preview = self.client.get(self.preview_url)
        self.client.post(self.place_url, self._data(preview))
        other = Client(enforce_csrf_checks=True)
        other.force_login(self.user_b)
        response = other.get(self.preview_url)
        self.assertNotContains(response, self.product.name)
        self.assertNotContains(response, "Collect after lunch")
        self.assertNotIn("checkout_recovery", other.session)
        self.client.force_login(self.user_b)
        response = self.client.get(self.preview_url)
        self.assertNotContains(response, "Collect after lunch")
        self.assertNotIn("checkout_recovery", self.client.session)

    def test_invalid_token_does_not_save_recovery_or_create_order(self):
        preview = self.client.get(self.preview_url)
        before = self._inventory_count()
        response = self.client.post(self.place_url, self._data(preview, checkout_token="forged-token"), follow=True)
        self.assertNotIn("checkout_recovery", self.client.session)
        self.assertEqual(response.context["customer_notes"], "")
        self.assertEqual(Order.objects.count(), 0)
        self.assertEqual(self._inventory_count(), before)

    def test_form_failure_preserves_valid_note_and_enforces_note_length(self):
        preview = self.client.get(self.preview_url)
        valid_note = "x" * 2000
        response = self.client.post(self.place_url, self._data(preview, payment_method="INVALID", customer_notes=valid_note), follow=True)
        self.assertEqual(response.context["customer_notes"], valid_note)
        self.assertEqual(self._checked(response, "payment_method"), [])
        invalid = self.client.post(self.place_url, self._data(response, customer_notes="x" * 2001), follow=True)
        self.assertContains(invalid, "at most 2000 characters")
        self.assertEqual(Order.objects.count(), 0)

    def test_pickup_cod_and_nondefault_delivery_address_are_retained(self):
        preview = self.client.get(self.preview_url)
        response = self.client.post(self.place_url, self._data(preview, payment_method="COD"), follow=True)
        self.assertEqual(self._checked(response, "payment_method"), ["COD"])
        # A valid delivery address must not be lost on another field's error.
        alternate = create_customer_delivery_address(customer=self.customer_a, data={
            "label": AddressLabel.WORK, "recipient_name": "Synthetic Work", "phone_number": "9000000301",
            "line1": "Work address", "city": "Test", "state": "Test", "postal_code": "560001",
            "latitude": "12.9", "longitude": "77.5", "is_default": False,
        })
        response = self.client.post(self.place_url, self._data(response,
            fulfillment_type="DELIVERY", payment_method="COD", delivery_address_id=alternate.pk,
            customer_notes="x" * 2001), follow=True)
        self.assertEqual(self._checked(response, "delivery_address_id"), [str(alternate.pk)])
        self.assertEqual(self._checked(response, "fulfillment_type"), ["DELIVERY"])
        self.assertEqual(self._checked(response, "payment_method"), ["COD"])

    def test_success_clears_recovery_without_clearing_other_session_data(self):
        preview = self.client.get(self.preview_url)
        self.client.post(self.place_url, self._data(preview))
        # Submit a corrected request with the still-current token before GET.
        session = self.client.session
        session["unrelated"] = "keep"
        session["delivery_location"] = {"label": "Keep location"}
        session.save()
        self.client.post(self.place_url, self._data(preview, **{f"pickup_location_{self.other_store.pk}": self.other_pickup.pk}))
        self.assertEqual(Order.objects.count(), 1)
        self.assertNotIn("checkout_recovery", self.client.session)
        self.assertNotIn("checkout_token", self.client.session)
        self.assertEqual(self.client.session["unrelated"], "keep")
        self.assertEqual(self.client.session["delivery_location"]["label"], "Keep location")


    def test_unexpected_checkout_exception_is_not_converted_to_recovery(self):
        from unittest.mock import patch
        preview = self.client.get(self.preview_url)
        data = self._data(preview, **{f"pickup_location_{self.other_store.pk}": self.other_pickup.pk})
        with patch("orders.views.place_customer_order", side_effect=RuntimeError("synthetic unexpected failure")):
            with self.assertRaises(RuntimeError):
                self.client.post(self.place_url, data)
        self.assertNotIn("checkout_recovery", self.client.session)
        self.assertEqual(Order.objects.count(), 0)


    def _focus_elements(self, response):
        from html.parser import HTMLParser

        class Elements(HTMLParser):
            def __init__(self):
                super().__init__()
                self.values = []

            def handle_starttag(self, tag, attrs):
                self.values.append((tag, dict(attrs)))

        parser = Elements()
        parser.feed(response.content.decode())
        ids = [attrs["id"] for _tag, attrs in parser.values if "id" in attrs]
        self.assertEqual(len(ids), len(set(ids)), "Focus targets must have unique IDs")
        return parser.values

    def _assert_collection_focus_contract(self, response, invalid_store_ids):
        elements = self._focus_elements(response)
        by_id = {attrs["id"]: attrs for _tag, attrs in elements if "id" in attrs}
        summary = by_id["checkout-error-summary"]
        self.assertEqual(summary["tabindex"], "-1")
        self.assertIn(summary["aria-labelledby"], by_id)
        links = [attrs["href"] for tag, attrs in elements
                 if tag == "a" and attrs.get("href", "").startswith("#collection-group-")]
        expected_links = []
        for index, group in enumerate(response.context["store_groups"], start=1):
            group_id = f"collection-group-{index}"
            error_id = f"collection-error-{index}"
            fieldset = by_id[group_id]
            self.assertIn(fieldset["aria-labelledby"], by_id)
            radios = [attrs for tag, attrs in elements if tag == "input"
                      and attrs.get("name") == f"pickup_location_{group['store_id']}"]
            if group["store_id"] in invalid_store_ids:
                expected_links.append(f"#{group_id}")
                self.assertEqual(fieldset["tabindex"], "-1")
                self.assertEqual(fieldset["aria-describedby"], error_id)
                self.assertIn(error_id, by_id)
                for radio in radios:
                    self.assertEqual(radio["aria-invalid"], "true")
                    self.assertEqual(radio["aria-describedby"], error_id)
                    self.assertNotIn("checked", radio)
            else:
                self.assertNotIn(error_id, by_id)
                self.assertNotIn("aria-describedby", fieldset)
                for radio in radios:
                    self.assertNotIn("aria-invalid", radio)
                    self.assertNotIn("aria-describedby", radio)
        self.assertEqual(links, expected_links)
        for name in (self.store.name, self.other_store.name):
            self.assertNotContains(response, name)

    def test_fresh_checkout_has_no_error_focus_target_or_invalid_radios(self):
        response = self.client.get(self.preview_url)
        elements = self._focus_elements(response)
        self.assertFalse(any(attrs.get("id") == "checkout-error-summary"
                             for _tag, attrs in elements))
        self.assertFalse(any("aria-invalid" in attrs for _tag, attrs in elements))
        self.assertFalse(any(attrs.get("href", "").startswith("#collection-group-")
                             for _tag, attrs in elements))
        self.assertEqual(self._checked(response, "fulfillment_type"), ["DELIVERY"])

    def test_recovered_summary_links_only_invalid_group_and_preserves_valid_input(self):
        from django.utils.html import escape
        self.other_product.name = "Synthetic <Notebook> & paper"
        self.other_product.save(update_fields=["name"])
        preview = self.client.get(self.preview_url)
        before = self._inventory_count()
        response = self.client.post(self.place_url, self._data(preview), follow=True)
        self._assert_collection_focus_contract(response, {self.other_store.pk})
        self.assertContains(response, escape(self.other_product.name))
        self.assertNotContains(response, self.other_product.name)
        self.assertContains(response, escape(self.note))
        self.assertEqual(self._checked(response, f"pickup_location_{self.store.pk}"), [str(self.selected.pk)])
        self.assertEqual(self._checked(response, "payment_method"), ["PAY_AT_PICKUP"])
        self.assertEqual(Order.objects.count(), 0)
        self.assertEqual(self._inventory_count(), before)

    def test_multiple_invalid_groups_include_focusable_group_with_no_options(self):
        preview = self.client.get(self.preview_url)
        self.other_pickup.is_active = False
        self.other_pickup.save(update_fields=["is_active"])
        response = self.client.post(self.place_url, self._data(preview, **{
            f"pickup_location_{self.store.pk}": "",
            f"pickup_location_{self.other_store.pk}": str(self.other_pickup.pk),
        }), follow=True)
        self._assert_collection_focus_contract(response, {self.store.pk, self.other_store.pk})
        self.assertNotContains(response, f'id="pickup-{self.other_pickup.pk}"')
        self.assertContains(response, "No collection points are available for these items.")
        self.assertEqual(Order.objects.count(), 0)

    def test_delivery_recovery_summary_does_not_mark_collection_options_invalid(self):
        preview = self.client.get(self.preview_url)
        response = self.client.post(self.place_url, self._data(preview,
            fulfillment_type="DELIVERY", payment_method="COD",
            delivery_address_id=self.address_a.pk, customer_notes="x" * 2001,
        ), follow=True)
        self._assert_collection_focus_contract(response, set())
        self.assertContains(response, "at most 2000 characters")
        self.assertEqual(self._checked(response, "delivery_address_id"), [str(self.address_a.pk)])
        self.assertEqual(self._checked(response, "fulfillment_type"), ["DELIVERY"])
