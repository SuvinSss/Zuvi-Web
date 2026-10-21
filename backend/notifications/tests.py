from django.core import mail
from django.test import override_settings

from notifications import services
from notifications.models import EmailStatus, Notification
from platform_api.tests import ApiTestBase


class NotificationApiTests(ApiTestBase):
    def test_users_only_see_and_read_their_own_notifications(self):
        mine = services.notify(self.customer.user if hasattr(self.customer, "user") else self.customer, "test", "Hello", email=False)
        theirs = services.notify(self.store_user, "test", "Secret", email=False)
        user = mine.recipient
        api = self.as_(user)
        data = api.get("/api/v1/notifications/").json()
        self.assertEqual([n["title"] for n in data["results"]], ["Hello"])
        self.assertEqual(api.post(f"/api/v1/notifications/{theirs.pk}/read/").status_code, 404)
        theirs.refresh_from_db()
        self.assertFalse(theirs.is_read)
        self.assertEqual(api.get("/api/v1/notifications/unread-count/").json()["unread"], 1)
        self.assertEqual(api.post(f"/api/v1/notifications/{mine.pk}/read/").status_code, 200)
        self.assertEqual(api.get("/api/v1/notifications/unread-count/").json()["unread"], 0)

    def test_anonymous_is_rejected(self):
        self.assertIn(self.as_(None).get("/api/v1/notifications/").status_code, (401, 403))

    def test_read_all_and_unread_filter(self):
        for i in range(3):
            services.notify(self.store_user, "test", f"n{i}", email=False)
        api = self.as_(self.store_user)
        before = api.get("/api/v1/notifications/?unread=1").json()["count"]
        self.assertGreaterEqual(before, 3)
        self.assertEqual(api.post("/api/v1/notifications/read-all/").json()["updated"], before)
        self.assertEqual(api.get("/api/v1/notifications/?unread=1").json()["count"], 0)

    def test_preferences_round_trip(self):
        api = self.as_(self.store_user)
        self.assertTrue(api.get("/api/v1/notifications/preferences/").json()["email_enabled"])
        api.put("/api/v1/notifications/preferences/", {"email_enabled": False}, format="json")
        self.assertFalse(api.get("/api/v1/notifications/preferences/").json()["email_enabled"])


class NotificationEmailTests(ApiTestBase):
    @override_settings(NOTIFICATION_EMAIL_ENABLED=False)
    def test_email_not_attempted_when_channel_disabled(self):
        with self.captureOnCommitCallbacks(execute=True):
            n = services.notify(self.store_user, "t", "x")
        self.assertEqual(len(mail.outbox), 0)
        self.assertEqual(n.email_status, EmailStatus.SKIPPED)

    @override_settings(NOTIFICATION_EMAIL_ENABLED=True, EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
    def test_email_sent_after_commit_and_respects_preference(self):
        self.store_user.email = "s@example.com"
        self.store_user.save()
        with self.captureOnCommitCallbacks(execute=True):
            n = services.notify(self.store_user, "t", "Hi")
        self.assertEqual(len(mail.outbox), 1)
        n.refresh_from_db()
        self.assertEqual(n.email_status, EmailStatus.SENT)
        self.as_(self.store_user).put("/api/v1/notifications/preferences/", {"email_enabled": False}, format="json")
        with self.captureOnCommitCallbacks(execute=True):
            services.notify(self.store_user, "t", "Again")
        self.assertEqual(len(mail.outbox), 1)

    @override_settings(NOTIFICATION_EMAIL_ENABLED=True, EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
    def test_email_failure_is_recorded_not_raised(self):
        from unittest import mock

        self.store_user.email = "s@example.com"
        self.store_user.save()
        with mock.patch("notifications.services.send_mail", side_effect=OSError("smtp down")):
            with self.captureOnCommitCallbacks(execute=True):
                n = services.notify(self.store_user, "t", "Hi")
        n.refresh_from_db()
        self.assertEqual(n.email_status, EmailStatus.FAILED)
        self.assertTrue(Notification.objects.filter(pk=n.pk).exists())
