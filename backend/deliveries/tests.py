"""Delivery domain: assignment, GPS tracking, evidence, state machine, access control."""
from datetime import timedelta
from decimal import Decimal
from io import BytesIO

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.utils import timezone
from PIL import Image
from rest_framework.test import APIClient

from accounts.models import Role
from customers.services import create_customer_with_user
from customers.models import RegistrationSource
from notifications.models import Notification
from orders.management_status import update_order_status
from orders.models import OrderStatus, StoreOrderStatus
from orders.store_status import accept_store_order, mark_store_order_processing, mark_store_order_ready
from orders.tests_delivery_workflow import DeliveryWorkflowTestMixin

from . import services
from .models import (
    AssignmentStatus,
    Delivery,
    DeliveryAssignment,
    DeliveryAttempt,
    DeliveryPartner,
    DeliveryStatus,
    EvidenceKind,
    PartnerStatus,
)

User = get_user_model()
STORE_LAT, STORE_LON = Decimal("12.971600"), Decimal("77.594600")  # test store address
DROP_LAT, DROP_LON = "12.971600", "77.594600"  # customer address used by the fixtures


def jpeg(name="proof.jpg", color=(200, 30, 30)):
    buffer = BytesIO()
    Image.new("RGB", (64, 48), color).save(buffer, "JPEG")
    return SimpleUploadedFile(name, buffer.getvalue(), content_type="image/jpeg")


class DeliveryBase(DeliveryWorkflowTestMixin, TestCase):
    def setUp(self):
        super().setUp()
        cache.clear()
        self.api = APIClient()

    # -- builders
    def make_partner(self, username, *, lat="12.9716", lon="77.5946", status=PartnerStatus.APPROVED, online=True,
                     located=True):
        user = User.objects.create_user(username=username, email=f"{username}@example.com", password="x",
                                        role=Role.DELIVERY_AGENT, phone_number=f"90000{abs(hash(username)) % 100000:05d}")
        return DeliveryPartner.objects.create(
            user=user, status=status, is_online=online,
            last_latitude=Decimal(lat) if located else None, last_longitude=Decimal(lon) if located else None,
            last_location_at=timezone.now() if located else None)

    def ready_order(self, assign=False):
        """Store marks the order ready; returns its Delivery (created by the hook)."""
        with self.captureOnCommitCallbacks(execute=assign):
            for step in (accept_store_order, mark_store_order_processing, mark_store_order_ready):
                step(store_order=self.store_order, store=self.store, actor=self.store_user)
        self.store_order.refresh_from_db()
        return Delivery.objects.get(store_order=self.store_order)

    def as_user(self, user):
        self.api.force_authenticate(user)
        return self.api

    def accepted_delivery(self, partner):
        delivery = self.ready_order()
        services.admin_assign(delivery.pk, partner.pk, actor=self.admin)
        services.accept_assignment(delivery.pk, partner)
        delivery.refresh_from_db()
        return delivery

    def pickup(self, delivery, partner, **extra):
        return services.confirm_pickup(delivery.pk, partner, photos=[jpeg()], latitude=STORE_LAT, longitude=STORE_LON, **extra)

    def deliver_payload(self, **overrides):
        data = {"latitude": DROP_LAT, "longitude": DROP_LON, "accuracy_m": "8", "recipient_name": "Delivery Customer",
                "photos": [jpeg("drop.jpg")]}
        data.update(overrides)
        return data


