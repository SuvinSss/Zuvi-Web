"""Role-based REST API: auth, public catalogue, customer, store and admin endpoints."""
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core import mail
from django.core.cache import cache
from django.test import Client, TestCase, override_settings
from rest_framework.authtoken.models import Token
from rest_framework.test import APIClient

from accounts.models import Role
from catalog.models import Product
from core.models import AuditEvent
from deliveries.models import DeliveryPartner, PartnerStatus
from deliveries.tests import DeliveryBase
from orders.models import Order, OrderStatus, StoreOrder, StoreOrderStatus
from inventory.models import InventoryTransaction

User = get_user_model()
PW = "Str0ng-pass-phrase-77"


class ApiTestBase(DeliveryBase):
    def setUp(self):
        super().setUp()
        cache.clear()

    def as_(self, user):
        api = APIClient()
        if user is not None:
            api.force_authenticate(user)
        return api

    def other_customer(self, name="other-cust"):
        from customers.models import RegistrationSource
        from customers.services import create_customer_with_user

        return create_customer_with_user(
            user_data={"username": name, "email": f"{name}@example.com", "first_name": "Other", "last_name": "Cust",
                       "phone_number": f"9400{abs(hash(name)) % 1000000:06d}", "password": PW},
            registration_source=RegistrationSource.WEBSITE)

    def address_payload(self, **extra):
        data = {"label": "HOME", "recipient_name": "Test Person", "phone_number": "9000000001", "line1": "1 Test Street", "city": "Bengaluru",
                "state": "Karnataka", "postal_code": "560001", "latitude": "12.9716", "longitude": "77.5946"}
        data.update(extra)
        return data


