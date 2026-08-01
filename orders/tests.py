import uuid
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.test import TestCase

from accounts.models import Role
from catalog.models import Product, ProductCategory, ProductStatus, ProductUnit
from catalog.pricing import MarginType
from customers.models import (
    AddressLabel,
    Customer,
    CustomerAddress,
    RegistrationSource,
)
from locations.models import Address
from stores.models import Store, StoreCategory, StoreStatus, StoreType

from .models import (
    ORDER_ITEM_PUBLIC_SNAPSHOT_FIELDS,
    FulfillmentType,
    Order,
    OrderItem,
    OrderStatus,
    OrderStatusHistory,
    PaymentMethod,
    PaymentStatus,
    PickupLocation,
    StoreOrder,
    StoreOrderStatus,
    StoreOrderStatusHistory,
)

User = get_user_model()


class OrderModelTestMixin:
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
            overrides["address"] = self.create_address()
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

    def create_product(self, store=None, **overrides):
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
            "unit": ProductUnit.PIECE,
            "unit_value": Decimal("1.000"),
        }
        defaults.update(overrides)
        product = Product(**defaults)
        product.full_clean()
        product.save()
        return product

    def create_pickup_location(self, store=None, **overrides):
        store = store or self.create_store()
        if "address" not in overrides:
            overrides["address"] = self.create_address(
                line1=f"Pickup Desk {Address.objects.count() + 1}"
            )
        defaults = {
            "store": store,
            "name": "Main Counter",
            "code": f"PK-{PickupLocation.objects.count() + 1}",
            "contact_phone": "9876543210",
            "is_active": True,
        }
        defaults.update(overrides)
        location = PickupLocation(**defaults)
        location.full_clean()
        location.save()
        return location

    def create_customer_address(self, customer, **overrides):
        defaults = {
            "customer": customer,
            "address": overrides.pop("address", None) or self.create_address(),
            "label": AddressLabel.HOME,
            "recipient_name": "Ada Customer",
            "phone_number": "9876543210",
            "is_default": True,
            "is_active": True,
        }
        defaults.update(overrides)
        customer_address = CustomerAddress(**defaults)
        customer_address.full_clean()
        customer_address.save()
        return customer_address

    def create_delivery_order(self, customer=None, **overrides):
        customer = customer or self.create_customer(
            username=f"cust-{Order.objects.count() + 1}"
        )
        customer_address = overrides.pop("delivery_address", None)
        if customer_address is None and "delivery_line1" not in overrides:
            customer_address = self.create_customer_address(customer)
        defaults = {
            "customer": customer,
            "fulfillment_type": FulfillmentType.DELIVERY,
            "payment_method": PaymentMethod.COD,
            "payment_status": PaymentStatus.PENDING,
            "checkout_token": str(uuid.uuid4()),
            "delivery_address": customer_address,
            "delivery_recipient_name": "Ada Customer",
            "delivery_phone_number": "9876543210",
            "delivery_line1": "12 MG Road",
            "delivery_city": "Bengaluru",
            "delivery_state": "Karnataka",
            "delivery_postal_code": "560001",
            "delivery_country": "India",
            "delivery_latitude": Decimal("12.971600"),
            "delivery_longitude": Decimal("77.594600"),
            "items_subtotal": Decimal("120.00"),
            "delivery_charge": Decimal("0.00"),
            "discount_total": Decimal("0.00"),
            "grand_total": Decimal("120.00"),
        }
        defaults.update(overrides)
        order = Order(**defaults)
        order.full_clean()
        order.save()
        return order

    def create_facility_pickup_order(self, customer=None, **overrides):
        customer = customer or self.create_customer(
            username=f"pickup-{Order.objects.count() + 1}"
        )
        defaults = {
            "customer": customer,
            "fulfillment_type": FulfillmentType.FACILITY_PICKUP,
            "payment_method": PaymentMethod.COD,
            "payment_status": PaymentStatus.PENDING,
            "checkout_token": str(uuid.uuid4()),
            "items_subtotal": Decimal("120.00"),
            "delivery_charge": Decimal("0.00"),
            "discount_total": Decimal("0.00"),
            "grand_total": Decimal("120.00"),
        }
        defaults.update(overrides)
        order = Order(**defaults)
        order.full_clean()
        order.save()
        return order

    def create_store_order(self, order=None, store=None, **overrides):
        store = store or self.create_store()
        order = order or self.create_delivery_order()
        defaults = {
            "order": order,
            "store": store,
            "store_name": store.name,
            "store_code": store.store_code,
            "items_subtotal": Decimal("120.00"),
            "delivery_charge": Decimal("0.00"),
            "store_total": Decimal("120.00"),
            "status": StoreOrderStatus.PENDING,
        }
        defaults.update(overrides)
        store_order = StoreOrder(**defaults)
        store_order.full_clean()
        store_order.save()
        return store_order

    def create_order_item(self, store_order=None, product=None, **overrides):
        store_order = store_order or self.create_store_order()
        product = product or self.create_product(store=store_order.store)
        defaults = {
            "store_order": store_order,
            "product": product,
            "product_name": product.name,
            "product_code": product.product_code,
            "sku": product.sku,
            "unit": product.unit,
            "unit_value": product.unit_value,
            "unit_price": product.final_price,
            "quantity": Decimal("1.000"),
            "line_total": product.final_price,
        }
        defaults.update(overrides)
        item = OrderItem(**defaults)
        item.full_clean()
        item.save()
        return item


