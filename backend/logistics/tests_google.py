"""Google Maps Platform providers with recorded-shape responses (no network, no billing)."""
from decimal import Decimal
from unittest import mock

from django.test import SimpleTestCase, override_settings

from logistics import providers
from logistics.tests_api import Base, NEAR

GOOGLE = dict(LOCATION_GEOCODER="google", LOCATION_ROUTER="google", GOOGLE_MAPS_SERVER_KEY="test-key")

AUTOCOMPLETE = {"suggestions": [
    {"placePrediction": {"placeId": "ChIJabc123", "text": {"text": "Paravur Market, Paravur, Kerala, India"},
                         "structuredFormat": {"mainText": {"text": "Paravur Market"}, "secondaryText": {"text": "Paravur, Kerala, India"}}}},
    {"queryPrediction": {"text": {"text": "paravur"}}},  # query predictions are ignored
]}
DETAILS = {"id": "ChIJabc123", "formattedAddress": "Market Rd, Paravur, Kerala 691301, India", "location": {"latitude": 8.8932, "longitude": 76.6141},
           "addressComponents": [{"longText": "Market Road", "shortText": "Market Rd", "types": ["route"]},
                                 {"longText": "Paravur", "shortText": "Paravur", "types": ["locality", "political"]},
                                 {"longText": "Kollam", "shortText": "Kollam", "types": ["administrative_area_level_2", "political"]},
                                 {"longText": "Kerala", "shortText": "KL", "types": ["administrative_area_level_1", "political"]},
                                 {"longText": "691301", "shortText": "691301", "types": ["postal_code"]}]}
GEOCODE = {"status": "OK", "results": [{"formatted_address": "Beach Rd, Paravur, Kerala 691301, India", "place_id": "ChIJxyz",
            "geometry": {"location": {"lat": 8.89, "lng": 76.61}},
            "address_components": [{"long_name": "Paravur", "short_name": "Paravur", "types": ["locality"]},
                                   {"long_name": "Kerala", "short_name": "KL", "types": ["administrative_area_level_1"]},
                                   {"long_name": "691301", "short_name": "691301", "types": ["postal_code"]}]}]}


class GoogleProviderUnitTests(SimpleTestCase):
    def test_autocomplete_request_and_parsing(self):
        g = providers.GoogleGeocoder("k")
        with mock.patch.object(providers, "_http_post_json", return_value=AUTOCOMPLETE) as post:
            out = g.search("Paravur", session="sess-1", near=(Decimal("8.9"), Decimal("76.6")))
        url, body, headers = post.call_args.args
        self.assertTrue(url.endswith("/places:autocomplete"))
        self.assertEqual((body["includedRegionCodes"], body["sessionToken"]), (["in"], "sess-1"))
        self.assertIn("locationBias", body)
        self.assertEqual(headers["X-Goog-Api-Key"], "k")
        self.assertEqual(len(out), 1)
        self.assertEqual((out[0].place_id, out[0].line1, out[0].as_dict()["needs_details"]), ("ChIJabc123", "Paravur Market", True))

    def test_details_fieldmask_and_components(self):
        g = providers.GoogleGeocoder("k")
        with mock.patch.object(providers, "_http_get_json", return_value=DETAILS) as get:
            p = g.details("ChIJabc123", session="sess-1")
        url, params, headers = get.call_args.args
        self.assertTrue(url.endswith("/places/ChIJabc123"))
        self.assertEqual(params["sessionToken"], "sess-1")
        self.assertEqual(headers["X-Goog-FieldMask"], "id,formattedAddress,location,addressComponents")
        self.assertEqual((p.latitude, p.city, p.district, p.state, p.postal_code, p.line1), ("8.893200", "Paravur", "Kollam", "Kerala", "691301", "Market Road"))
        self.assertFalse(p.as_dict()["needs_details"])

    def test_details_rejects_bad_ids_and_missing_location(self):
        g = providers.GoogleGeocoder("k")
        with self.assertRaises(providers.ProviderUnavailable):
            g.details("../../etc")
        with mock.patch.object(providers, "_http_get_json", return_value={"id": "x"}):
            with self.assertRaises(providers.ProviderUnavailable):
                g.details("ChIJ1")

    def test_reverse_keeps_customer_pin(self):
        with mock.patch.object(providers, "_http_get_json", return_value=GEOCODE) as get:
            p = providers.GoogleGeocoder("k").reverse(Decimal("8.893200"), Decimal("76.614100"))
        self.assertEqual(get.call_args.args[1]["latlng"], "8.893200,76.614100")
        self.assertEqual((p.latitude, p.longitude, p.city, p.postal_code), ("8.893200", "76.614100", "Paravur", "691301"))
        with mock.patch.object(providers, "_http_get_json", return_value={"status": "ZERO_RESULTS", "results": []}):
            with self.assertRaises(providers.ProviderUnavailable):
                providers.GoogleGeocoder("k").reverse(1, 1)

    def test_routes_two_wheeler_distance(self):
        with mock.patch.object(providers, "_http_post_json", return_value={"routes": [{"distanceMeters": 4321, "duration": "600s"}]}) as post:
            km = providers.GoogleRouter("k").road_km((8.89, 76.61), (8.91, 76.63))
        url, body, headers = post.call_args.args
        self.assertEqual((body["travelMode"], headers["X-Goog-FieldMask"]), ("TWO_WHEELER", "routes.distanceMeters,routes.duration"))
        self.assertEqual(km, Decimal("4.321"))
        with mock.patch.object(providers, "_http_post_json", return_value={}):
            with self.assertRaises(providers.ProviderUnavailable):
                providers.GoogleRouter("k").road_km((8.89, 76.61), (8.91, 76.63))

    def test_without_a_key_google_is_off(self):
        with override_settings(LOCATION_GEOCODER="google", LOCATION_ROUTER="google", GOOGLE_MAPS_SERVER_KEY=""):
            self.assertEqual((providers.get_geocoder().name, providers.get_router().name), ("none", "none"))
        with override_settings(**GOOGLE):
            self.assertEqual((providers.get_geocoder().name, providers.get_router().name), ("google", "google"))

    def test_errors_never_carry_the_key(self):
        from urllib.error import HTTPError
        err = HTTPError("https://maps.googleapis.com/maps/api/geocode/json?key=SECRET", 403, "Forbidden", {}, None)
        with mock.patch.object(providers, "urlopen", side_effect=err):
            with self.assertRaises(providers.ProviderUnavailable) as ctx:
                providers._http_get_json(providers.GEOCODE_URL, {"key": "SECRET"}, {})
        self.assertNotIn("SECRET", str(ctx.exception))