@override_settings(DELIVERY_MIN_PING_INTERVAL_SECONDS=0)
class CreationAndAssignmentTests(DeliveryBase):
    def test_delivery_is_created_when_store_marks_ready_and_only_then(self):
        self.assertFalse(Delivery.objects.exists())
        delivery = self.ready_order()
        self.assertEqual(delivery.status, DeliveryStatus.PENDING_ASSIGNMENT)
        self.assertEqual(delivery.attempts.get().number, 1)
        self.assertEqual(delivery.pickup_latitude, STORE_LAT)
        self.assertEqual(delivery.dropoff_latitude, Decimal(DROP_LAT))
        self.assertEqual(delivery.status_history.count(), 1)

    def test_ensure_delivery_is_idempotent(self):
        delivery = self.ready_order()
        self.assertEqual(services.ensure_delivery(self.store_order).pk, delivery.pk)
        self.assertEqual(Delivery.objects.count(), 1)

    def test_auto_assign_picks_nearest_eligible_partner(self):
        near = self.make_partner("near", lat="12.9720", lon="77.5950")
        self.make_partner("far", lat="13.2000", lon="77.9000")
        self.make_partner("offline", lat="12.9716", lon="77.5946", online=False)
        self.make_partner("pending", status=PartnerStatus.PENDING)
        self.make_partner("suspended", status=PartnerStatus.SUSPENDED)
        self.make_partner("nolocation", located=False)
        delivery = self.ready_order(assign=True)
        delivery.refresh_from_db()
        self.assertEqual(delivery.status, DeliveryStatus.OFFERED)
        self.assertEqual(delivery.partner_id, near.pk)
        offer = delivery.assignments.get()
        self.assertTrue(offer.automatic)
        self.assertGreater(offer.expires_at, timezone.now())
        self.assertTrue(Notification.objects.filter(recipient=near.user, kind="DELIVERY_OFFERED").exists())

    def test_no_partner_available_keeps_delivery_queued(self):
        delivery = self.ready_order(assign=True)
        delivery.refresh_from_db()
        self.assertEqual(delivery.status, DeliveryStatus.PENDING_ASSIGNMENT)

    def test_partner_with_active_delivery_is_not_offered_another(self):
        partner = self.make_partner("busy")
        delivery = self.accepted_delivery(partner)
        self.assertEqual(delivery.status, DeliveryStatus.ACCEPTED)
        other = self.create_second_delivery()
        self.assertIsNone(services.auto_assign(other.pk))

    def create_second_delivery(self):
        order = self.place_sample_order(token="tok-second")
        store_order = order.store_orders.get()
        for step in (accept_store_order, mark_store_order_processing, mark_store_order_ready):
            step(store_order=store_order, store=self.store, actor=self.store_user)
        return Delivery.objects.get(store_order=store_order)

    def test_accept_requires_the_offered_partner(self):
        partner, stranger = self.make_partner("p1"), self.make_partner("p2")
        delivery = self.ready_order()
        services.admin_assign(delivery.pk, partner.pk, actor=self.admin)
        response = self.as_user(stranger.user).post(f"/api/v1/deliveries/{delivery.pk}/accept/")
        self.assertEqual(response.status_code, 404)  # not even revealed to others
        response = self.as_user(partner.user).post(f"/api/v1/deliveries/{delivery.pk}/accept/")
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(response.json()["status"], "ACCEPTED")

    def test_reject_reoffers_to_next_partner_and_never_back_to_the_rejecter(self):
        first, second = self.make_partner("first", lat="12.9717"), self.make_partner("second", lat="12.9800")
        delivery = self.ready_order()
        services.admin_assign(delivery.pk, first.pk, actor=self.admin)
        with self.captureOnCommitCallbacks(execute=True):
            services.reject_assignment(delivery.pk, first, reason="Too far")
        delivery.refresh_from_db()
        self.assertEqual(delivery.partner_id, second.pk)
        self.assertEqual(delivery.status, DeliveryStatus.OFFERED)
        self.assertEqual(delivery.rejection_count, 1)
        self.assertEqual(delivery.assignments.filter(partner=first).get().status, AssignmentStatus.REJECTED)

    def test_expired_offer_is_released_and_reassigned(self):
        first, second = self.make_partner("a", lat="12.9717"), self.make_partner("b", lat="12.9800")
        delivery = self.ready_order()
        services.admin_assign(delivery.pk, first.pk, actor=self.admin)
        DeliveryAssignment.objects.update(expires_at=timezone.now() - timedelta(seconds=1))
        self.assertEqual(services.expire_stale_offers(), 1)
        delivery.refresh_from_db()
        self.assertEqual(delivery.partner_id, second.pk)
        self.assertEqual(delivery.assignments.filter(partner=first).get().status, AssignmentStatus.EXPIRED)
        with self.assertRaises(Exception):  # the late accept by the first partner is refused
            services.accept_assignment(delivery.pk, first)

    def test_late_accept_after_expiry_is_refused(self):
        partner = self.make_partner("late")
        delivery = self.ready_order()
        services.admin_assign(delivery.pk, partner.pk, actor=self.admin)
        DeliveryAssignment.objects.update(expires_at=timezone.now() - timedelta(seconds=1))
        response = self.as_user(partner.user).post(f"/api/v1/deliveries/{delivery.pk}/accept/")
        self.assertEqual(response.status_code, 400)

    @override_settings(DELIVERY_MAX_REJECTIONS=1)
    def test_repeated_rejection_flags_for_manual_assignment(self):
        first, _second = self.make_partner("r1", lat="12.9717"), self.make_partner("r2", lat="12.9800")
        delivery = self.ready_order()
        services.admin_assign(delivery.pk, first.pk, actor=self.admin)
        with self.captureOnCommitCallbacks(execute=True):
            services.reject_assignment(delivery.pk, first)
        delivery.refresh_from_db()
        self.assertEqual(delivery.status, DeliveryStatus.PENDING_ASSIGNMENT)
        self.assertTrue(delivery.needs_attention)
        self.assertTrue(Notification.objects.filter(recipient=self.admin, title__icontains="manual").exists())

    def test_admin_can_reassign_and_previous_partner_loses_access(self):
        first, second = self.make_partner("m1"), self.make_partner("m2")
        delivery = self.accepted_delivery(first)
        self.as_user(self.admin).post(f"/api/v1/admin/deliveries/{delivery.pk}/assign/", {"partner_id": second.pk}, format="json")
        delivery.refresh_from_db()
        self.assertEqual(delivery.partner_id, second.pk)
        self.assertEqual(delivery.assignments.filter(partner=first).get().status, AssignmentStatus.REVOKED)
        self.assertEqual(self.as_user(first.user).get(f"/api/v1/deliveries/{delivery.pk}/").status_code, 404)

    def test_admin_cannot_assign_unapproved_partner(self):
        pending = self.make_partner("pend", status=PartnerStatus.PENDING)
        delivery = self.ready_order()
        response = self.as_user(self.admin).post(f"/api/v1/admin/deliveries/{delivery.pk}/assign/", {"partner_id": pending.pk}, format="json")
        self.assertEqual(response.status_code, 400)