class PickupLocationModelTests(OrderModelTestMixin, TestCase):
    def test_create_pickup_location(self):
        location = self.create_pickup_location()
        self.assertTrue(location.is_active)
        self.assertIn(location.store.store_code, str(location))

    def test_pickup_code_unique_per_store_when_set(self):
        store = self.create_store()
        self.create_pickup_location(store=store, code="MAIN")
        duplicate = PickupLocation(
            store=store,
            name="Other",
            code="MAIN",
            address=self.create_address(line1="Other desk"),
        )
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                duplicate.save()


class OrderModelTests(OrderModelTestMixin, TestCase):
    def test_order_number_generated_on_save(self):
        order = self.create_delivery_order()
        self.assertTrue(order.order_number.startswith("ORD-"))
        self.assertEqual(len(order.order_number), 21)

    def test_checkout_token_unique(self):
        token = str(uuid.uuid4())
        self.create_delivery_order(checkout_token=token)
        other = self.create_customer(username="other")
        customer_address = self.create_customer_address(other)
        duplicate = Order(
            customer=other,
            fulfillment_type=FulfillmentType.DELIVERY,
            checkout_token=token,
            delivery_address=customer_address,
            delivery_recipient_name="Other Customer",
            delivery_phone_number="9876543211",
            delivery_line1="99 Other Road",
            delivery_city="Bengaluru",
            items_subtotal=Decimal("10.00"),
            grand_total=Decimal("10.00"),
        )
        with self.assertRaises(ValidationError) as ctx:
            duplicate.full_clean()
        self.assertIn("checkout_token", ctx.exception.message_dict)
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                duplicate.save()

    def test_defaults_are_cod_pending(self):
        order = self.create_delivery_order()
        self.assertEqual(order.payment_method, PaymentMethod.COD)
        self.assertEqual(order.payment_status, PaymentStatus.PENDING)
        self.assertEqual(order.status, OrderStatus.PLACED)

    def test_delivery_order_requires_address_fields(self):
        customer = self.create_customer(username="noaddr")
        order = Order(
            customer=customer,
            fulfillment_type=FulfillmentType.DELIVERY,
            checkout_token=str(uuid.uuid4()),
            items_subtotal=Decimal("10.00"),
            grand_total=Decimal("10.00"),
        )
        with self.assertRaises(ValidationError) as ctx:
            order.full_clean()
        self.assertIn("delivery_line1", ctx.exception.message_dict)

    def test_negative_money_rejected_by_constraint(self):
        customer = self.create_customer(username="neg")
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                Order.objects.create(
                    customer=customer,
                    fulfillment_type=FulfillmentType.DELIVERY,
                    checkout_token=str(uuid.uuid4()),
                    delivery_recipient_name="Ada",
                    delivery_phone_number="9876543210",
                    delivery_line1="12 MG Road",
                    delivery_city="Bengaluru",
                    items_subtotal=Decimal("-1.00"),
                    delivery_charge=Decimal("0.00"),
                    discount_total=Decimal("0.00"),
                    grand_total=Decimal("0.00"),
                )

    def test_order_delete_is_blocked(self):
        order = self.create_delivery_order()
        with self.assertRaises(ValidationError):
            order.delete()
        with self.assertRaises(ValidationError):
            Order.objects.filter(pk=order.pk).delete()
        self.assertTrue(Order.objects.filter(pk=order.pk).exists())

    def test_order_has_no_product_foreign_key(self):
        field_names = {field.name for field in Order._meta.fields}
        self.assertNotIn("product", field_names)
        self.assertFalse(
            any(field.name == "product" for field in Order._meta.local_fields)
        )


