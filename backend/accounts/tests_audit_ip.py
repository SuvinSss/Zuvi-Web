from django.test import RequestFactory, SimpleTestCase

from accounts.audit_ip import get_client_ip


class GetClientIpTests(SimpleTestCase):
    def setUp(self):
        self.factory = RequestFactory()

    def test_returns_remote_addr_only(self):
        request = self.factory.get("/")
        request.META["REMOTE_ADDR"] = "127.0.0.1"
        self.assertEqual(get_client_ip(request), "127.0.0.1")

    def test_ignores_spoofed_x_forwarded_for(self):
        request = self.factory.get(
            "/",
            HTTP_X_FORWARDED_FOR="203.0.113.50, 198.51.100.1",
        )
        request.META["REMOTE_ADDR"] = "127.0.0.1"
        self.assertEqual(get_client_ip(request), "127.0.0.1")
        self.assertNotEqual(get_client_ip(request), "203.0.113.50")

    def test_none_request_returns_none(self):
        self.assertIsNone(get_client_ip(None))

    def test_missing_remote_addr_returns_none(self):
        request = self.factory.get("/")
        request.META.pop("REMOTE_ADDR", None)
        self.assertIsNone(get_client_ip(request))