@override_settings(DELIVERY_MIN_PING_INTERVAL_SECONDS=0)
class EvidenceAndCompletionTests(DeliveryBase):
    def setUp(self):
        super().setUp()
        self.partner = self.make_partner("rider")

    def test_pickup_requires_a_photo(self):
        delivery = self.accepted_delivery(self.partner)
        response = self.as_user(self.partner.user).post(
            f"/api/v1/deliveries/{delivery.pk}/pickup/", {"latitude": "12.9716", "longitude": "77.5946"}, format="multipart")
        self.assertEqual(response.status_code, 400)
        self.assertIn("photos", response.json())
        delivery.refresh_from_db()
        self.assertEqual(delivery.status, DeliveryStatus.ACCEPTED)

    def test_pickup_moves_store_order_out_for_delivery_and_notifies_customer(self):
        delivery = self.accepted_delivery(self.partner)
        response = self.as_user(self.partner.user).post(
            f"/api/v1/deliveries/{delivery.pk}/pickup/",
            {"latitude": "12.9716", "longitude": "77.5946", "photos": [jpeg()]}, format="multipart")
        self.assertEqual(response.status_code, 200, response.content)
        self.store_order.refresh_from_db()
        self.assertEqual(self.store_order.status, StoreOrderStatus.OUT_FOR_DELIVERY)
        evidence = delivery.evidence.get()
        self.assertEqual((evidence.kind, evidence.photos.count()), (EvidenceKind.PICKUP, 1))
        self.assertTrue(evidence.within_tolerance)
        self.assertTrue(Notification.objects.filter(recipient=self.customer_user, kind="PICKUP_CONFIRMED").exists())

    def test_cannot_pick_up_an_order_the_store_has_not_marked_ready(self):
        delivery = self.accepted_delivery(self.partner)
        from orders.models import StoreOrder
        StoreOrder.objects.filter(pk=self.store_order.pk).update(status=StoreOrderStatus.PREPARING)
        with self.assertRaises(Exception):
            self.pickup(delivery, self.partner)

    def test_non_image_upload_is_rejected_and_nothing_is_stored(self):
        delivery = self.accepted_delivery(self.partner)
        bad = SimpleUploadedFile("proof.jpg", b"not an image at all", content_type="image/jpeg")
        response = self.as_user(self.partner.user).post(
            f"/api/v1/deliveries/{delivery.pk}/pickup/",
            {"latitude": "12.9716", "longitude": "77.5946", "photos": [bad]}, format="multipart")
        self.assertEqual(response.status_code, 400)
        self.assertEqual(delivery.evidence.count(), 0)
        delivery.refresh_from_db()
        self.assertEqual(delivery.status, DeliveryStatus.ACCEPTED)

    def test_invalid_coordinates_are_rejected(self):
        delivery = self.accepted_delivery(self.partner)
        response = self.as_user(self.partner.user).post(
            f"/api/v1/deliveries/{delivery.pk}/pickup/",
            {"latitude": "123.0", "longitude": "77.5946", "photos": [jpeg()]}, format="multipart")
        self.assertEqual(response.status_code, 400)

    def test_cannot_complete_without_photo_evidence(self):
        delivery = self.accepted_delivery(self.partner)
        self.pickup(delivery, self.partner)
        response = self.as_user(self.partner.user).post(
            f"/api/v1/deliveries/{delivery.pk}/complete/", {"latitude": DROP_LAT, "longitude": DROP_LON}, format="multipart")
        self.assertEqual(response.status_code, 400)
        self.order.refresh_from_db()
        self.assertNotEqual(self.order.status, OrderStatus.COMPLETED)
        self.assertIsNone(self.order.delivered_at)

    def test_cannot_complete_before_pickup(self):
        delivery = self.accepted_delivery(self.partner)
        response = self.as_user(self.partner.user).post(
            f"/api/v1/deliveries/{delivery.pk}/complete/", self.deliver_payload(), format="multipart")
        self.assertEqual(response.status_code, 400)

    def test_full_happy_path_completes_order_with_evidence(self):
        delivery = self.accepted_delivery(self.partner)
        self.pickup(delivery, self.partner)
        api = self.as_user(self.partner.user)
        self.assertEqual(api.post(f"/api/v1/deliveries/{delivery.pk}/arrive/").status_code, 200)
        response = api.post(f"/api/v1/deliveries/{delivery.pk}/complete/", self.deliver_payload(), format="multipart")
        self.assertEqual(response.status_code, 200, response.content)
        delivery.refresh_from_db()
        self.assertEqual(delivery.status, DeliveryStatus.DELIVERED)
        self.assertIsNotNone(delivery.delivered_at)
        self.store_order.refresh_from_db()
        self.order.refresh_from_db()
        self.assertEqual(self.store_order.status, StoreOrderStatus.COMPLETED)
        self.assertEqual(self.order.status, OrderStatus.COMPLETED)
        self.assertIsNotNone(self.order.delivered_at)
        proof = delivery.evidence.get(kind=EvidenceKind.DELIVERY)
        self.assertEqual(proof.photos.count(), 1)
        self.assertEqual(proof.recipient_name, "Delivery Customer")
        self.assertIsNotNone(proof.created_at)  # server timestamp
        self.assertTrue(proof.within_tolerance)
        self.assertEqual(delivery.attempts.get().outcome, DeliveryAttempt.Outcome.DELIVERED)
        self.assertTrue(Notification.objects.filter(recipient=self.customer_user, kind="DELIVERED").exists())
        history = list(delivery.status_history.values_list("new_status", flat=True))
        self.assertEqual(history, ["PENDING_ASSIGNMENT", "OFFERED", "ACCEPTED", "IN_TRANSIT", "ARRIVED", "DELIVERED"])

    def test_completed_delivery_cannot_be_completed_twice(self):
        delivery = self.accepted_delivery(self.partner)
        self.pickup(delivery, self.partner)
        services.complete_delivery(delivery.pk, self.partner, photos=[jpeg()], latitude=DROP_LAT, longitude=DROP_LON)
        response = self.as_user(self.partner.user).post(
            f"/api/v1/deliveries/{delivery.pk}/complete/", self.deliver_payload(), format="multipart")
        self.assertEqual(response.status_code, 400)
        self.assertEqual(delivery.evidence.filter(kind=EvidenceKind.DELIVERY).count(), 1)

    def test_far_away_completion_is_flagged_not_hidden(self):
        delivery = self.accepted_delivery(self.partner)
        self.pickup(delivery, self.partner)
        services.complete_delivery(delivery.pk, self.partner, photos=[jpeg()], latitude="13.5", longitude="78.5")
        proof = delivery.evidence.get(kind=EvidenceKind.DELIVERY)
        self.assertFalse(proof.within_tolerance)
        self.assertGreater(proof.distance_from_target_m, 1000)

    @override_settings(DELIVERY_ENFORCE_LOCATION_TOLERANCE=True)
    def test_enforced_tolerance_blocks_far_completion(self):
        delivery = self.accepted_delivery(self.partner)
        self.pickup(delivery, self.partner)
        with self.assertRaises(Exception):
            services.complete_delivery(delivery.pk, self.partner, photos=[jpeg()], latitude="13.5", longitude="78.5")
        delivery.refresh_from_db()
        self.assertEqual(delivery.status, DeliveryStatus.IN_TRANSIT)

    def test_admin_cannot_mark_order_delivered_without_delivery_evidence(self):
        delivery = self.accepted_delivery(self.partner)
        self.pickup(delivery, self.partner)
        with self.assertRaises(Exception) as ctx:
            update_order_status(order=self.order, new_status=OrderStatus.COMPLETED, actor=self.super_admin, reason="manual")
        self.assertIn("evidence", str(ctx.exception))
        self.order.refresh_from_db()
        self.assertNotEqual(self.order.status, OrderStatus.COMPLETED)

    def test_evidence_photos_are_private_and_access_controlled(self):
        delivery = self.accepted_delivery(self.partner)
        self.pickup(delivery, self.partner)
        services.complete_delivery(delivery.pk, self.partner, photos=[jpeg()], latitude=DROP_LAT, longitude=DROP_LON)
        pickup_photo = delivery.evidence.get(kind=EvidenceKind.PICKUP).photos.get()
        drop_photo = delivery.evidence.get(kind=EvidenceKind.DELIVERY).photos.get()
        url = lambda photo: f"/api/v1/evidence-photos/{photo.pk}/file/"
        self.assertNotIn("/media/", drop_photo.file.name)
        self.assertTrue(drop_photo.file.storage.exists(drop_photo.file.name))
        self.api.force_authenticate(None)
        self.assertIn(self.api.get(url(drop_photo)).status_code, (401, 403))  # anonymous
        ok = self.as_user(self.customer_user).get(url(drop_photo))
        self.assertEqual(ok.status_code, 200)
        self.assertEqual(ok["Cache-Control"], "private, no-store")
        self.assertEqual(ok["X-Content-Type-Options"], "nosniff")
        self.assertEqual(self.as_user(self.customer_user).get(url(pickup_photo)).status_code, 404)  # no pickup proof for customers
        self.assertEqual(self.as_user(self.store_user).get(url(pickup_photo)).status_code, 200)
        self.assertEqual(self.as_user(self.admin).get(url(drop_photo)).status_code, 200)
        self.assertEqual(self.as_user(self.partner.user).get(url(drop_photo)).status_code, 200)

    def test_other_customer_other_store_and_other_partner_cannot_see_evidence(self):
        delivery = self.accepted_delivery(self.partner)
        self.pickup(delivery, self.partner)
        photo = delivery.evidence.get().photos.get()
        other_customer = create_customer_with_user(
            user_data={"username": "nosy", "email": "nosy@example.com", "first_name": "N", "last_name": "N",
                       "phone_number": "9000000123", "password": "secure-password-123"},
            registration_source=RegistrationSource.WEBSITE)[1]
        other_store = self.create_store(name="Other Store")
        other_store_user = self.create_store_user(store=other_store, username="other-store-user")
        other_partner = self.make_partner("rival")
        for user in (other_customer, other_store_user, other_partner.user):
            api = self.as_user(user)
            self.assertEqual(api.get(f"/api/v1/evidence-photos/{photo.pk}/file/").status_code, 404, user.username)
            self.assertIn(api.get(f"/api/v1/deliveries/{delivery.pk}/evidence/").status_code, (403, 404), user.username)

    def test_store_can_confirm_pickup_only_for_its_own_delivery(self):
        delivery = self.accepted_delivery(self.partner)
        self.pickup(delivery, self.partner)
        other_store_user = self.create_store_user(store=self.create_store(name="Other"), username="osu")
        self.assertEqual(self.as_user(other_store_user).post(f"/api/v1/store/deliveries/{delivery.pk}/confirm-pickup/").status_code, 403)
        ok = self.as_user(self.store_user).post(f"/api/v1/store/deliveries/{delivery.pk}/confirm-pickup/")
        self.assertEqual(ok.status_code, 200, ok.content)
        self.assertIsNotNone(ok.json()["store_confirmed_at"])


