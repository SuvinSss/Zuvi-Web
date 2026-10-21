from decimal import Decimal

from django.test import Client, TestCase
from django.urls import reverse

from customers.models import RegistrationSource
from customers.services import create_customer_delivery_address, create_customer_with_user


class SavedAddressSelectionTests(TestCase):
    def setUp(self):
        self.customer, self.user = create_customer_with_user(
            user_data={"username": "location-owner", "email": "owner@example.com", "first_name": "Test", "phone_number": "9000000001", "password": "example-pass-456"},
            registration_source=RegistrationSource.WEBSITE,
        )
        self.other_customer, self.other_user = create_customer_with_user(
            user_data={"username": "location-other", "email": "other@example.com", "phone_number": "9000000002", "password": "example-pass-456"},
            registration_source=RegistrationSource.WEBSITE,
        )
        self.payload = {
            "label": "HOME", "recipient_name": "Test", "phone_number": "9000000001",
            "line1": "Test Street", "line2": "", "landmark": "", "city": "Bengaluru",
            "district": "", "state": "Karnataka", "postal_code": "560001",
            "latitude": Decimal("12.971600"), "longitude": Decimal("77.594600"),
            "delivery_instructions": "", "is_default": True,
        }
        self.address = create_customer_delivery_address(customer=self.customer, data=self.payload)
        self.url = reverse("locations:select_saved_address", args=[self.address.pk])
        self.client.force_login(self.user)

    def test_select_uses_owned_address_coordinates_not_browser_values(self):
        response = self.client.post(self.url, {"latitude": "0", "longitude": "0", "next": "https://evil.example"})
        self.assertRedirects(response, "/", fetch_redirect_response=False)
        selected = self.client.session["delivery_location"]
        self.assertEqual(selected["address_id"], self.address.pk)
        self.assertEqual(selected["latitude"], "12.971600")
        self.assertIn("Test Street", selected["label"])

    def test_other_customer_cannot_select_or_see_address(self):
        self.client.force_login(self.other_user)
        self.assertEqual(self.client.post(self.url).status_code, 404)
        response = self.client.get(reverse("customers:customer_portal_address_list"))
        self.assertNotContains(response, "Test Street")

    def test_inactive_address_cannot_be_selected(self):
        self.address.is_active = False
        self.address.save()
        self.assertEqual(self.client.post(self.url).status_code, 404)

    def test_post_login_and_csrf_required(self):
        self.assertEqual(self.client.get(self.url).status_code, 405)
        csrf_client = Client(enforce_csrf_checks=True)
        csrf_client.force_login(self.user)
        self.assertEqual(csrf_client.post(self.url).status_code, 403)
        self.client.logout()
        self.assertEqual(self.client.post(self.url).status_code, 302)

    def test_modal_lists_owned_saved_address(self):
        response = self.client.get(reverse("customers:customer_portal_address_list"))
        self.assertContains(response, 'data-saved-address-url="' + self.url + '"')
        self.assertContains(response, "Select location manually")
        self.assertContains(response, "Add a new address")

    def test_selected_point_prefills_create_and_save_updates_header(self):
        self.client.post(reverse("locations:set_delivery_location"), {
            "latitude": "10.123456", "longitude": "76.123456", "label": "Test point",
        })
        create_url = reverse("customers:customer_portal_address_create")
        response = self.client.get(create_url, {"from_location": "1"})
        self.assertEqual(response.context["form"]["latitude"].value(), "10.123456")
        response = self.client.post(create_url, {**self.payload, "from_location": "1"})
        self.assertEqual(response.status_code, 302)
        selected = self.client.session["delivery_location"]
        self.assertNotEqual(selected["address_id"], self.address.pk)
        self.assertEqual(self.customer.addresses.filter(is_active=True, is_default=True).count(), 1)

    def test_nonfinite_coordinates_rejected(self):
        for latitude in ("NaN", "Infinity", "-Infinity", "sNaN"):
            response = self.client.post(reverse("locations:set_delivery_location"), {
                "latitude": latitude, "longitude": "0",
            }, HTTP_X_REQUESTED_WITH="XMLHttpRequest")
            self.assertEqual(response.status_code, 400)
