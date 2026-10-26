import logging

import requests
from django.test import SimpleTestCase, override_settings

from . import google_client
from .errors import (
    AmbiguousRoute,
    GeocodeNotFound,
    MapsBadResponse,
    MapsKeyRejected,
    MapsNetworkError,
    MapsNotConfigured,
    MapsQuotaExceeded,
    MapsTimeout,
    NoRouteFound,
)
from .testing import (
    TEST_SERVER_KEY,
    GoogleFakeMixin,
    coord,
    geocode_ok,
    matrix_ok,
    route_ok,
)

A, B = coord(8.8139, 76.6672), coord(8.8300, 76.7000)


class ConfigurationTests(SimpleTestCase):
    @override_settings(GOOGLE_MAPS_SERVER_API_KEY="")
    def test_missing_server_key_is_reported_not_ignored(self):
        with self.assertRaises(MapsNotConfigured):
            google_client.compute_route(A, B)
        with self.assertRaises(MapsNotConfigured):
            google_client.reverse_geocode(A)

    @override_settings(GOOGLE_MAPS_SERVER_API_KEY="", GOOGLE_MAPS_BROWSER_API_KEY="browser-only")
    def test_browser_key_is_never_used_as_server_key(self):
        with self.assertRaises(MapsNotConfigured):
            google_client.compute_route(A, B)


class GeocodingTests(GoogleFakeMixin, SimpleTestCase):
    def test_reverse_geocode_normalises_components(self):
        self.google.push(*geocode_ok())
        result = google_client.reverse_geocode(A)
        self.assertEqual(result.components["locality"], "Paravur")
        self.assertEqual(result.components["line1"], "12 Test Road")
        self.assertEqual(result.components["postal_code"], "691301")
        self.assertTrue(result.is_precise)
        call = self.google.calls[0]
        self.assertEqual(call["params"]["latlng"], "8.813900,76.667200")
        self.assertEqual(call["params"]["region"], "in")

    def test_approximate_result_is_not_precise(self):
        self.google.push(*geocode_ok(location_type="APPROXIMATE"))
        self.assertFalse(google_client.reverse_geocode(A).is_precise)

    def test_zero_results(self):
        self.google.push(200, {"status": "ZERO_RESULTS", "results": []})
        with self.assertRaises(GeocodeNotFound):
            google_client.reverse_geocode(A)

    def test_denied_quota_and_invalid_statuses(self):
        for status, exc in (("REQUEST_DENIED", MapsKeyRejected), ("OVER_QUERY_LIMIT", MapsQuotaExceeded),
                            ("OVER_DAILY_LIMIT", MapsQuotaExceeded), ("INVALID_REQUEST", MapsBadResponse),
                            ("UNKNOWN_ERROR", MapsBadResponse)):
            self.google.push(200, {"status": status, "error_message": f"bad key {TEST_SERVER_KEY}"})
            with self.assertRaises(exc):
                google_client.reverse_geocode(A)

    def test_non_json_body_is_a_bad_response(self):
        self.google.push(200, None)
        with self.assertRaises(MapsBadResponse):
            google_client.reverse_geocode(A)

    def test_forward_geocode_rejects_blank_and_huge_input_without_calling_google(self):
        for text in ("", "   ", "x" * 301):
            with self.assertRaises(GeocodeNotFound):
                google_client.geocode_address(text)
        self.assertEqual(self.google.calls, [])


class RoutesTests(GoogleFakeMixin, SimpleTestCase):
    def test_route_uses_header_key_field_mask_and_region(self):
        self.google.push(*route_ok(3200, 480))
        route = google_client.compute_route(A, B)
        self.assertEqual((route.distance_meters, route.duration_seconds), (3200, 480))
        call = self.google.calls[0]
        self.assertEqual(call["headers"]["X-Goog-Api-Key"], TEST_SERVER_KEY)
        self.assertEqual(call["headers"]["X-Goog-FieldMask"], "routes.distanceMeters,routes.duration")
        self.assertNotIn("key", call["params"])
        self.assertNotIn(TEST_SERVER_KEY, call["url"])
        self.assertEqual(call["json"]["regionCode"], "IN")
        self.assertEqual(call["json"]["travelMode"], "TWO_WHEELER")
        self.assertEqual(call["json"]["routingPreference"], "TRAFFIC_UNAWARE")

    def test_zero_metre_route_omits_distance_field(self):
        self.google.push(200, {"routes": [{"duration": "0s"}]})
        route = google_client.compute_route(A, A)
        self.assertEqual(route.distance_meters, 0)

    def test_empty_routes_is_no_route(self):
        self.google.push(200, {})
        with self.assertRaises(NoRouteFound):
            google_client.compute_route(A, B)

    def test_multiple_routes_for_single_route_request_is_ambiguous(self):
        self.google.push(200, {"routes": [{"distanceMeters": 1, "duration": "1s"}] * 2})
        with self.assertRaises(AmbiguousRoute):
            google_client.compute_route(A, B)

    def test_route_without_duration_is_ambiguous(self):
        self.google.push(200, {"routes": [{"distanceMeters": 100}]})
        with self.assertRaises(AmbiguousRoute):
            google_client.compute_route(A, B)

    def test_http_errors_are_classified_and_never_leak_the_key(self):
        cases = [
            (403, {"error": {"status": "PERMISSION_DENIED", "message": f"key {TEST_SERVER_KEY} blocked"}}, MapsKeyRejected),
            (401, {"error": {"status": "UNAUTHENTICATED", "message": "no"}}, MapsKeyRejected),
            (429, {"error": {"status": "RESOURCE_EXHAUSTED", "message": "quota"}}, MapsQuotaExceeded),
            (404, {"error": {"status": "NOT_FOUND", "message": "none"}}, NoRouteFound),
            (400, {"error": {"status": "INVALID_ARGUMENT", "message": "bad"}}, MapsBadResponse),
            (503, None, MapsBadResponse),
        ]
        for status, body, exc in cases:
            self.google.push(status, body)
            with self.assertLogs("geo.google", level=logging.WARNING) as logs, self.assertRaises(exc) as ctx:
                google_client.compute_route(A, B)
            self.assertNotIn(TEST_SERVER_KEY, str(ctx.exception))
            self.assertNotIn(TEST_SERVER_KEY, ctx.exception.public_message)
            self.assertNotIn(TEST_SERVER_KEY, "\n".join(logs.output))

    def test_timeout_and_network_failure(self):
        self.google.push(0, raises=MapsTimeout("t"))
        with self.assertRaises(MapsTimeout):
            google_client.compute_route(A, B)
        self.google.push(0, raises=MapsNetworkError("n"))
        with self.assertRaises(MapsNetworkError):
            google_client.compute_route(A, B)