class StoreOrderModelTests(OrderModelTestMixin, TestCase):
    def test_store_order_number_generated(self):
        store_order = self.create_store_order()
        self.assertTrue(store_order.store_order_number.startswith("SO-"))

    def test_unique_per_order_and_store(self):
        order = self.create_delivery_order()
        store = self.create_store()
        self.create_store_order(order=order, store=store)
        duplicate = StoreOrder(
            order=order,
            store=store,
            store_name=store.name,
            store_code=store.store_code,
            items_subtotal=Decimal("10.00"),
            store_total=Decimal("10.00"),
        )
        with self.assertRaises(ValidationError):
            duplicate.full_clean()
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                duplicate.save()

    def test_pickup_location_must_match_store(self):
        store_a = self.create_store(name="Store A")
        store_b = self.create_store(name="Store B")
        pickup = self.create_pickup_location(store=store_b)
        order = self.create_facility_pickup_order()
        store_order = StoreOrder(
            order=order,
            store=store_a,
            store_name=store_a.name,
            store_code=store_a.store_code,
            pickup_location=pickup,
            items_subtotal=Decimal("10.00"),
            store_total=Decimal("10.00"),
        )
        with self.assertRaises(ValidationError) as ctx:
            store_order.full_clean()
        self.assertIn("pickup_location", ctx.exception.message_dict)

    def test_facility_pickup_requires_pickup_location(self):
        store = self.create_store()
        order = self.create_facility_pickup_order()
        store_order = StoreOrder(
            order=order,
            store=store,
            store_name=store.name,
            store_code=store.store_code,
            items_subtotal=Decimal("10.00"),
            store_total=Decimal("10.00"),
        )
        with self.assertRaises(ValidationError) as ctx:
            store_order.full_clean()
        self.assertIn("pickup_location", ctx.exception.message_dict)

    def test_store_order_delete_blocked(self):
        store_order = self.create_store_order()
        with self.assertRaises(ValidationError):
            store_order.delete()
        self.assertTrue(StoreOrder.objects.filter(pk=store_order.pk).exists())


