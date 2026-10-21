"""Reviews: eligibility, one-per-target, aggregates, moderation, privacy, store replies."""
from django.core.cache import cache
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from customers.models import RegistrationSource
from customers.services import create_customer_with_user
from deliveries.tests import DeliveryBase, jpeg, DROP_LAT, DROP_LON, STORE_LAT, STORE_LON
from deliveries import services as delivery_services
from orders.models import StoreOrderStatus
from notifications.models import Notification

from .models import RatingAggregate, Review, ReviewStatus, TargetType
from . import services


class ReviewBase(DeliveryBase):
    def setUp(self):
        super().setUp()
        self.partner = self.make_partner("review-rider")

    def deliver(self):
        delivery = self.accepted_delivery(self.partner)
        self.pickup(delivery, self.partner)
        delivery_services.complete_delivery(delivery.pk, self.partner, photos=[jpeg()], latitude=DROP_LAT, longitude=DROP_LON)
        self.store_order.refresh_from_db()
        return delivery

    def client_for(self, user):
        api = APIClient()
        api.force_authenticate(user)
        return api

    def review(self, **overrides):
        data = {"store_order": self.store_order.pk, "target_type": "STORE", "rating": 4, "title": "Good", "comment": "Fresh produce"}
        data.update(overrides)
        return self.client_for(self.customer_user).post("/api/v1/reviews/", data, format="json")

    def other_customer(self, name="rev-other"):
        return create_customer_with_user(
            user_data={"username": name, "email": f"{name}@example.com", "first_name": "Other", "last_name": "Person",
                       "phone_number": f"9100{abs(hash(name)) % 1000000:06d}", "password": "secure-password-123"},
            registration_source=RegistrationSource.WEBSITE)[1]


class EligibilityTests(ReviewBase):
    def test_cannot_review_before_delivery(self):
        self.ready_order()
        response = self.review()
        self.assertEqual(response.status_code, 400)
        self.assertEqual(Review.objects.count(), 0)

    def test_can_review_store_after_delivery_and_aggregate_updates(self):
        self.deliver()
        response = self.review(rating=5)
        self.assertEqual(response.status_code, 201, response.content)
        agg = RatingAggregate.objects.get(target_type="STORE", target_id=self.store.pk)
        self.assertEqual((agg.count, float(agg.average)), (1, 5.0))

    def test_one_review_per_target_per_order(self):
        self.deliver()
        self.assertEqual(self.review().status_code, 201)
        self.assertEqual(self.review(rating=1).status_code, 400)
        self.assertEqual(Review.objects.count(), 1)

    def test_other_customer_cannot_review_my_order(self):
        self.deliver()
        api = self.client_for(self.other_customer())
        response = api.post("/api/v1/reviews/", {"store_order": self.store_order.pk, "target_type": "STORE", "rating": 1}, format="json")
        self.assertEqual(response.status_code, 404)

    def test_rating_bounds_enforced(self):
        self.deliver()
        for bad in (0, 6, -1, "x"):
            self.assertEqual(self.review(rating=bad).status_code, 400, bad)

    def test_product_review_requires_product_in_order(self):
        self.deliver()
        item = self.store_order.items.first()
        self.assertEqual(self.review(target_type="PRODUCT", product=item.product_id, rating=3).status_code, 201)
        stranger = self.create_public_product(store=self.store, name="Not ordered")
        self.assertEqual(self.review(target_type="PRODUCT", product=stranger.pk).status_code, 400)
        self.assertEqual(self.review(target_type="PRODUCT").status_code, 400)

    def test_partner_review_requires_a_delivered_partner_delivery(self):
        delivery = self.deliver()
        self.assertEqual(self.review(target_type="DELIVERY_PARTNER", rating=5).status_code, 201)
        agg = RatingAggregate.objects.get(target_type="DELIVERY_PARTNER", target_id=delivery.partner_id)
        self.assertEqual(agg.count, 1)

    def test_html_is_stripped_from_text(self):
        self.deliver()
        response = self.review(title="<b>Hi</b>", comment="<script>alert(1)</script>Nice")
        body = response.json()
        self.assertEqual(body["title"], "Hi")
        self.assertNotIn("<", body["comment"])