@override_settings(DELIVERY_MIN_PING_INTERVAL_SECONDS=0, DELIVERY_REQUIRE_OTP=True)
class OtpTests(DeliveryBase):
    def test_wrong_code_is_counted_and_blocks_completion_until_correct(self):
        partner = self.make_partner("otp-rider")
        delivery = self.accepted_delivery(partner)
        self.pickup(delivery, partner)
        api = self.as_user(partner.user)
        bad = api.post(f"/api/v1/deliveries/{delivery.pk}/complete/", self.deliver_payload(otp="000000"), format="multipart")
        self.assertEqual(bad.status_code, 400)
        delivery.refresh_from_db()
        self.assertEqual((delivery.status, delivery.otp_failed_attempts), (DeliveryStatus.IN_TRANSIT, 1))
        customer_api = APIClient()
        customer_api.force_authenticate(self.customer_user)
        code = customer_api.get(f"/api/v1/orders/{self.order.pk}/tracking/").json()["deliveries"][0]["otp"]
        good = self.as_user(partner.user).post(f"/api/v1/deliveries/{delivery.pk}/complete/", self.deliver_payload(otp=code), format="multipart")
        self.assertEqual(good.status_code, 200, good.content)
        delivery.refresh_from_db()
        self.assertIsNotNone(delivery.otp_verified_at)

    @override_settings(DELIVERY_MAX_OTP_FAILURES=2)
    def test_lockout_after_too_many_wrong_codes(self):
        partner = self.make_partner("otp-lock")
        delivery = self.accepted_delivery(partner)
        self.pickup(delivery, partner)
        code = services.delivery_otp(delivery)
        api = self.as_user(partner.user)
        for _ in range(2):
            api.post(f"/api/v1/deliveries/{delivery.pk}/complete/", self.deliver_payload(otp="111111"), format="multipart")
        locked = api.post(f"/api/v1/deliveries/{delivery.pk}/complete/", self.deliver_payload(otp=code), format="multipart")
        self.assertEqual(locked.status_code, 400)
        delivery.refresh_from_db()
        self.assertNotEqual(delivery.status, DeliveryStatus.DELIVERED)

    def test_otp_is_not_shown_to_other_customers_or_before_pickup(self):
        partner = self.make_partner("otp-vis")
        delivery = self.accepted_delivery(partner)
        before = self.as_user(self.customer_user).get(f"/api/v1/orders/{self.order.pk}/tracking/").json()["deliveries"][0]
        self.assertNotIn("otp", before)
        self.pickup(delivery, partner)
        admin_view = self.as_user(self.admin).get(f"/api/v1/orders/{self.order.pk}/tracking/").json()["deliveries"][0]
        self.assertNotIn("otp", admin_view)