class OrderItemModelTests(OrderModelTestMixin, TestCase):
    def test_snapshots_preserve_product_fields(self):
        store = self.create_store()
        product = self.create_product(
            store=store,
            name="Original Name",
            sku="ORIG-1",
            unit=ProductUnit.KG,
            unit_value=Decimal("0.500"),
            store_price=Decimal("80.00"),
            profit_margin_type=MarginType.FIXED,
            profit_margin=Decimal("19.50"),
        )
        self.assertEqual(product.final_price, Decimal("99.50"))
        store_order = self.create_store_order(store=store)
        item = self.create_order_item(store_order=store_order, product=product)

        product.name = "Renamed Later"
        product.sku = "CHANGED"
        product.store_price = Decimal("200.00")
        product.full_clean()
        product.save()

        item.refresh_from_db()
        self.assertEqual(item.product_name, "Original Name")
        self.assertEqual(item.sku, "ORIG-1")
        self.assertEqual(item.unit_price, Decimal("99.50"))
        self.assertEqual(item.unit, ProductUnit.KG)
        self.assertEqual(item.unit_value, Decimal("0.500"))

    def test_no_internal_price_fields_on_order_item(self):
        field_names = {field.name for field in OrderItem._meta.fields}
        sensitive = {
            "store_price",
            "profit_margin",
            "profit_margin_type",
            "selling_price",
            "discount_type",
            "discount_value",
            "commission",
        }
        self.assertFalse(field_names & sensitive)

    def test_public_snapshot_excludes_internal_fields(self):
        item = self.create_order_item()
        snapshot = item.public_snapshot()
        self.assertEqual(set(snapshot), set(ORDER_ITEM_PUBLIC_SNAPSHOT_FIELDS))
        self.assertNotIn("store_price", snapshot)

    def test_product_must_belong_to_store_order_store(self):
        store_a = self.create_store(name="A")
        store_b = self.create_store(name="B")
        store_order = self.create_store_order(store=store_a)
        product_b = self.create_product(store=store_b)
        item = OrderItem(
            store_order=store_order,
            product=product_b,
            product_name=product_b.name,
            product_code=product_b.product_code,
            sku=product_b.sku,
            unit=product_b.unit,
            unit_value=product_b.unit_value,
            unit_price=Decimal("10.00"),
            quantity=Decimal("1.000"),
            line_total=Decimal("10.00"),
        )
        with self.assertRaises(ValidationError) as ctx:
            item.full_clean()
        self.assertIn("product", ctx.exception.message_dict)

    def test_quantity_and_money_constraints(self):
        store_order = self.create_store_order()
        product = self.create_product(store=store_order.store)
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                OrderItem.objects.create(
                    store_order=store_order,
                    product=product,
                    product_name=product.name,
                    product_code=product.product_code,
                    sku=product.sku,
                    unit=product.unit,
                    unit_value=Decimal("1.000"),
                    unit_price=Decimal("10.00"),
                    quantity=Decimal("0.000"),
                    line_total=Decimal("0.00"),
                )

    def test_order_item_delete_blocked(self):
        item = self.create_order_item()
        with self.assertRaises(ValidationError):
            item.delete()
        self.assertTrue(OrderItem.objects.filter(pk=item.pk).exists())


class OrderHistoryModelTests(OrderModelTestMixin, TestCase):
    def test_order_status_history(self):
        order = self.create_delivery_order()
        actor = order.customer.user
        history = OrderStatusHistory.objects.create(
            order=order,
            old_status="",
            new_status=OrderStatus.PLACED,
            changed_by=actor,
            reason="Order placed",
        )
        self.assertIn(order.order_number, str(history))
        self.assertEqual(order.status_history.count(), 1)

    def test_store_order_status_history(self):
        store_order = self.create_store_order()
        history = StoreOrderStatusHistory.objects.create(
            store_order=store_order,
            old_status=StoreOrderStatus.PENDING,
            new_status=StoreOrderStatus.ACCEPTED,
            reason="Accepted by store",
        )
        self.assertIn(store_order.store_order_number, str(history))
        self.assertEqual(store_order.status_history.count(), 1)


class OrderRelationshipTests(OrderModelTestMixin, TestCase):
    def test_multi_store_order_split(self):
        customer = self.create_customer(username="multi")
        order = self.create_delivery_order(customer=customer)
        store_a = self.create_store(name="Store A")
        store_b = self.create_store(name="Store B")
        so_a = self.create_store_order(order=order, store=store_a)
        so_b = self.create_store_order(order=order, store=store_b)
        self.create_order_item(
            store_order=so_a,
            product=self.create_product(store=store_a, name="A Item"),
        )
        self.create_order_item(
            store_order=so_b,
            product=self.create_product(store=store_b, name="B Item"),
        )
        self.assertEqual(order.store_orders.count(), 2)
        self.assertEqual(so_a.items.count(), 1)
        self.assertEqual(so_b.items.count(), 1)

    def test_delivery_address_set_null_preserves_order(self):
        customer = self.create_customer(username="addr-null")
        customer_address = self.create_customer_address(customer)
        order = self.create_delivery_order(
            customer=customer,
            delivery_address=customer_address,
        )
        address_pk = customer_address.pk
        # Deactivate path in business logic; hard-delete CustomerAddress to
        # verify SET_NULL on Order.delivery_address while snapshots remain.
        location = customer_address.address
        customer_address.delete()
        order.refresh_from_db()
        self.assertIsNone(order.delivery_address_id)
        self.assertEqual(order.delivery_line1, "12 MG Road")
        self.assertFalse(CustomerAddress.objects.filter(pk=address_pk).exists())
        self.assertTrue(Address.objects.filter(pk=location.pk).exists())