@override_settings(**GOOGLE)
class GoogleApiTests(Base):
    def setUp(self):
        # Safety net: no test may reach Google (or any network). Unmocked calls behave like an outage.
        from urllib.error import URLError
        patcher = mock.patch.object(providers, "urlopen", side_effect=URLError("network disabled in tests"))
        patcher.start()
        self.addCleanup(patcher.stop)
        super().setUp()
    def test_config_endpoint_for_web_and_mobile_has_no_keys(self):
        r = self.client.get("/api/v1/geo/config/").json()
        self.assertEqual((r["map"], r["suggestions_need_details"], r["attribution"]), ("google", True, "Powered by Google"))
        self.assertNotIn("test-key", str(r))

    def test_config_serves_only_the_public_browser_key(self):
        with override_settings(GOOGLE_MAPS_BROWSER_KEY="web-key", GOOGLE_MAPS_MAP_ID="MAPID"):
            r = self.client.get("/api/v1/geo/config/").json()
        self.assertEqual((r["browser_key"], r["map_id"]), ("web-key", "MAPID"))
        self.assertNotIn("test-key", str(r))  # the server key never appears
        self.assertEqual(self.client.get("/api/v1/geo/config/").json()["browser_key"], "")

    def test_search_then_details_flow(self):
        with mock.patch.object(providers, "_http_post_json", return_value=AUTOCOMPLETE):
            r = self.client.get("/api/v1/geo/search/?q=Paravur&session=abc-123&lat=8.9&lon=76.6").json()
        self.assertTrue(r["results"][0]["needs_details"])
        with mock.patch.object(providers, "_http_get_json", return_value=DETAILS):
            d = self.client.get("/api/v1/geo/place/?id=ChIJabc123&session=abc-123").json()
        self.assertEqual(d["result"]["latitude"], "8.893200")
        with mock.patch.object(providers, "_http_get_json", side_effect=providers.ProviderUnavailable("x")):
            self.assertFalse(self.client.get("/api/v1/geo/place/?id=ChIJabc123").json()["available"])

    def test_checkout_uses_google_road_distance_and_falls_back_when_down(self):
        self.add_cart()
        with mock.patch.object(providers, "_http_post_json", return_value={"routes": [{"distanceMeters": 5200}]}):
            d = self.quote().json()["stores"][0]["delivery"]
        self.assertEqual((d["distance_km"], d["distance_source"]), ("5.20", "road"))
        with mock.patch.object(providers, "_http_post_json", side_effect=providers.ProviderUnavailable("timeout")):
            d = self.quote().json()["stores"][0]["delivery"]
        self.assertEqual(d["distance_source"], "estimated")

    def test_store_list_never_calls_paid_routing(self):
        with mock.patch.object(providers, "_http_post_json") as post:
            r = self.client.get(f"/api/v1/delivery/stores/?lat={NEAR[0]}&lon={NEAR[1]}").json()
        post.assert_not_called()
        self.assertTrue(any(s["serviceable"] for s in r["stores"]))

    def test_mobile_token_client_can_use_location_and_quote(self):
        from rest_framework.authtoken.models import Token
        from rest_framework.test import APIClient
        token = Token.objects.create(user=self.customer_user)
        app = APIClient()
        app.credentials(HTTP_AUTHORIZATION=f"Token {token.key}")
        self.assertEqual(app.get("/api/v1/geo/config/").status_code, 200)
        app.post("/api/v1/cart/items/", {"product_id": self.product.pk, "quantity": "1"}, format="json")
        with mock.patch.object(providers, "_http_post_json", return_value={"routes": [{"distanceMeters": 3000}]}):
            r = app.post("/api/v1/checkout/quote/", {"fulfillment_type": "DELIVERY", "delivery_address_id": self.address.pk}, format="json")
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(r.json()["stores"][0]["delivery"]["distance_km"], "3.00")