@override_settings(DELIVERY_MIN_PING_INTERVAL_SECONDS=0)
class TrackingTests(DeliveryBase):
    def setUp(self):
        super().setUp()
        self.partner = self.make_partner("tracker")

    def ping(self, delivery, lat="12.9720", lon="77.5950", user=None, **extra):
        return self.as_user(user or self.partner.user).post(
            f"/api/v1/deliveries/{delivery.pk}/location/", {"latitude": lat, "longitude": lon, **extra}, format="json")

    def test_location_recorded_with_server_timestamp_and_updates_partner(self):
        delivery = self.accepted_delivery(self.partner)
        response = self.ping(delivery, accuracy_m=12)
        self.assertEqual(response.status_code, 201, response.content)
        ping = delivery.pings.get()
        self.assertEqual(float(ping.latitude), 12.972)
        self.assertEqual(ping.accuracy_m, 12)
        self.assertIsNotNone(ping.recorded_at)
        self.partner.refresh_from_db()
        self.assertEqual(self.partner.last_latitude, Decimal("12.972000"))

    def test_other_partner_cannot_post_location(self):
        delivery = self.accepted_delivery(self.partner)
        rival = self.make_partner("rival-gps")
        self.assertEqual(self.ping(delivery, user=rival.user).status_code, 404)
        self.assertEqual(delivery.pings.count(), 0)

    def test_location_not_accepted_when_delivery_not_in_progress(self):
        delivery = self.ready_order()
        services.admin_assign(delivery.pk, self.partner.pk, actor=self.admin)
        self.assertEqual(self.ping(delivery).status_code, 400)  # only offered
        services.accept_assignment(delivery.pk, self.partner)
        self.pickup(delivery, self.partner)
        services.complete_delivery(delivery.pk, self.partner, photos=[jpeg()], latitude=DROP_LAT, longitude=DROP_LON)
        self.assertEqual(self.ping(delivery).status_code, 400)  # finished

    def test_invalid_and_imprecise_locations_rejected(self):
        delivery = self.accepted_delivery(self.partner)
        self.assertEqual(self.ping(delivery, lat="91", lon="10").status_code, 400)
        self.assertEqual(self.ping(delivery, lat="abc", lon="10").status_code, 400)
        self.assertEqual(self.ping(delivery, accuracy_m=-1).status_code, 400)
        self.assertEqual(self.ping(delivery, accuracy_m=99999).status_code, 400)
        self.assertEqual(delivery.pings.count(), 0)

    @override_settings(DELIVERY_MIN_PING_INTERVAL_SECONDS=60)
    def test_too_frequent_updates_are_rejected(self):
        delivery = self.accepted_delivery(self.partner)
        self.assertEqual(self.ping(delivery).status_code, 201)
        self.assertEqual(self.ping(delivery).status_code, 400)
        self.assertEqual(delivery.pings.count(), 1)

    def test_customer_tracking_shows_position_and_flags_stale_data(self):
        delivery = self.accepted_delivery(self.partner)
        self.ping(delivery)
        url = f"/api/v1/orders/{self.order.pk}/tracking/"
        fresh = self.as_user(self.customer_user).get(url).json()["deliveries"][0]
        self.assertEqual(fresh["status"], "ACCEPTED")
        self.assertFalse(fresh["location"]["is_stale"])
        self.assertEqual(fresh["partner"]["first_name"], self.partner.user.first_name)
        self.assertNotIn("phone", fresh["partner"])
        self.assertIsNone(fresh["eta"])  # no routing provider is configured; we never invent an ETA
        delivery.pings.update(recorded_at=timezone.now() - timedelta(minutes=10))
        stale = self.as_user(self.customer_user).get(url).json()["deliveries"][0]
        self.assertTrue(stale["location"]["is_stale"])
        self.assertGreaterEqual(stale["location"]["age_seconds"], 600)

    def test_no_location_yet_is_reported_as_stale_not_fabricated(self):
        self.accepted_delivery(self.partner)
        data = self.as_user(self.customer_user).get(f"/api/v1/orders/{self.order.pk}/tracking/").json()["deliveries"][0]
        self.assertTrue(data["location"]["is_stale"])
        self.assertNotIn("latitude", data["location"])

    def test_customer_cannot_track_someone_elses_order_or_read_gps_trail(self):
        delivery = self.accepted_delivery(self.partner)
        self.ping(delivery)
        other = create_customer_with_user(
            user_data={"username": "other-c", "email": "other-c@example.com", "first_name": "O", "last_name": "C",
                       "phone_number": "9000000456", "password": "secure-password-123"},
            registration_source=RegistrationSource.WEBSITE)[1]
        self.assertEqual(self.as_user(other).get(f"/api/v1/orders/{self.order.pk}/tracking/").status_code, 404)
        self.assertEqual(self.as_user(self.customer_user).get(f"/api/v1/deliveries/{delivery.pk}/tracking-history/").status_code, 403)
        self.assertEqual(self.as_user(self.store_user).get(f"/api/v1/deliveries/{delivery.pk}/tracking-history/").status_code, 403)

    def test_tracking_history_for_assigned_partner_and_admin_only(self):
        delivery = self.accepted_delivery(self.partner)
        for lat in ("12.9720", "12.9730", "12.9740"):
            self.ping(delivery, lat=lat)
        mine = self.as_user(self.partner.user).get(f"/api/v1/deliveries/{delivery.pk}/tracking-history/").json()
        self.assertEqual(mine["count"], 3)
        self.assertEqual([p["latitude"] for p in mine["results"]], ["12.972000", "12.973000", "12.974000"])
        self.assertEqual(self.as_user(self.admin).get(f"/api/v1/deliveries/{delivery.pk}/tracking-history/").json()["count"], 3)
        rival = self.make_partner("rival-hist")
        self.assertEqual(self.as_user(rival.user).get(f"/api/v1/deliveries/{delivery.pk}/tracking-history/").status_code, 404)

    def test_unauthenticated_requests_are_rejected(self):
        delivery = self.accepted_delivery(self.partner)
        self.api.force_authenticate(None)
        for method, url in (("get", f"/api/v1/orders/{self.order.pk}/tracking/"),
                            ("post", f"/api/v1/deliveries/{delivery.pk}/location/"),
                            ("get", f"/api/v1/deliveries/{delivery.pk}/tracking-history/")):
            self.assertIn(getattr(self.api, method)(url).status_code, (401, 403), url)

    def test_customer_sees_no_internal_notes_in_timeline(self):
        delivery = self.accepted_delivery(self.partner)
        data = self.as_user(self.customer_user).get(f"/api/v1/orders/{self.order.pk}/tracking/").json()["deliveries"][0]
        self.assertTrue(all(step["note"] == "" for step in data["timeline"]))