class AggregateAndVisibilityTests(ReviewBase):
    def test_only_published_reviews_count_and_show_publicly(self):
        self.deliver()
        review_id = self.review(rating=5).json()["id"]
        anonymous = APIClient()
        listing = anonymous.get(f"/api/v1/public/stores/{self.store.pk}/reviews/").json()
        self.assertEqual(listing["count"], 1)
        self.assertEqual(listing["rating"]["count"], 1)
        row = listing["results"][0]
        self.assertEqual(row["reviewer"], "Delivery C.")
        self.assertNotIn("customer", row)
        self.assertNotIn("email", str(row))
        self.client_for(self.admin).post(f"/api/v1/admin/reviews/{review_id}/hide/", {"reason": "Abusive"}, format="json")
        listing = anonymous.get(f"/api/v1/public/stores/{self.store.pk}/reviews/").json()
        self.assertEqual((listing["count"], listing["rating"]["count"], listing["rating"]["average"]), (0, 0, 0.0))

    def test_aggregate_is_recomputed_across_edit_withdraw_and_restore(self):
        self.deliver()
        review_id = self.review(rating=5).json()["id"]
        api = self.client_for(self.customer_user)
        api.patch(f"/api/v1/reviews/{review_id}/", {"rating": 3}, format="json")
        self.assertEqual(float(RatingAggregate.objects.get().average), 3.0)
        api.delete(f"/api/v1/reviews/{review_id}/")
        self.assertEqual(RatingAggregate.objects.get().count, 0)
        self.assertEqual(Review.objects.get().status, ReviewStatus.WITHDRAWN)

    def test_average_over_multiple_reviews(self):
        self.deliver()
        self.review(rating=5)
        other_order_review = Review.objects.get()
        # a second published review on the same store from another order
        order2 = self.place_sample_order(token="tok-review-2")
        so2 = order2.store_orders.get()
        so2.status = StoreOrderStatus.COMPLETED
        so2.save()
        customer = order2.customer
        services.create_review(customer=customer, store_order=so2, target_type=TargetType.STORE, rating=2)
        agg = RatingAggregate.objects.get(target_type="STORE", target_id=self.store.pk)
        self.assertEqual((agg.count, float(agg.average)), (2, 3.5))
        self.assertEqual(agg.distribution["5"], 1)
        self.assertEqual(agg.distribution["2"], 1)

    def test_my_reviews_are_private_to_the_author(self):
        self.deliver()
        self.review()
        self.assertEqual(self.client_for(self.customer_user).get("/api/v1/reviews/mine/").json()["count"], 1)
        self.assertEqual(self.client_for(self.other_customer()).get("/api/v1/reviews/mine/").json()["count"], 0)
        review = Review.objects.get()
        self.assertEqual(self.client_for(self.other_customer("snoop")).patch(f"/api/v1/reviews/{review.pk}/", {"rating": 1}, format="json").status_code, 404)

    def test_edit_window_closes(self):
        self.deliver()
        review_id = self.review().json()["id"]
        Review.objects.filter(pk=review_id).update(created_at=timezone.now() - timezone.timedelta(days=30))
        response = self.client_for(self.customer_user).patch(f"/api/v1/reviews/{review_id}/", {"rating": 1}, format="json")
        self.assertEqual(response.status_code, 400)


class ModerationAndReplyTests(ReviewBase):
    def setUp(self):
        super().setUp()
        self.deliver()
        self.review_id = self.review(rating=1, comment="Rude").json()["id"]

    def test_only_admins_moderate_and_a_reason_is_required(self):
        for user in (self.customer_user, self.store_user, self.partner.user):
            self.assertEqual(self.client_for(user).post(f"/api/v1/admin/reviews/{self.review_id}/hide/", {"reason": "x"}, format="json").status_code, 403)
        admin = self.client_for(self.admin)
        self.assertEqual(admin.post(f"/api/v1/admin/reviews/{self.review_id}/hide/", {}, format="json").status_code, 400)
        ok = admin.post(f"/api/v1/admin/reviews/{self.review_id}/hide/", {"reason": "Contains abuse"}, format="json")
        self.assertEqual(ok.status_code, 200, ok.content)
        self.assertTrue(Notification.objects.filter(recipient=self.customer_user, kind="REVIEW_MODERATED").exists())
        from core.models import AuditEvent
        self.assertTrue(AuditEvent.objects.filter(action="review.hide", actor=self.admin).exists())
        restored = admin.post(f"/api/v1/admin/reviews/{self.review_id}/restore/", {}, format="json")
        self.assertEqual(restored.json()["status"], "PUBLISHED")
        self.assertEqual(RatingAggregate.objects.get(target_type="STORE").count, 1)

    def test_reports_flag_for_moderation_and_cannot_be_duplicated(self):
        reporter = self.other_customer("reporter")
        api = self.client_for(reporter)
        self.assertEqual(api.post(f"/api/v1/reviews/{self.review_id}/report/", {"reason": "ABUSIVE"}, format="json").status_code, 201)
        self.assertEqual(api.post(f"/api/v1/reviews/{self.review_id}/report/", {"reason": "SPAM"}, format="json").status_code, 400)
        self.assertEqual(self.client_for(self.customer_user).post(f"/api/v1/reviews/{self.review_id}/report/", {"reason": "SPAM"}, format="json").status_code, 400)
        listing = self.client_for(self.admin).get("/api/v1/admin/reviews/?reported=1").json()
        self.assertEqual(listing["count"], 1)
        self.assertEqual(listing["results"][0]["report_count"], 1)

    def test_store_can_reply_once_to_its_own_reviews_only(self):
        api = self.client_for(self.store_user)
        self.assertEqual(api.post(f"/api/v1/store/reviews/{self.review_id}/reply/", {"body": "Sorry to hear this"}, format="json").status_code, 201)
        self.assertEqual(api.post(f"/api/v1/store/reviews/{self.review_id}/reply/", {"body": "Again"}, format="json").status_code, 400)
        other = self.create_store_user(store=self.create_store(name="Rival Mart"), username="rival-store-user")
        self.assertEqual(self.client_for(other).post(f"/api/v1/store/reviews/{self.review_id}/reply/", {"body": "Spy"}, format="json").status_code, 404)
        public = APIClient().get(f"/api/v1/public/stores/{self.store.pk}/reviews/").json()["results"][0]
        self.assertEqual(public["reply"]["body"], "Sorry to hear this")

    def test_store_list_shows_only_own_published_reviews(self):
        self.assertEqual(self.client_for(self.store_user).get("/api/v1/store/reviews/").json()["count"], 1)
        other = self.create_store_user(store=self.create_store(name="Rival Mart 2"), username="rival2")
        self.assertEqual(self.client_for(other).get("/api/v1/store/reviews/").json()["count"], 0)

    def test_partner_sees_own_ratings_only(self):
        self.review(target_type="DELIVERY_PARTNER", rating=4)
        self.assertEqual(self.client_for(self.partner.user).get("/api/v1/delivery/ratings/").json()["count"], 1)
        rival = self.make_partner("rating-rival")
        self.assertEqual(self.client_for(rival.user).get("/api/v1/delivery/ratings/").json()["count"], 0)
