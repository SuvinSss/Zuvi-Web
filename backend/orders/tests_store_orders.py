"""
Store portal StoreOrder management and cross-store isolation.
"""

from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.test import Client, TestCase
from django.urls import reverse

from accounts.models import Role
from cart.services import add_product_to_cart
from customers.models import AddressLabel, RegistrationSource
from customers.services import create_customer_delivery_address, create_customer_with_user
from stores.models import StoreStatus, StoreUser

from .checkout import place_customer_order
from .models import FulfillmentType, PaymentMethod, StoreOrderStatus
from .store_status import transition_store_order
from .tests_checkout import CheckoutTestMixin

User = get_user_model()


class StoreOrderPortalIsolationTests(CheckoutTestMixin, TestCase):
    def setUp(self):
        self.client = Client(enforce_csrf_checks=True)

        self.store_a = self.create_store(name="Orders Store A")
        self.store_b = self.create_store(name="Orders Store B")
        self.product_a = self.create_public_product(
            store=self.store_a,
            name="Alpha Order Item",
            stock=Decimal("20.000"),
            store_price=Decimal("50.00"),
            profit_margin=Decimal("10.00"),
        )
        self.product_b = self.create_public_product(
            store=self.store_b,
            name="Beta Order Item",
            stock=Decimal("20.000"),
            store_price=Decimal("40.00"),
            profit_margin=Decimal("10.00"),
        )

        self.manager_a = User.objects.create_user(
            username="orders-mgr-a",
            email="orders-mgr-a@example.com",
            password="secure-password-123",
            role=Role.STORE_USER,
        )
        StoreUser.objects.create(
            store=self.store_a,
            user=self.manager_a,
            is_primary=True,
            is_active=True,
            can_manage_inventory=True,
            can_manage_orders=True,
        )
        self.viewer_a = User.objects.create_user(
            username="orders-viewer-a",
            email="orders-viewer-a@example.com",
            password="secure-password-123",
            role=Role.STORE_USER,
        )
        StoreUser.objects.create(
            store=self.store_a,
            user=self.viewer_a,
            is_primary=False,
            is_active=True,
            can_manage_inventory=True,
            can_manage_orders=False,
        )
        self.manager_b = User.objects.create_user(
            username="orders-mgr-b",
            email="orders-mgr-b@example.com",
            password="secure-password-123",
            role=Role.STORE_USER,
        )
        StoreUser.objects.create(
            store=self.store_b,
            user=self.manager_b,
            is_primary=True,
            is_active=True,
            can_manage_inventory=True,
            can_manage_orders=True,
        )

        self.customer, self.customer_user = create_customer_with_user(
            user_data={
                "username": "store-order-customer",
                "email": "store-order-customer@example.com",
                "first_name": "Store",
                "last_name": "Customer",
                "phone_number": "9000000911",
                "password": "secure-password-123",
            },
            registration_source=RegistrationSource.WEBSITE,
        )
        self.address = create_customer_delivery_address(
            customer=self.customer,
            data={
                "label": AddressLabel.HOME,
                "recipient_name": "Store Customer",
                "phone_number": "9000000911",
                "line1": "15 Portal Lane",
                "line2": "",
                "landmark": "",
                "city": "Bengaluru",
                "district": "",
                "state": "Karnataka",
                "postal_code": "560001",
                "latitude": "12.971600",
                "longitude": "77.594600",
                "delivery_instructions": "Leave at gate",
                "is_default": True,
            },
        )



    def _place_multi_store(self, *, token):
        add_product_to_cart(
            customer=self.customer,
            product_code=self.product_a.product_code,
            quantity=Decimal("2.000"),
        )
        add_product_to_cart(
            customer=self.customer,
            product_code=self.product_b.product_code,
            quantity=Decimal("1.000"),
        )
        return place_customer_order(
            customer=self.customer,
            checkout_token=token,
            fulfillment_type=FulfillmentType.DELIVERY,
            payment_method=PaymentMethod.COD,
            delivery_address_id=self.address.pk,
            customer_notes="Please pack carefully",
            actor=self.customer_user,
        )


    def _action_url(self, name, number):
        return reverse(
            f"orders:{name}",
            kwargs={"store_order_number": number},
        )