@override_settings(DELIVERY_MIN_PING_INTERVAL_SECONDS=0)
class FailureRetryCancelTests(DeliveryBase):
    def setUp(self):
        super().setUp()
        self.partner = self.make_partner("fail-rider")

    def in_transit(self):
        delivery = self.accepted_delivery(self.partner)
        self.pickup(delivery, self.partner)
        return delivery

    def test_failed_delivery_records_reason_and_does_not_complete_order(self):
        delivery = self.in_transit()
        response = self.as_user(self.partner.user).post(
            f"/api/v1/deliveries/{delivery.pk}/fail/", {"reason": "CUSTOMER_UNAVAILABLE", "note": "Rang twice"}, format="json")
        self.assertEqual(response.status_code, 200, response.content)
        delivery.refresh_from_db()
        self.assertEqual(delivery.status, DeliveryStatus.FAILED)
        attempt = delivery.attempts.get()
        self.assertEqual((attempt.outcome, attempt.failure_reason), (DeliveryAttempt.Outcome.FAILED, "CUSTOMER_UNAVAILABLE"))
        self.order.refresh_from_db()
        self.assertNotEqual(self.order.status, OrderStatus.COMPLETED)
        self.assertTrue(Notification.objects.filter(recipient=self.customer_user, kind="DELIVERY_FAILED").exists())

    def test_fail_requires_valid_reason_and_other_requires_note(self):
        delivery = self.in_transit()
        api = self.as_user(self.partner.user)
        self.assertEqual(api.post(f"/api/v1/deliveries/{delivery.pk}/fail/", {"reason": "BOGUS"}, format="json").status_code, 400)
        self.assertEqual(api.post(f"/api/v1/deliveries/{delivery.pk}/fail/", {"reason": "OTHER"}, format="json").status_code, 400)

    def test_cannot_fail_before_pickup(self):
        delivery = self.accepted_delivery(self.partner)
        response = self.as_user(self.partner.user).post(f"/api/v1/deliveries/{delivery.pk}/fail/", {"reason": "WRONG_ADDRESS"}, format="json")
        self.assertEqual(response.status_code, 400)

    def test_admin_retry_creates_new_attempt_requiring_fresh_evidence(self):
        delivery = self.in_transit()
        services.fail_delivery(delivery.pk, self.partner, reason="CUSTOMER_UNAVAILABLE")
        response = self.as_user(self.admin).post(f"/api/v1/admin/deliveries/{delivery.pk}/retry/")
        self.assertEqual(response.status_code, 200, response.content)
        delivery.refresh_from_db()
        self.assertEqual((delivery.status, delivery.attempt_number), (DeliveryStatus.PENDING_ASSIGNMENT, 2))
        self.assertEqual(delivery.attempts.count(), 2)
        self.assertIsNone(delivery.partner_id)
        services.admin_assign(delivery.pk, self.partner.pk, actor=self.admin)
        services.accept_assignment(delivery.pk, self.partner)
        # The first attempt's pickup evidence is not reused: the order is already out, so re-pickup is refused
        # until the store order is READY again; delivering needs a fresh in-transit state.
        with self.assertRaises(Exception):
            services.complete_delivery(delivery.pk, self.partner, photos=[jpeg()], latitude=DROP_LAT, longitude=DROP_LON)

    def test_retry_limit(self):
        delivery = self.in_transit()
        Delivery.objects.filter(pk=delivery.pk).update(attempt_number=3, status=DeliveryStatus.FAILED)
        with self.assertRaises(Exception):
            services.retry_delivery(delivery.pk, actor=self.admin)

    def test_only_admins_can_retry_assign_or_cancel(self):
        delivery = self.in_transit()
        services.fail_delivery(delivery.pk, self.partner, reason="WRONG_ADDRESS")
        for user in (self.partner.user, self.store_user, self.customer_user):
            api = self.as_user(user)
            self.assertEqual(api.post(f"/api/v1/admin/deliveries/{delivery.pk}/retry/").status_code, 403)
            self.assertEqual(api.post(f"/api/v1/admin/deliveries/{delivery.pk}/cancel/").status_code, 403)
            self.assertEqual(api.get("/api/v1/admin/deliveries/").status_code, 403)

    def test_cancelling_the_order_cancels_the_open_delivery(self):
        delivery = self.accepted_delivery(self.partner)
        from orders.cancellation import cancel_order_by_admin
        cancel_order_by_admin(order=self.order, actor=self.super_admin, reason="Customer asked")
        delivery.refresh_from_db()
        self.assertEqual(delivery.status, DeliveryStatus.CANCELLED)
        self.assertEqual(delivery.assignments.get().status, AssignmentStatus.REVOKED)