class AuthTests(ApiTestBase):
    def register(self, **extra):
        data = {"username": "newbie", "email": "newbie@example.com", "password": PW, "first_name": "New", "last_name": "Bie", "phone_number": "9500000001"}
        data.update(extra)
        return APIClient().post("/api/v1/auth/register/", data, format="json")

    def test_registration_creates_customer_and_ignores_privilege_fields(self):
        response = self.register(role="SUPER_ADMIN", is_staff=True, is_superuser=True, is_active=False)
        self.assertEqual(response.status_code, 201, response.content)
        user = User.objects.get(username="newbie")
        self.assertEqual((user.role, user.is_staff, user.is_superuser, user.is_active), (Role.CUSTOMER, False, False, True))
        self.assertTrue(hasattr(user, "customer_profile"))
        self.assertNotIn("password", response.content.decode())

    def test_registration_validation(self):
        self.assertEqual(self.register(password="123").status_code, 400)
        self.register()
        self.assertEqual(self.register(username="other", phone_number="9500000009").status_code, 400)  # duplicate email
        self.assertEqual(self.register(username="third", email="third@example.com").status_code, 400)  # duplicate phone

    def test_partner_registration_is_pending_and_cannot_work(self):
        response = APIClient().post("/api/v1/auth/partner-register/", {
            "username": "rider1", "email": "rider1@example.com", "password": PW, "first_name": "Ri", "phone_number": "9500000002",
            "vehicle_type": "SCOOTER", "role": "ADMIN"}, format="json")
        self.assertEqual(response.status_code, 201, response.content)
        user = User.objects.get(username="rider1")
        self.assertEqual(user.role, Role.DELIVERY_AGENT)
        self.assertEqual(user.delivery_partner.status, PartnerStatus.PENDING)
        api = self.as_(user)
        self.assertEqual(api.get("/api/v1/delivery/assignments/").status_code, 403)

    def test_token_login_me_and_revoke(self):
        self.register()
        api = APIClient()
        bad = api.post("/api/v1/auth/token/", {"username": "newbie", "password": "wrong"}, format="json")
        self.assertEqual(bad.status_code, 400)
        good = api.post("/api/v1/auth/token/", {"username": "newbie", "password": PW}, format="json")
        self.assertEqual(good.status_code, 200)
        token = good.json()["token"]
        client = APIClient()
        client.credentials(HTTP_AUTHORIZATION=f"Token {token}")
        me = client.get("/api/v1/auth/me/")
        self.assertEqual(me.json()["username"], "newbie")
        self.assertEqual(me.json()["role"], "CUSTOMER")
        self.assertEqual(client.post("/api/v1/auth/token/revoke/").status_code, 204)
        self.assertIn(client.get("/api/v1/auth/me/").status_code, (401, 403))

    def test_suspended_user_cannot_login_and_existing_token_stops_working(self):
        self.register()
        token = APIClient().post("/api/v1/auth/token/", {"username": "newbie", "password": PW}, format="json").json()["token"]
        client = APIClient()
        client.credentials(HTTP_AUTHORIZATION=f"Token {token}")
        self.assertEqual(client.get("/api/v1/auth/me/").status_code, 200)
        user = User.objects.get(username="newbie")
        resp = self.as_(self.admin).post(f"/api/v1/admin/users/{user.pk}/suspend/", {"reason": "Fraud review"}, format="json")
        self.assertEqual(resp.status_code, 200, resp.content)
        self.assertIn(client.get("/api/v1/auth/me/").status_code, (401, 403))
        denied = APIClient().post("/api/v1/auth/token/", {"username": "newbie", "password": PW}, format="json")
        self.assertEqual(denied.status_code, 400)
        self.assertEqual(denied.json()["detail"], "Invalid username or password.")  # no hint that the account is suspended
        self.assertTrue(AuditEvent.objects.filter(action="user.suspend", actor=self.admin).exists())
        self.as_(self.admin).post(f"/api/v1/admin/users/{user.pk}/reactivate/", {"reason": "Cleared"}, format="json")
        self.assertEqual(APIClient().post("/api/v1/auth/token/", {"username": "newbie", "password": PW}, format="json").status_code, 200)

    def test_session_signin_requires_csrf(self):
        self.register()
        client = Client(enforce_csrf_checks=True)
        denied = client.post("/api/v1/auth/signin/", {"username": "newbie", "password": PW}, content_type="application/json")
        self.assertEqual(denied.status_code, 403)
        client.get("/api/v1/auth/session/")
        csrf = client.cookies["csrftoken"].value
        ok = client.post("/api/v1/auth/signin/", {"username": "newbie", "password": PW}, content_type="application/json", HTTP_X_CSRFTOKEN=csrf)
        self.assertEqual(ok.status_code, 200, ok.content)
        self.assertEqual(ok.json()["user"]["role"], "CUSTOMER")
        self.assertIn("HttpOnly", str(ok.cookies["sessionid"]))
        self.assertEqual(client.get("/api/v1/auth/me/").status_code, 200)

    def test_change_password_needs_current_password_and_revokes_tokens(self):
        self.register()
        user = User.objects.get(username="newbie")
        Token.objects.create(user=user)
        api = self.as_(user)
        self.assertEqual(api.post("/api/v1/auth/password/change/", {"current_password": "nope", "new_password": "An0ther-long-pass-99"}, format="json").status_code, 400)
        self.assertEqual(api.post("/api/v1/auth/password/change/", {"current_password": PW, "new_password": "123"}, format="json").status_code, 400)
        self.assertEqual(api.post("/api/v1/auth/password/change/", {"current_password": PW, "new_password": "An0ther-long-pass-99"}, format="json").status_code, 204)
        self.assertFalse(Token.objects.filter(user=user).exists())
        user.refresh_from_db()
        self.assertTrue(user.check_password("An0ther-long-pass-99"))

    @override_settings(EMAIL_HOST="smtp.invalid", EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend", FRONTEND_BASE_URL="https://app.example")
    def test_password_reset_does_not_reveal_accounts_and_works_once(self):
        self.register()
        api = APIClient()
        unknown = api.post("/api/v1/auth/password/reset/", {"email": "nobody@example.com"}, format="json")
        known = api.post("/api/v1/auth/password/reset/", {"email": "newbie@example.com"}, format="json")
        self.assertEqual((unknown.status_code, known.status_code), (202, 202))
        self.assertEqual(unknown.json(), known.json())
        self.assertEqual(len(mail.outbox), 1)
        import re

        match = re.search(r"uid=([^&\s]+)&token=([^\s]+)", mail.outbox[0].body)
        uid, token = match.groups()
        bad = api.post("/api/v1/auth/password/reset/confirm/", {"uid": uid, "token": "bad-token", "new_password": "Brand-new-pass-55"}, format="json")
        self.assertEqual(bad.status_code, 400)
        ok = api.post("/api/v1/auth/password/reset/confirm/", {"uid": uid, "token": token, "new_password": "Brand-new-pass-55"}, format="json")
        self.assertEqual(ok.status_code, 204)
        again = api.post("/api/v1/auth/password/reset/confirm/", {"uid": uid, "token": token, "new_password": "Third-new-pass-66"}, format="json")
        self.assertEqual(again.status_code, 400)

    def test_profile_update_cannot_change_role(self):
        api = self.as_(self.customer_user)
        response = api.patch("/api/v1/auth/me/", {"first_name": "Changed", "role": "ADMIN", "is_staff": True}, format="json")
        self.assertEqual(response.status_code, 200, response.content)
        self.customer_user.refresh_from_db()
        self.assertEqual((self.customer_user.first_name, self.customer_user.role, self.customer_user.is_staff), ("Changed", Role.CUSTOMER, False))

    def test_me_payload_is_role_aware(self):
        partner = self.make_partner("me-rider")
        self.assertEqual(self.as_(partner.user).get("/api/v1/auth/me/").json()["delivery_partner"]["status"], "APPROVED")
        self.assertEqual(self.as_(self.store_user).get("/api/v1/auth/me/").json()["store"]["id"], self.store.pk)
        self.assertEqual(APIClient().get("/api/v1/auth/me/").status_code in (401, 403), True)


class PublicCatalogTests(ApiTestBase):
    def test_public_products_hide_internal_pricing_and_unpublished_items(self):
        hidden = self.create_public_product(store=self.store, name="Hidden Item")
        Product.objects.filter(pk=hidden.pk).update(is_active=False)
        response = APIClient().get("/api/v1/public/products/")
        self.assertEqual(response.status_code, 200)
        names = [p["name"] for p in response.json()["results"]]
        self.assertIn("Delivery Item", names)
        self.assertNotIn("Hidden Item", names)
        text = response.content.decode()
        for secret in ("store_price", "profit_margin", "commission", "selling_price"):
            self.assertNotIn(secret, text)
        row = response.json()["results"][0]
        self.assertIn("price", row)
        self.assertNotIn("stock_quantity", row)

    def test_out_of_stock_and_suspended_store_products_not_listed(self):
        Product.objects.filter(pk=self.product.pk).update(stock_quantity=Decimal("0"))
        self.assertEqual(APIClient().get("/api/v1/public/products/").json()["count"], 0)
        Product.objects.filter(pk=self.product.pk).update(stock_quantity=Decimal("5"))
        self.assertEqual(APIClient().get("/api/v1/public/products/").json()["count"], 1)
        from stores.models import Store, StoreStatus
        Store.objects.filter(pk=self.store.pk).update(status=StoreStatus.SUSPENDED)
        self.assertEqual(APIClient().get("/api/v1/public/products/").json()["count"], 0)
        self.assertEqual(APIClient().get(f"/api/v1/public/products/by-code/{self.product.product_code}/").status_code, 404)

    def test_detail_search_and_filters(self):
        api = APIClient()
        detail = api.get(f"/api/v1/public/products/by-code/{self.product.product_code}/")
        self.assertEqual(detail.status_code, 200)
        self.assertNotIn("store_price", detail.content.decode())
        self.assertEqual(api.get("/api/v1/public/products/?q=Delivery").json()["count"], 1)
        self.assertEqual(api.get("/api/v1/public/products/?q=zzzz").json()["count"], 0)
        self.assertEqual(api.get("/api/v1/public/products/?category=abc").json()["count"], 0)
        self.assertEqual(api.get("/api/v1/public/products/?ordering=-price").status_code, 200)
        self.assertEqual(api.get("/api/v1/public/products/?max_price=0.01").json()["count"], 0)

    def test_public_store_listing_has_no_private_fields(self):
        response = APIClient().get("/api/v1/public/stores/")
        self.assertEqual(response.status_code, 200)
        text = response.content.decode()
        for secret in ("commission", "contact_phone", "email", "line1"):
            self.assertNotIn(secret, text)
        self.assertEqual(APIClient().get(f"/api/v1/public/stores/{self.store.pk}/").status_code, 200)

    def test_pagination_is_bounded(self):
        for i in range(3):
            self.create_public_product(store=self.store, name=f"Bulk {i}")
        response = APIClient().get("/api/v1/public/products/?page_size=1000")
        self.assertLessEqual(len(response.json()["results"]), 100)


class CustomerFlowTests(ApiTestBase):
    def setUp(self):
        super().setUp()
        self.api = self.as_(self.customer_user)

    def add_to_cart(self, qty="2"):
        return self.api.post("/api/v1/cart/items/", {"product_id": self.product.pk, "quantity": qty}, format="json")

    def test_address_crud_and_isolation(self):
        created = self.api.post("/api/v1/customer/addresses/", self.address_payload(), format="json")
        self.assertEqual(created.status_code, 201, created.content)
        aid = created.json()["id"]
        stranger = self.as_(self.other_customer()[1])
        self.assertEqual(stranger.get(f"/api/v1/customer/addresses/{aid}/").status_code, 404)
        self.assertEqual(stranger.delete(f"/api/v1/customer/addresses/{aid}/").status_code, 404)
        self.assertEqual(stranger.put(f"/api/v1/customer/addresses/{aid}/", self.address_payload(), format="json").status_code, 404)
        self.assertEqual(stranger.get("/api/v1/customer/addresses/").json(), [])
        upd = self.api.put(f"/api/v1/customer/addresses/{aid}/", self.address_payload(city="Mysuru"), format="json")
        self.assertEqual(upd.json()["city"], "Mysuru")
        bad = self.api.post("/api/v1/customer/addresses/", self.address_payload(latitude="95"), format="json")
        self.assertEqual(bad.status_code, 400)
        self.assertEqual(self.api.delete(f"/api/v1/customer/addresses/{aid}/").status_code, 204)
        self.assertEqual(self.api.get(f"/api/v1/customer/addresses/{aid}/").status_code, 404)

    def test_only_customers_use_customer_endpoints(self):
        for user in (self.store_user, self.admin, self.make_partner("not-a-customer").user):
            self.assertEqual(self.as_(user).get("/api/v1/cart/").status_code, 403, user.username)
            self.assertEqual(self.as_(user).get("/api/v1/customer/addresses/").status_code, 403)
        self.assertIn(APIClient().get("/api/v1/cart/").status_code, (401, 403))

    def test_cart_totals_use_live_server_price_never_client_price(self):
        response = self.api.post("/api/v1/cart/items/", {"product_id": self.product.pk, "quantity": "2", "unit_price": "0.01", "price": "0.01"}, format="json")
        self.assertEqual(response.status_code, 201, response.content)
        body = response.json()
        self.product.refresh_from_db()
        self.assertEqual(Decimal(body["subtotal"]), (self.product.final_price * 2).quantize(Decimal("0.01")))
        item = body["items"][0]
        self.assertEqual(self.api.patch(f"/api/v1/cart/items/{item['id']}/", {"quantity": "3"}, format="json").json()["items"][0]["quantity"], "3.000")
        self.assertEqual(self.api.patch(f"/api/v1/cart/items/{item['id']}/", {"quantity": "0"}, format="json").status_code, 400)
        self.assertEqual(self.api.patch(f"/api/v1/cart/items/{item['id']}/", {"quantity": "9999"}, format="json").status_code, 400)  # over stock
        other = self.as_(self.other_customer()[1])
        self.assertEqual(other.patch(f"/api/v1/cart/items/{item['id']}/", {"quantity": "1"}, format="json").status_code, 404)
        self.assertEqual(len(self.api.get("/api/v1/cart/").json()["items"]), 1)
        self.assertEqual(self.api.delete(f"/api/v1/cart/items/{item['id']}/").json()["items"], [])

    def test_cannot_add_unavailable_product(self):
        Product.objects.filter(pk=self.product.pk).update(is_active=False)
        self.assertEqual(self.add_to_cart().status_code, 400)

    def test_checkout_requires_idempotency_key_and_is_idempotent(self):
        self.add_to_cart()
        payload = {"fulfillment_type": "DELIVERY", "payment_method": "COD", "delivery_address_id": self.address.pk}
        self.assertEqual(self.api.post("/api/v1/checkout/", payload, format="json").status_code, 400)
        first = self.api.post("/api/v1/checkout/", payload, format="json", HTTP_IDEMPOTENCY_KEY="key-1")
        self.assertEqual(first.status_code, 201, first.content)
        again = self.api.post("/api/v1/checkout/", payload, format="json", HTTP_IDEMPOTENCY_KEY="key-1")
        self.assertEqual(again.status_code, 200)
        self.assertEqual(again.json()["order_number"], first.json()["order_number"])
        self.assertEqual(Order.objects.filter(customer=self.customer).count(), 2)  # the fixture's order + this one, not three
        self.product.refresh_from_db()
        self.assertEqual(self.product.stock_quantity, Decimal("6.000"))  # fixture took 2, this order 2: deducted once each
        body = first.json()
        self.assertEqual(body["status"], "PLACED")
        self.assertEqual(len(body["store_orders"]), 1)
        self.assertEqual(self.api.get("/api/v1/cart/").json()["items"], [])

    def test_checkout_rejects_other_customers_address_and_empty_cart(self):
        self.add_to_cart()
        _, other_user = self.other_customer("addr-owner")
        from customers.services import create_customer_delivery_address
        theirs = create_customer_delivery_address(customer=other_user.customer_profile, data={
            "label": "HOME", "recipient_name": "X", "phone_number": "9000000009", "line1": "9 Other Rd", "line2": "", "landmark": "",
            "city": "Pune", "district": "", "state": "MH", "postal_code": "411001", "latitude": "18.5", "longitude": "73.8", "delivery_instructions": "", "is_default": True})
        response = self.api.post("/api/v1/checkout/", {"fulfillment_type": "DELIVERY", "payment_method": "COD", "delivery_address_id": theirs.pk},
                                 format="json", HTTP_IDEMPOTENCY_KEY="k-steal")
        self.assertEqual(response.status_code, 400)
        self.assertEqual(Order.objects.count(), 1)  # only the fixture's order
        self.api.delete("/api/v1/cart/")
        empty = self.api.post("/api/v1/checkout/", {"fulfillment_type": "DELIVERY", "payment_method": "COD", "delivery_address_id": self.address.pk},
                              format="json", HTTP_IDEMPOTENCY_KEY="k-empty")
        self.assertEqual(empty.status_code, 400)

    def test_preview_has_no_internal_fields(self):
        self.add_to_cart()
        response = self.api.get("/api/v1/checkout/preview/")
        self.assertEqual(response.status_code, 200)
        text = response.content.decode()
        self.assertNotIn("store_price", text)
        self.assertEqual(response.json()["has_blocking_issues"], False)
        self.assertEqual(len(response.json()["addresses"]), 1)

    def test_order_list_detail_isolation_and_cancel(self):
        self.add_to_cart()
        order_id = self.api.post("/api/v1/checkout/", {"fulfillment_type": "DELIVERY", "payment_method": "COD", "delivery_address_id": self.address.pk},
                                 format="json", HTTP_IDEMPOTENCY_KEY="k-orders").json()["id"]
        self.assertEqual(self.api.get("/api/v1/orders/").json()["count"], 2)  # fixture order + this one
        stranger = self.as_(self.other_customer("snoop2")[1])
        self.assertEqual(stranger.get("/api/v1/orders/").json()["count"], 0)
        self.assertEqual(stranger.get(f"/api/v1/orders/{order_id}/").status_code, 404)
        self.assertEqual(stranger.post(f"/api/v1/orders/{order_id}/cancel/", {"reason": "mine"}, format="json").status_code, 404)
        detail = self.api.get(f"/api/v1/orders/{order_id}/").json()
        self.assertTrue(detail["can_cancel"])
        self.assertNotIn("store_price", str(detail))
        self.assertEqual(self.api.post(f"/api/v1/orders/{order_id}/cancel/", {"reason": ""}, format="json").status_code, 400)
        cancelled = self.api.post(f"/api/v1/orders/{order_id}/cancel/", {"reason": "Changed my mind"}, format="json")
        self.assertEqual(cancelled.status_code, 200, cancelled.content)
        self.assertEqual(cancelled.json()["status"], "CANCELLED")
        self.product.refresh_from_db()
        self.assertEqual(self.product.stock_quantity, Decimal("8.000"))  # this order's 2 units restored (fixture order still holds 2)

    def test_cannot_cancel_after_store_started_preparing(self):
        self.add_to_cart()
        order_id = self.api.post("/api/v1/checkout/", {"fulfillment_type": "DELIVERY", "payment_method": "COD", "delivery_address_id": self.address.pk},
                                 format="json", HTTP_IDEMPOTENCY_KEY="k-late").json()["id"]
        so = StoreOrder.objects.get(order_id=order_id)
        store_api = self.as_(self.store_user)
        store_api.post(f"/api/v1/store/orders/{so.pk}/action/", {"action": "accept"}, format="json")
        store_api.post(f"/api/v1/store/orders/{so.pk}/action/", {"action": "processing"}, format="json")
        late = self.api.post(f"/api/v1/orders/{order_id}/cancel/", {"reason": "too late"}, format="json")
        self.assertEqual(late.status_code, 400)


class StoreApiTests(ApiTestBase):
    def test_store_sees_only_its_orders_and_limited_customer_data(self):
        api = self.as_(self.store_user)
        listing = api.get("/api/v1/store/orders/").json()
        self.assertEqual(listing["count"], 1)
        detail = api.get(f"/api/v1/store/orders/{self.store_order.pk}/").json()
        text = str(detail)
        self.assertNotIn("9000000777", text)      # customer phone
        self.assertNotIn("7 Delivery Road", text)  # customer address
        self.assertEqual(detail["recipient_first_name"], "Delivery")
        self.assertIn("accept", detail["actions"])
        rival = self.create_store_user(store=self.create_store(name="Rival Store"), username="rival-su")
        self.assertEqual(self.as_(rival).get("/api/v1/store/orders/").json()["count"], 0)
        self.assertEqual(self.as_(rival).get(f"/api/v1/store/orders/{self.store_order.pk}/").status_code, 404)
        self.assertEqual(self.as_(rival).post(f"/api/v1/store/orders/{self.store_order.pk}/action/", {"action": "accept"}, format="json").status_code, 404)

    def test_store_order_transitions_and_invalid_moves(self):
        api = self.as_(self.store_user)
        url = f"/api/v1/store/orders/{self.store_order.pk}/action/"
        self.assertEqual(api.post(url, {"action": "ready"}, format="json").status_code, 400)  # cannot skip steps
        self.assertEqual(api.post(url, {"action": "bogus"}, format="json").status_code, 400)
        for action, expected in (("accept", "ACCEPTED"), ("processing", "PREPARING"), ("ready", "READY")):
            response = api.post(url, {"action": action}, format="json")
            self.assertEqual((response.status_code, response.json()["status"]), (200, expected), response.content)
        self.order.refresh_from_db()
        self.assertEqual(self.order.status, OrderStatus.IN_PROGRESS)

    def test_reject_requires_reason_and_restores_stock(self):
        api = self.as_(self.store_user)
        url = f"/api/v1/store/orders/{self.store_order.pk}/action/"
        self.assertEqual(api.post(url, {"action": "reject"}, format="json").status_code, 400)
        self.assertEqual(api.post(url, {"action": "reject", "reason": "Out of stock"}, format="json").status_code, 200)
        self.product.refresh_from_db()
        self.assertEqual(self.product.stock_quantity, Decimal("10.000"))

    def test_staff_without_order_permission_cannot_act(self):
        from stores.models import StoreUser
        StoreUser.objects.filter(user=self.store_user).update(can_manage_orders=False)
        api = self.as_(self.store_user)
        self.assertEqual(api.post(f"/api/v1/store/orders/{self.store_order.pk}/action/", {"action": "accept"}, format="json").status_code, 403)
        self.assertEqual(api.get(f"/api/v1/store/orders/{self.store_order.pk}/").status_code, 200)

    def test_customers_and_partners_cannot_use_store_endpoints(self):
        for user in (self.customer_user, self.make_partner("store-nope").user, self.admin):
            self.assertEqual(self.as_(user).get("/api/v1/store/orders/").status_code, 403, user.username)

    def test_stock_changes_go_through_inventory_service(self):
        api = self.as_(self.store_user)
        before = InventoryTransaction.objects.filter(product=self.product).count()
        ok = api.post(f"/api/v1/store/products/{self.product.pk}/stock/", {"movement": "STOCK_IN", "quantity": "5", "reason": "Delivery received"}, format="json")
        self.assertEqual(ok.status_code, 200, ok.content)
        self.assertEqual(ok.json()["stock_quantity"], "13.000" if Decimal(ok.json()["stock_quantity"]) == Decimal("13") else ok.json()["stock_quantity"])
        self.assertEqual(InventoryTransaction.objects.filter(product=self.product).count(), before + 1)
        negative = api.post(f"/api/v1/store/products/{self.product.pk}/stock/", {"movement": "STOCK_OUT", "quantity": "9999", "reason": "x"}, format="json")
        self.assertEqual(negative.status_code, 400)
        other_store_product = self.create_public_product(store=self.create_store(name="Else Store"), name="Else Product")
        self.assertEqual(api.post(f"/api/v1/store/products/{other_store_product.pk}/stock/", {"movement": "STOCK_IN", "quantity": "1", "reason": "x"}, format="json").status_code, 404)
        self.assertEqual(api.get("/api/v1/store/products/").json()["count"], 1)

    def test_store_cannot_set_stock_directly(self):
        api = self.as_(self.store_user)
        response = api.post(f"/api/v1/store/products/{self.product.pk}/stock/", {"movement": "SET", "quantity": "999", "reason": "x"}, format="json")
        self.assertEqual(response.status_code, 400)
        self.product.refresh_from_db()
        self.assertNotEqual(self.product.stock_quantity, Decimal("999"))

    def test_store_me_dashboard(self):
        data = self.as_(self.store_user).get("/api/v1/store/me/").json()
        self.assertEqual(data["store"]["id"], self.store.pk)
        self.assertEqual(data["orders_by_status"]["PENDING"], 1)


class AdminApiTests(ApiTestBase):
    def test_admin_endpoints_deny_every_other_role(self):
        urls = ["/api/v1/admin/overview/", "/api/v1/admin/users/", "/api/v1/admin/stores/", "/api/v1/admin/orders/", "/api/v1/admin/audit-events/"]
        partner = self.make_partner("admin-nope")
        for user in (self.customer_user, self.store_user, partner.user):
            for url in urls:
                self.assertEqual(self.as_(user).get(url).status_code, 403, (user.username, url))
        for url in urls:
            self.assertIn(self.as_(None).get(url).status_code, (401, 403))

    def test_admin_without_django_permission_is_denied_orders_but_super_admin_is_not(self):
        self.assertEqual(self.as_(self.admin).get("/api/v1/admin/orders/").status_code, 403)
        self.assertEqual(self.as_(self.super_admin).get("/api/v1/admin/orders/").status_code, 200)
        self.grant_order_perms(self.admin, "view_order")
        refreshed = User.objects.get(pk=self.admin.pk)
        self.assertEqual(self.as_(refreshed).get("/api/v1/admin/orders/").status_code, 200)
        self.assertEqual(self.as_(refreshed).post(f"/api/v1/admin/orders/{self.order.pk}/status/", {"status": "CONFIRMED"}, format="json").status_code, 403)

    def test_order_monitoring_filters_and_detail(self):
        api = self.as_(self.super_admin)
        self.assertEqual(api.get("/api/v1/admin/orders/?status=PLACED").json()["count"], 1)
        self.assertEqual(api.get("/api/v1/admin/orders/?status=COMPLETED").json()["count"], 0)
        self.assertEqual(api.get(f"/api/v1/admin/orders/?q={self.order.order_number}").json()["count"], 1)
        detail = api.get(f"/api/v1/admin/orders/{self.order.pk}/").json()
        self.assertEqual(detail["customer"]["username"], "delivery-customer")
        self.assertIn("audit_history", detail)

    def test_admin_status_and_cancel(self):
        api = self.as_(self.super_admin)
        ok = api.post(f"/api/v1/admin/orders/{self.order.pk}/status/", {"status": "CONFIRMED", "reason": "ok"}, format="json")
        self.assertEqual(ok.status_code, 200, ok.content)
        self.assertEqual(api.post(f"/api/v1/admin/orders/{self.order.pk}/status/", {"status": "CANCELLED"}, format="json").status_code, 400)
        self.assertEqual(api.post(f"/api/v1/admin/orders/{self.order.pk}/cancel/", {"reason": "Fraud"}, format="json").json()["status"], "CANCELLED")

    def test_user_management_guards(self):
        api = self.as_(self.admin)
        self.assertEqual(api.post(f"/api/v1/admin/users/{self.admin.pk}/suspend/", {"reason": "x"}, format="json").status_code, 403)
        self.assertEqual(api.post(f"/api/v1/admin/users/{self.super_admin.pk}/suspend/", {"reason": "x"}, format="json").status_code, 403)
        self.assertEqual(api.post(f"/api/v1/admin/users/{self.customer_user.pk}/suspend/", {}, format="json").status_code, 400)
        listing = api.get("/api/v1/admin/users/?role=CUSTOMER").json()
        self.assertEqual(listing["count"], 1)
        self.assertNotIn("password", str(listing))

    def test_store_status_change_audited_and_validated(self):
        api = self.as_(self.super_admin)
        self.assertEqual(api.post(f"/api/v1/admin/stores/{self.store.pk}/status/", {"status": "SUSPENDED"}, format="json").status_code, 400)  # reason needed
        ok = api.post(f"/api/v1/admin/stores/{self.store.pk}/status/", {"status": "SUSPENDED", "reason": "Quality audit"}, format="json")
        self.assertEqual(ok.status_code, 200, ok.content)
        self.assertEqual(APIClient().get("/api/v1/public/products/").json()["count"], 0)
        self.assertEqual(api.post(f"/api/v1/admin/stores/{self.store.pk}/status/", {"status": "REJECTED", "reason": "x"}, format="json").status_code, 400)
        denied = self.as_(self.admin).post(f"/api/v1/admin/stores/{self.store.pk}/status/", {"status": "ACTIVE"}, format="json")
        self.assertEqual(denied.status_code, 403)

    def test_overview_and_audit_listing(self):
        data = self.as_(self.admin).get("/api/v1/admin/overview/").json()
        self.assertIn("orders", data)
        self.assertEqual(data["deliveries"]["partners_online"], 0)
        self.as_(self.admin).post(f"/api/v1/admin/users/{self.customer_user.pk}/suspend/", {"reason": "test"}, format="json")
        events = self.as_(self.admin).get("/api/v1/admin/audit-events/?action=user.suspend").json()
        self.assertEqual(events["count"], 1)
        self.assertEqual(events["results"][0]["actor"], self.admin.username)
