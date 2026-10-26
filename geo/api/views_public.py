"""Configuration, session, geocoding and public (no paid API) endpoints."""

from django.contrib.auth import authenticate, login, logout
from django.middleware.csrf import get_token
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import csrf_protect, ensure_csrf_cookie
from rest_framework import serializers, status
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts.decorators import can_access_management_portal
from accounts.models import Role
from customers.decorators import resolve_customer_portal_profile
from geo import google_client
from geo.config import browser_client_config
from geo.coords import haversine_km, parse_coordinate
from geo.errors import InvalidCoordinates
from geo.serviceability import evaluate_store, store_coordinate
from stores.decorators import resolve_store_portal_membership
from stores.models import Store, StoreStatus

from .permissions import user_has_geo_permission
from .serializers import ForwardGeocodeSerializer, PointSerializer
from .throttles import GeocodeThrottle, LoginThrottle, PublicGeoThrottle

PORTALS = ("customer", "store", "delivery", "admin")


def portal_for_user(user):
    """The portal this user may use, or None. Mirrors the existing Django portal rules."""
    if not user.is_authenticated or not user.is_active:
        return None
    if user.role == Role.CUSTOMER:
        return "customer" if resolve_customer_portal_profile(user)[0] else None
    if user.role == Role.STORE_USER:
        return "store" if resolve_store_portal_membership(user)[0] else None
    if user.role == Role.DELIVERY_AGENT:
        return "delivery"
    if can_access_management_portal(user):
        return "admin"
    return None


def session_payload(user):
    portal = portal_for_user(user)
    if portal is None:
        return {"authenticated": False}
    return {
        "authenticated": True,
        "portal": portal,
        "user": {
            "id": user.pk,
            "username": user.get_username(),
            "name": user.get_full_name() or user.get_username(),
            "role": user.role,
        },
        "permissions": {
            "maps": user_has_geo_permission(user, "geo.manage_maps_operations"),
            "pricing": user_has_geo_permission(user, "geo.manage_delivery_pricing"),
            "assignments": user_has_geo_permission(user, "geo.manage_delivery_assignments"),
        },
    }


class MapsConfigView(APIView):
    """Browser-safe configuration. Contains the browser key only, never the server key."""

    permission_classes = [AllowAny]
    authentication_classes = []

    def get(self, request):
        response = Response(browser_client_config())
        response["Cache-Control"] = "no-store"
        return response


@method_decorator(ensure_csrf_cookie, name="dispatch")
class SessionView(APIView):
    permission_classes = [AllowAny]

    def get(self, request):
        data = session_payload(request.user)
        data["csrfToken"] = get_token(request._request)
        return Response(data)


class LoginSerializer(serializers.Serializer):
    username = serializers.CharField(max_length=150)
    password = serializers.CharField(max_length=256, trim_whitespace=False)
    portal = serializers.ChoiceField(choices=PORTALS)


@method_decorator(csrf_protect, name="dispatch")
class LoginView(APIView):
    permission_classes = [AllowAny]
    authentication_classes = []
    throttle_classes = [LoginThrottle]

    def post(self, request):
        data = LoginSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        django_request = request._request
        user = authenticate(
            django_request,
            username=data.validated_data["username"],
            password=data.validated_data["password"],
        )
        if user is None or not user.is_active:
            return Response(
                {"error": {"code": "BAD_CREDENTIALS", "message": "Incorrect username or password.",
                           "retryable": False}},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if portal_for_user(user) != data.validated_data["portal"]:
            return Response(
                {"error": {"code": "WRONG_PORTAL", "message": "This account cannot use this portal.",
                           "retryable": False}},
                status=status.HTTP_403_FORBIDDEN,
            )
        login(django_request, user)
        payload = session_payload(user)
        payload["csrfToken"] = get_token(django_request)
        return Response(payload)


class LogoutView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        logout(request._request)
        return Response(status=status.HTTP_204_NO_CONTENT)


def geocode_dict(result):
    return {
        "formatted_address": result.formatted_address,
        "place_id": result.place_id,
        "latitude": str(result.latitude),
        "longitude": str(result.longitude),
        "precise": result.is_precise,
        "components": result.components,
    }


class ReverseGeocodeView(APIView):
    """Coordinates -> readable address. Signed-in users only; throttled; nothing is stored."""

    throttle_classes = [GeocodeThrottle]

    def post(self, request):
        data = PointSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        point = parse_coordinate(data.validated_data["latitude"], data.validated_data["longitude"])
        return Response(geocode_dict(google_client.reverse_geocode(point)))


class ForwardGeocodeView(APIView):
    throttle_classes = [GeocodeThrottle]

    def post(self, request):
        data = ForwardGeocodeSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        return Response(geocode_dict(google_client.geocode_address(data.validated_data["address"])))


class NearbyStoresView(APIView):
    """Stores whose delivery radius covers a point. Straight-line only, so it costs nothing.

    Results are approximate by design; the road distance and the fee are only
    decided when a quote is created for a saved address.
    """

    permission_classes = [AllowAny]
    authentication_classes = []
    throttle_classes = [PublicGeoThrottle]

    def get(self, request):
        try:
            point = parse_coordinate(request.query_params.get("lat"), request.query_params.get("lng"))
        except InvalidCoordinates:
            raise serializers.ValidationError({"lat": "Choose a valid location."}) from None
        stores = Store.objects.filter(is_active=True, status=StoreStatus.ACTIVE).select_related(
            "address", "category"
        )
        results = []
        for store in stores:
            origin = store_coordinate(store)
            if origin is None or haversine_km(origin, point) > float(store.delivery_radius_km) + 5:
                continue  # cheap bounding filter before the full eligibility evaluation
            verdict = evaluate_store(store, point)
            results.append(
                {
                    "id": store.pk,
                    "name": store.name,
                    "category": store.category.name,
                    "straight_line_km": verdict.straight_line_km,
                    "within_delivery_area": verdict.eligible,
                    "reasons": verdict.reasons,
                    "approximate": True,
                }
            )
        results.sort(key=lambda r: (not r["within_delivery_area"], r["straight_line_km"] or 0))
        return Response({"stores": results[:50], "approximate": True})