class TransportSecurityTests(SimpleTestCase):
    def test_requests_exceptions_do_not_leak_the_url_with_the_key(self):
        transport = google_client.GoogleTransport()
        from unittest.mock import patch

        secret_url = f"https://maps.googleapis.com/x?key={TEST_SERVER_KEY}"
        for raised, expected in ((requests.Timeout(secret_url), MapsTimeout),
                                 (requests.ConnectionError(secret_url), MapsNetworkError)):
            with patch("geo.google_client.requests.request", side_effect=raised):
                with self.assertRaises(expected) as ctx:
                    transport.request("GET", "https://example.test", params={"key": TEST_SERVER_KEY})
            self.assertNotIn(TEST_SERVER_KEY, str(ctx.exception))
            self.assertIsNone(ctx.exception.__cause__)


class MatrixTests(GoogleFakeMixin, SimpleTestCase):
    def test_elements_are_validated_individually(self):
        origins = [A, B, coord(8.9, 76.7)]
        self.google.push(200, [
            {"originIndex": 0, "destinationIndex": 0, "status": {}, "condition": "ROUTE_EXISTS",
             "distanceMeters": 1000, "duration": "100s"},
            {"originIndex": 1, "destinationIndex": 0, "status": {"code": 5, "message": "nope"},
             "condition": "ROUTE_NOT_FOUND"},
            # origin 2 is missing from the response entirely
        ])
        elements = google_client.compute_route_matrix(origins, [coord(8.85, 76.69)])
        self.assertEqual([e.ok for e in elements], [True, False, False])
        self.assertEqual(elements[2].condition, "MISSING")
        self.assertEqual(self.google.calls[0]["headers"]["X-Goog-FieldMask"],
                         "originIndex,destinationIndex,duration,distanceMeters,status,condition")

    def test_ok_condition_without_duration_is_not_trusted(self):
        self.google.push(200, [{"originIndex": 0, "destinationIndex": 0, "status": {},
                                "condition": "ROUTE_EXISTS", "distanceMeters": 5}])
        (element,) = google_client.compute_route_matrix([A], [B])
        self.assertFalse(element.ok)

    def test_out_of_range_indices_are_ignored(self):
        self.google.push(*matrix_ok([(5, 0, 1, 1)]))
        (element,) = google_client.compute_route_matrix([A], [B])
        self.assertFalse(element.ok)

    def test_oversized_matrix_is_refused_before_calling_google(self):
        with self.assertRaises(MapsBadResponse):
            google_client.compute_route_matrix([A] * 6, [B] * 6)
        self.assertEqual(self.google.calls, [])

    def test_matrix_must_be_an_array(self):
        self.google.push(200, {"unexpected": True})
        with self.assertRaises(MapsBadResponse):
            google_client.compute_route_matrix([A], [B])


class AddressValidationTests(GoogleFakeMixin, SimpleTestCase):
    def test_disabled_by_default(self):
        with self.assertRaises(MapsNotConfigured):
            google_client.validate_address(["12 Test Road"])

    @override_settings(GOOGLE_ADDRESS_VALIDATION_ENABLED=True)
    def test_verdict_is_reduced_to_safe_fields(self):
        self.google.push(200, {"result": {"verdict": {"addressComplete": True, "validationGranularity": "PREMISE"},
                                          "geocode": {"location": {"latitude": 1}}}})
        verdict = google_client.validate_address(["12 Test Road"])
        self.assertEqual(verdict, {"address_complete": True, "has_unconfirmed_components": False,
                                   "has_inferred_components": False, "validation_granularity": "PREMISE"})
