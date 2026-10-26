from django.core.cache import cache
from django.test import SimpleTestCase, override_settings

from . import routing
from .errors import MapsKeyRejected, MapsNetworkError, NoRouteFound
from .testing import GoogleFakeMixin, coord, matrix_ok, route_ok

STORE_A, STORE_B, STORE_C = coord(8.80, 76.65), coord(8.82, 76.67), coord(8.84, 76.69)
HOME = coord(8.85, 76.70)


class SingleRouteTests(GoogleFakeMixin, SimpleTestCase):
    def test_live_result_is_normalised_and_labelled(self):
        self.google.push(*route_ok(3200, 480))
        result = routing.get_route(STORE_A, HOME, origin_ref="store:1", destination_ref="address:9")
        self.assertEqual(result.source, "LIVE")
        self.assertEqual(result.provider, "google_routes_v2")
        self.assertEqual(str(result.distance_km), "3.200")
        self.assertEqual(result.duration_seconds, 480)
        self.assertEqual(result.status, "OK")
        self.assertEqual(result.as_dict()["origin_ref"], "store:1")
        self.assertEqual(len(self.google.calls), 1)

    def test_repeat_request_is_served_from_cache_and_labelled_cached(self):
        self.google.push(*route_ok(3200, 480))
        routing.get_route(STORE_A, HOME)
        again = routing.get_route(STORE_A, HOME, origin_ref="store:1")
        self.assertEqual(again.source, "CACHED")
        self.assertEqual(again.origin_ref, "store:1")
        self.assertEqual(again.distance_meters, 3200)
        self.assertEqual(len(self.google.calls), 1)

    def test_cache_expiry_forces_a_new_live_request(self):
        self.google.push(*route_ok(3200, 480)).push(*route_ok(3300, 500))
        routing.get_route(STORE_A, HOME)
        cache.clear()  # what TTL expiry does
        second = routing.get_route(STORE_A, HOME)
        self.assertEqual((second.source, second.distance_meters), ("LIVE", 3300))

    @override_settings(GOOGLE_ROUTES_CACHE_TTL_SECONDS=0)
    def test_zero_ttl_disables_caching(self):
        self.google.push(*route_ok(1000, 100)).push(*route_ok(1000, 100))
        routing.get_route(STORE_A, HOME)
        self.assertEqual(routing.get_route(STORE_A, HOME).source, "LIVE")
        self.assertEqual(len(self.google.calls), 2)

    def test_use_cache_false_bypasses_but_refreshes_the_cache(self):
        self.google.push(*route_ok(1000, 100)).push(*route_ok(1100, 110))
        routing.get_route(STORE_A, HOME)
        fresh = routing.get_route(STORE_A, HOME, use_cache=False)
        self.assertEqual((fresh.source, fresh.distance_meters), ("LIVE", 1100))
        self.assertEqual(routing.get_route(STORE_A, HOME).distance_meters, 1100)

    def test_different_destination_is_a_different_cache_entry(self):
        self.google.push(*route_ok(1000, 100)).push(*route_ok(2000, 200))
        routing.get_route(STORE_A, HOME)
        other = routing.get_route(STORE_A, coord(8.9, 76.8))
        self.assertEqual(other.distance_meters, 2000)

    def test_failure_is_raised_and_never_replaced_by_a_straight_line_guess(self):
        self.google.push(0, raises=MapsNetworkError("down"))
        with self.assertRaises(MapsNetworkError):
            routing.get_route(STORE_A, HOME)
        self.google.push(200, {})
        with self.assertRaises(NoRouteFound):
            routing.get_route(STORE_A, HOME)

    def test_failures_are_not_cached(self):
        self.google.push(200, {}).push(*route_ok(1000, 100))
        with self.assertRaises(NoRouteFound):
            routing.get_route(STORE_A, HOME)
        self.assertEqual(routing.get_route(STORE_A, HOME).source, "LIVE")


class MultiOriginTests(GoogleFakeMixin, SimpleTestCase):
    def origins(self, *pairs):
        return [(ref, c) for ref, c in pairs]

    def test_single_uncached_origin_uses_a_single_route_call(self):
        self.google.push(*route_ok(1500, 150))
        out = routing.get_routes_from_origins(self.origins(("1", STORE_A)), HOME)
        self.assertEqual(out["1"].distance_meters, 1500)
        self.assertIn("computeRoutes", self.google.calls[0]["url"])

    def test_two_origins_use_one_matrix_call_and_fill_the_cache(self):
        self.google.push(*matrix_ok([(0, 0, 1000, 100), (1, 0, 2000, 200)]))
        out = routing.get_routes_from_origins(self.origins(("1", STORE_A), ("2", STORE_B)), HOME)
        self.assertEqual([out["1"].distance_meters, out["2"].distance_meters], [1000, 2000])
        self.assertIn("computeRouteMatrix", self.google.calls[0]["url"])
        self.assertEqual(routing.get_route(STORE_B, HOME).source, "CACHED")

    def test_cached_pairs_are_not_requested_again(self):
        self.google.push(*route_ok(1000, 100))
        routing.get_route(STORE_A, HOME)
        self.google.push(*route_ok(2000, 200))
        out = routing.get_routes_from_origins(self.origins(("1", STORE_A), ("2", STORE_B)), HOME)
        self.assertEqual(out["1"].source, "CACHED")
        self.assertEqual(out["2"].source, "LIVE")
        self.assertIn("computeRoutes", self.google.calls[-1]["url"])

    def test_one_failed_element_does_not_poison_the_others(self):
        self.google.push(200, [
            {"originIndex": 0, "destinationIndex": 0, "status": {}, "condition": "ROUTE_EXISTS",
             "distanceMeters": 1000, "duration": "100s"},
            {"originIndex": 1, "destinationIndex": 0, "status": {"code": 5}, "condition": "ROUTE_NOT_FOUND"},
        ])
        out = routing.get_routes_from_origins(self.origins(("1", STORE_A), ("2", STORE_B)), HOME)
        self.assertEqual(out["1"].distance_meters, 1000)
        self.assertIsInstance(out["2"], routing.RouteFailure)
        self.assertEqual(out["2"].error.code, "NO_ROUTE")

    def test_whole_matrix_failure_is_reported_for_every_origin(self):
        self.google.push(403, {"error": {"status": "PERMISSION_DENIED", "message": "x"}})
        out = routing.get_routes_from_origins(
            self.origins(("1", STORE_A), ("2", STORE_B), ("3", STORE_C)), HOME
        )
        self.assertTrue(all(isinstance(v, routing.RouteFailure) for v in out.values()))
        self.assertIsInstance(out["1"].error, MapsKeyRejected)
