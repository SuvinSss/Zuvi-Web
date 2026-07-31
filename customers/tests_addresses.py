from decimal import Decimal

from django.test import Client, TestCase
from django.urls import reverse

from .decorators import portal_customer_addresses_queryset
from .models import AddressLabel, RegistrationSource
from .services import (
    create_customer_delivery_address,
    create_customer_with_user,
    deactivate_customer_address,
    update_customer_delivery_address,
)
from .tests import CustomerModelTestMixin


class CustomerPortalAddressTests(CustomerModelTestMixin, TestCase):
    def setUp(self):
        self.client = Client(enforce_csrf_checks=True)
        self.list_url = reverse("customers:customer_portal_address_list")
        self.create_url = reverse("customers:customer_portal_address_create")

        self.customer_a, self.user_a = create_customer_with_user(
            user_data={
                "username": "addr-customer-a",
                "email": "addr-a@example.com",
                "first_name": "Alice",
                "last_name": "Alpha",
                "phone_number": "9111111111",
                "password": "secure-password-123",
            },
            registration_source=RegistrationSource.WEBSITE,
        )
        self.customer_b, self.user_b = create_customer_with_user(
            user_data={
                "username": "addr-customer-b",
                "email": "addr-b@example.com",
                "first_name": "Bob",
                "last_name": "Beta",
                "phone_number": "9222222222",
                "password": "secure-password-123",
            },
            registration_source=RegistrationSource.WEBSITE,
        )

        self.valid_payload = {
            "label": AddressLabel.HOME,
            "recipient_name": "Alice Alpha",
            "phone_number": "9111111111",
            "line1": "10 Alice Street",
            "line2": "Apt 2",
            "landmark": "Near Park",
            "city": "Bengaluru",
            "district": "Bengaluru Urban",
            "state": "Karnataka",
            "postal_code": "560001",
            "latitude": "12.971600",
            "longitude": "77.594600",
            "delivery_instructions": "Ring the bell",
            "is_default": "on",
        }

    def _csrf_token(self, url):
        response = self.client.get(url)
        return response.cookies["csrftoken"].value

    def _login(self, user):
        self.client.force_login(user)
        self.client.get(self.list_url)

    def _post(self, url, payload):
        token = self._csrf_token(self.list_url)
        data = dict(payload)
        data["csrfmiddlewaretoken"] = token
        return self.client.post(url, data)

    def _edit_url(self, pk):
        return reverse("customers:customer_portal_address_edit", kwargs={"pk": pk})

    def _set_default_url(self, pk):
        return reverse(
            "customers:customer_portal_address_set_default",
            kwargs={"pk": pk},
        )

    def _deactivate_url(self, pk):
        return reverse(
            "customers:customer_portal_address_deactivate",
            kwargs={"pk": pk},
        )

    def test_create_page_includes_csrf(self):
        self._login(self.user_a)
        response = self.client.get(self.create_url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "csrfmiddlewaretoken")
        self.assertContains(response, "Latitude")
        self.assertContains(response, "Landmark")
        self.assertContains(response, "District")
        self.assertContains(response, "Delivery instructions")

    def test_first_active_address_becomes_default_automatically(self):
        self._login(self.user_a)
        payload = dict(self.valid_payload)
        payload.pop("is_default", None)
        response = self._post(self.create_url, payload)
        self.assertEqual(response.status_code, 302)

        address = self.customer_a.addresses.get()
        self.assertTrue(address.is_default)
        self.assertTrue(address.is_active)
        self.assertEqual(address.address.landmark, "Near Park")
        self.assertEqual(address.address.district, "Bengaluru Urban")
        self.assertEqual(address.delivery_instructions, "Ring the bell")

    def test_setting_default_clears_previous_default(self):
        first = create_customer_delivery_address(
            customer=self.customer_a,
            data={
                **{k: self.valid_payload[k] for k in (
                    "label",
                    "recipient_name",
                    "phone_number",
                    "line1",
                    "line2",
                    "landmark",
                    "city",
                    "district",
                    "state",
                    "postal_code",
                    "delivery_instructions",
                )},
                "latitude": Decimal("12.971600"),
                "longitude": Decimal("77.594600"),
                "is_default": True,
            },
        )
        second = create_customer_delivery_address(
            customer=self.customer_a,
            data={
                "label": AddressLabel.WORK,
                "recipient_name": "Alice Work",
                "phone_number": "9111111111",
                "line1": "20 Work Road",
                "line2": "",
                "landmark": "",
                "city": "Bengaluru",
                "district": "",
                "state": "Karnataka",
                "postal_code": "560002",
                "latitude": Decimal("12.980000"),
                "longitude": Decimal("77.600000"),
                "delivery_instructions": "",
                "is_default": True,
            },
        )
        first.refresh_from_db()
        second.refresh_from_db()
        self.assertFalse(first.is_default)
        self.assertTrue(second.is_default)

        self._login(self.user_a)
        response = self._post(self._set_default_url(first.pk), {})
        self.assertEqual(response.status_code, 302)
        first.refresh_from_db()
        second.refresh_from_db()
        self.assertTrue(first.is_default)
        self.assertFalse(second.is_default)

    def test_deactivate_default_promotes_another_active_address(self):
        first = create_customer_delivery_address(
            customer=self.customer_a,
            data={
                "label": AddressLabel.HOME,
                "recipient_name": "Alice Home",
                "phone_number": "9111111111",
                "line1": "Home Lane",
                "line2": "",
                "landmark": "",
                "city": "Bengaluru",
                "district": "",
                "state": "Karnataka",
                "postal_code": "560001",
                "latitude": Decimal("12.971600"),
                "longitude": Decimal("77.594600"),
                "delivery_instructions": "",
                "is_default": True,
            },
        )
        second = create_customer_delivery_address(
            customer=self.customer_a,
            data={
                "label": AddressLabel.WORK,
                "recipient_name": "Alice Work",
                "phone_number": "9111111111",
                "line1": "Work Lane",
                "line2": "",
                "landmark": "",
                "city": "Bengaluru",
                "district": "",
                "state": "Karnataka",
                "postal_code": "560002",
                "latitude": Decimal("12.980000"),
                "longitude": Decimal("77.600000"),
                "delivery_instructions": "",
                "is_default": False,
            },
        )
        self._login(self.user_a)
        response = self._post(self._deactivate_url(first.pk), {})
        self.assertEqual(response.status_code, 302)

        first.refresh_from_db()
        second.refresh_from_db()
        self.assertFalse(first.is_active)
        self.assertFalse(first.is_default)
        self.assertTrue(second.is_active)
        self.assertTrue(second.is_default)

    def test_deactivate_only_address_leaves_no_default(self):
        only = create_customer_delivery_address(
            customer=self.customer_a,
            data={
                "label": AddressLabel.HOME,
                "recipient_name": "Alice Alone",
                "phone_number": "9111111111",
                "line1": "Solo Street",
                "line2": "",
                "landmark": "",
                "city": "Bengaluru",
                "district": "",
                "state": "Karnataka",
                "postal_code": "560001",
                "latitude": Decimal("12.971600"),
                "longitude": Decimal("77.594600"),
                "delivery_instructions": "",
                "is_default": True,
            },
        )
        deactivate_customer_address(customer_address=only)
        only.refresh_from_db()
        self.assertFalse(only.is_active)
        self.assertFalse(only.is_default)
        self.assertFalse(
            self.customer_a.addresses.filter(is_active=True, is_default=True).exists()
        )

    def test_set_default_and_deactivate_require_post(self):
        address = create_customer_delivery_address(
            customer=self.customer_a,
            data={
                "label": AddressLabel.HOME,
                "recipient_name": "Alice",
                "phone_number": "9111111111",
                "line1": "Post Only",
                "line2": "",
                "landmark": "",
                "city": "Bengaluru",
                "district": "",
                "state": "Karnataka",
                "postal_code": "560001",
                "latitude": Decimal("12.971600"),
                "longitude": Decimal("77.594600"),
                "delivery_instructions": "",
                "is_default": True,
            },
        )
        self._login(self.user_a)
        self.assertEqual(self.client.get(self._set_default_url(address.pk)).status_code, 405)
        self.assertEqual(self.client.get(self._deactivate_url(address.pk)).status_code, 405)

    def test_invalid_latitude_and_longitude_rejected(self):
        self._login(self.user_a)
        bad_lat = dict(self.valid_payload)
        bad_lat["latitude"] = "95.000000"
        response = self._post(self.create_url, bad_lat)
        self.assertEqual(response.status_code, 200)
        self.assertFormError(
            response.context["form"],
            "latitude",
            "Latitude must be between -90 and 90.",
        )

        bad_lng = dict(self.valid_payload)
        bad_lng["longitude"] = "-181.000000"
        response = self._post(self.create_url, bad_lng)
        self.assertEqual(response.status_code, 200)
        self.assertFormError(
            response.context["form"],
            "longitude",
            "Longitude must be between -180 and 180.",
        )
        self.assertEqual(self.customer_a.addresses.count(), 0)

    def test_customer_cannot_access_another_customers_address(self):
        address_b = create_customer_delivery_address(
            customer=self.customer_b,
            data={
                "label": AddressLabel.HOME,
                "recipient_name": "Bob Secret",
                "phone_number": "9222222222",
                "line1": "99 Secret Lane",
                "line2": "",
                "landmark": "Hidden",
                "city": "Mysuru",
                "district": "Mysuru",
                "state": "Karnataka",
                "postal_code": "570001",
                "latitude": Decimal("12.295800"),
                "longitude": Decimal("76.639400"),
                "delivery_instructions": "Do not share",
                "is_default": True,
            },
        )
        self._login(self.user_a)
        self.assertEqual(self.client.get(self._edit_url(address_b.pk)).status_code, 404)
        self.assertEqual(self._post(self._edit_url(address_b.pk), self.valid_payload).status_code, 404)
        self.assertEqual(self._post(self._set_default_url(address_b.pk), {}).status_code, 404)
        self.assertEqual(self._post(self._deactivate_url(address_b.pk), {}).status_code, 404)

        address_b.refresh_from_db()
        self.assertEqual(address_b.recipient_name, "Bob Secret")
        self.assertTrue(address_b.is_active)
        self.assertTrue(address_b.is_default)

    def test_list_isolation_between_customers(self):
        create_customer_delivery_address(
            customer=self.customer_a,
            data={
                "label": AddressLabel.HOME,
                "recipient_name": "Alice Only",
                "phone_number": "9111111111",
                "line1": "Alice Isolation St",
                "line2": "",
                "landmark": "",
                "city": "Bengaluru",
                "district": "",
                "state": "Karnataka",
                "postal_code": "560001",
                "latitude": Decimal("12.971600"),
                "longitude": Decimal("77.594600"),
                "delivery_instructions": "",
                "is_default": True,
            },
        )
        create_customer_delivery_address(
            customer=self.customer_b,
            data={
                "label": AddressLabel.HOME,
                "recipient_name": "Bob Only",
                "phone_number": "9222222222",
                "line1": "Bob Isolation St",
                "line2": "",
                "landmark": "",
                "city": "Mysuru",
                "district": "",
                "state": "Karnataka",
                "postal_code": "570001",
                "latitude": Decimal("12.295800"),
                "longitude": Decimal("77.639400"),
                "delivery_instructions": "",
                "is_default": True,
            },
        )

        self._login(self.user_a)
        response = self.client.get(self.list_url)
        self.assertContains(response, "Alice Isolation St")
        self.assertContains(response, "Alice Only")
        self.assertNotContains(response, "Bob Isolation St")
        self.assertNotContains(response, "Bob Only")

        qs = portal_customer_addresses_queryset(self.user_a)
        self.assertEqual(qs.count(), 1)
        self.assertTrue(qs.filter(customer=self.customer_a).exists())
        self.assertFalse(qs.filter(customer=self.customer_b).exists())

    def test_customer_id_in_form_cannot_reassign_ownership(self):
        self._login(self.user_a)
        payload = dict(self.valid_payload)
        payload["customer_id"] = self.customer_b.pk
        response = self._post(self.create_url, payload)
        self.assertEqual(response.status_code, 302)

        created = self.customer_a.addresses.get()
        self.assertEqual(created.customer_id, self.customer_a.pk)
        self.assertFalse(self.customer_b.addresses.exists())

    def test_edit_updates_own_address_only(self):
        address = create_customer_delivery_address(
            customer=self.customer_a,
            data={
                "label": AddressLabel.HOME,
                "recipient_name": "Alice",
                "phone_number": "9111111111",
                "line1": "Old Line",
                "line2": "",
                "landmark": "",
                "city": "Bengaluru",
                "district": "",
                "state": "Karnataka",
                "postal_code": "560001",
                "latitude": Decimal("12.971600"),
                "longitude": Decimal("77.594600"),
                "delivery_instructions": "",
                "is_default": True,
            },
        )
        self._login(self.user_a)
        payload = dict(self.valid_payload)
        payload.update(
            {
                "recipient_name": "Alice Edited",
                "line1": "Edited Street",
                "customer_id": self.customer_b.pk,
            }
        )
        response = self._post(self._edit_url(address.pk), payload)
        self.assertEqual(response.status_code, 302)
        address.refresh_from_db()
        address.address.refresh_from_db()
        self.assertEqual(address.recipient_name, "Alice Edited")
        self.assertEqual(address.address.line1, "Edited Street")
        self.assertEqual(address.customer_id, self.customer_a.pk)

    def test_anonymous_redirected_to_customer_login(self):
        response = self.client.get(self.list_url)
        self.assertEqual(response.status_code, 302)
        self.assertIn("/customer/login/", response.url)

    def test_create_rejects_missing_csrf(self):
        plain = Client(enforce_csrf_checks=True)
        plain.force_login(self.user_a)
        plain.get(self.create_url)
        response = plain.post(self.create_url, self.valid_payload)
        self.assertEqual(response.status_code, 403)
        self.assertEqual(self.customer_a.addresses.count(), 0)

    def test_clearing_default_on_edit_promotes_another_active_address(self):
        first = create_customer_delivery_address(
            customer=self.customer_a,
            data={
                "label": AddressLabel.HOME,
                "recipient_name": "Alice Home",
                "phone_number": "9111111111",
                "line1": "Home Lane",
                "line2": "",
                "landmark": "",
                "city": "Bengaluru",
                "district": "",
                "state": "Karnataka",
                "postal_code": "560001",
                "latitude": Decimal("12.971600"),
                "longitude": Decimal("77.594600"),
                "delivery_instructions": "",
                "is_default": True,
            },
        )
        second = create_customer_delivery_address(
            customer=self.customer_a,
            data={
                "label": AddressLabel.WORK,
                "recipient_name": "Alice Work",
                "phone_number": "9111111111",
                "line1": "Work Lane",
                "line2": "",
                "landmark": "",
                "city": "Bengaluru",
                "district": "",
                "state": "Karnataka",
                "postal_code": "560002",
                "latitude": Decimal("12.980000"),
                "longitude": Decimal("77.600000"),
                "delivery_instructions": "",
                "is_default": False,
            },
        )

        update_customer_delivery_address(
            customer_address=first,
            data={
                "label": AddressLabel.HOME,
                "recipient_name": "Alice Home",
                "phone_number": "9111111111",
                "line1": "Home Lane",
                "line2": "",
                "landmark": "",
                "city": "Bengaluru",
                "district": "",
                "state": "Karnataka",
                "postal_code": "560001",
                "latitude": Decimal("12.971600"),
                "longitude": Decimal("77.594600"),
                "delivery_instructions": "",
                "is_default": False,
            },
        )

        first.refresh_from_db()
        second.refresh_from_db()
        self.assertFalse(first.is_default)
        self.assertTrue(second.is_default)
        self.assertEqual(
            self.customer_a.addresses.filter(is_active=True, is_default=True).count(),
            1,
        )
