from unittest import mock

from django.test import SimpleTestCase


class SpaServingTests(SimpleTestCase):
    def test_unbuilt_frontend_gives_a_clear_503(self):
        with mock.patch("config.spa.INDEX") as index:
            index.read_text.side_effect = FileNotFoundError
            response = self.client.get("/app/customer/stores")
        self.assertEqual(response.status_code, 503)
        self.assertIn("npm", response.content.decode())

    def test_built_frontend_serves_index_for_client_routes(self):
        with mock.patch("config.spa.INDEX") as index:
            index.read_text.return_value = "<!doctype html><div id=root></div>"
            for url in ("/app/", "/app/admin/pricing"):
                response = self.client.get(url)
                self.assertEqual(response.status_code, 200)
                self.assertIn("root", response.content.decode())

    def test_only_get_is_allowed(self):
        self.assertEqual(self.client.post("/app/").status_code, 405)