class PartnerAdminTests(DeliveryBase):
    def test_partner_lifecycle_and_reasons(self):
        partner = self.make_partner("new-partner", status=PartnerStatus.PENDING, online=False)
        api = self.as_user(self.admin)
        self.assertEqual(api.post(f"/api/v1/admin/delivery-partners/{partner.pk}/reject/", {}, format="json").status_code, 400)
        self.assertEqual(api.post(f"/api/v1/admin/delivery-partners/{partner.pk}/approve/", {}, format="json").status_code, 200)
        partner.refresh_from_db()
        self.assertTrue(partner.is_approved)
        self.assertEqual(partner.approved_by, self.admin)
        self.assertEqual(api.post(f"/api/v1/admin/delivery-partners/{partner.pk}/suspend/", {"reason": "Complaints"}, format="json").status_code, 200)
        partner.refresh_from_db()
        self.assertFalse(partner.is_approved)
        self.assertFalse(partner.is_online)

    def test_unapproved_partner_cannot_use_delivery_endpoints(self):
        partner = self.make_partner("unapproved", status=PartnerStatus.PENDING)
        api = self.as_user(partner.user)
        self.assertEqual(api.get("/api/v1/delivery/assignments/").status_code, 403)
        self.assertEqual(api.post("/api/v1/delivery/me/online/", {"is_online": True}, format="json").status_code, 403)
        self.assertEqual(api.get("/api/v1/delivery/me/").status_code, 200)  # may view own onboarding status

    def test_going_online_needs_a_location(self):
        partner = self.make_partner("nolocation2", located=False, online=False)
        api = self.as_user(partner.user)
        self.assertEqual(api.post("/api/v1/delivery/me/online/", {"is_online": True}, format="json").status_code, 400)
        ok = api.post("/api/v1/delivery/me/online/", {"is_online": True, "latitude": "12.9", "longitude": "77.5"}, format="json")
        self.assertEqual(ok.status_code, 200)
        self.assertTrue(ok.json()["is_online"])

    def test_partner_customer_details_hidden_until_accepted(self):
        partner = self.make_partner("privacy")
        delivery = self.ready_order()
        services.admin_assign(delivery.pk, partner.pk, actor=self.admin)
        offered = self.as_user(partner.user).get(f"/api/v1/deliveries/{delivery.pk}/").json()
        self.assertIsNone(offered["customer"])
        self.assertNotIn("line1", offered["dropoff"])
        services.accept_assignment(delivery.pk, partner)
        accepted = self.as_user(partner.user).get(f"/api/v1/deliveries/{delivery.pk}/").json()
        self.assertEqual(accepted["customer"]["name"], "Delivery Customer")
        self.assertIn("line1", accepted["dropoff"])

    def test_admin_list_filters_and_search(self):
        self.ready_order()
        api = self.as_user(self.admin)
        self.assertEqual(api.get("/api/v1/admin/deliveries/?status=PENDING_ASSIGNMENT").json()["count"], 1)
        self.assertEqual(api.get("/api/v1/admin/deliveries/?status=DELIVERED").json()["count"], 0)
        self.assertEqual(api.get(f"/api/v1/admin/deliveries/?q={self.order.order_number}").json()["count"], 1)
