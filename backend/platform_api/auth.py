"""Authentication and account endpoints for every role (session cookie for web, token for mobile)."""
from django.conf import settings
from django.contrib.auth import authenticate, get_user_model, login, update_session_auth_hash
from django.contrib.auth.password_validation import validate_password
from django.contrib.auth.tokens import default_token_generator
from django.core.exceptions import ValidationError as DjangoValidationError
from django.core.mail import send_mail
from django.db import IntegrityError, transaction
from django.middleware.csrf import get_token
from django.utils.decorators import method_decorator
from django.utils.encoding import force_bytes, force_str
from django.utils.http import urlsafe_base64_decode, urlsafe_base64_encode
from django.views.decorators.csrf import csrf_protect
from drf_spectacular.utils import extend_schema
from rest_framework import serializers
from rest_framework.authentication import SessionAuthentication, TokenAuthentication
from rest_framework.authtoken.models import Token
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView

from accounts.models import Role
from core.permissions import get_customer, get_delivery_partner, get_store_membership
from customers.models import RegistrationSource
from customers.services import create_customer_with_user
from deliveries.models import DeliveryPartner, PartnerStatus, VehicleType

User = get_user_model()


def account_payload(user) -> dict:
    data = {"id": user.pk, "username": user.get_username(), "email": user.email, "first_name": user.first_name,
            "last_name": user.last_name, "phone_number": user.phone_number, "role": user.role}
    customer = get_customer(user)
    if customer:
        data["customer"] = {"id": customer.pk, "code": customer.customer_code}
    membership = get_store_membership(user)
    if membership:
        data["store"] = {"id": membership.store_id, "name": membership.store.name, "code": membership.store.store_code,
                         "can_manage_orders": membership.can_manage_orders, "can_manage_inventory": membership.can_manage_inventory}
    partner = get_delivery_partner(user, approved_only=False)
    if partner:
        data["delivery_partner"] = {"id": partner.pk, "status": partner.status, "is_online": partner.is_online}
    return data


def _fail_validation(exc: DjangoValidationError):
    raise serializers.ValidationError(exc.message_dict if hasattr(exc, "error_dict") else {"detail": exc.messages})


class RegisterSerializer(serializers.Serializer):
    username = serializers.CharField(max_length=150)
    email = serializers.EmailField()
    password = serializers.CharField(write_only=True, trim_whitespace=False, max_length=128)
    first_name = serializers.CharField(max_length=150)
    last_name = serializers.CharField(max_length=150, required=False, allow_blank=True)
    phone_number = serializers.CharField(max_length=20)


class PartnerRegisterSerializer(RegisterSerializer):
    vehicle_type = serializers.ChoiceField(choices=VehicleType.choices, default=VehicleType.MOTORCYCLE)
    vehicle_number = serializers.CharField(max_length=30, required=False, allow_blank=True)


class RegisterView(APIView):
    """Customer self-registration. Role is always CUSTOMER; privilege fields are never accepted."""

    authentication_classes = []
    permission_classes = [AllowAny]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "register"

    @extend_schema(request=RegisterSerializer, responses={201: dict})
    def post(self, request):
        data = RegisterSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        v = dict(data.validated_data)
        try:
            customer, user = create_customer_with_user(user_data=v, registration_source=RegistrationSource.WEBSITE)
        except DjangoValidationError as exc:
            _fail_validation(exc)
        except IntegrityError:
            raise serializers.ValidationError({"detail": "An account with those details already exists."}) from None
        return Response({"user": account_payload(user)}, status=201)


class PartnerRegisterView(APIView):
    """Delivery partner application. The account cannot work until an administrator approves it."""

    authentication_classes = []
    permission_classes = [AllowAny]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "register"

    @extend_schema(request=PartnerRegisterSerializer, responses={201: dict})
    def post(self, request):
        data = PartnerRegisterSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        v = dict(data.validated_data)
        vehicle_type, vehicle_number = v.pop("vehicle_type"), v.pop("vehicle_number", "")
        password = v.pop("password")
        try:
            validate_password(password)
            with transaction.atomic():
                user = User(**v)
                user.role, user.is_staff, user.is_superuser = Role.DELIVERY_AGENT, False, False
                user.set_password(password)
                user.full_clean()
                user.save()
                DeliveryPartner.objects.create(user=user, vehicle_type=vehicle_type, vehicle_number=vehicle_number, status=PartnerStatus.PENDING)
        except DjangoValidationError as exc:
            _fail_validation(exc)
        except IntegrityError:
            raise serializers.ValidationError({"detail": "An account with those details already exists."}) from None
        return Response({"user": account_payload(user), "message": "Your application is pending approval."}, status=201)


class CredentialsSerializer(serializers.Serializer):
    username = serializers.CharField()
    password = serializers.CharField(write_only=True, trim_whitespace=False)


def _authenticate(request, creds):
    # Same generic message for unknown user, wrong password and suspended account.
    user = authenticate(request, username=creds["username"], password=creds["password"])
    if user is None or not user.is_active:
        return None
    return user


@method_decorator(csrf_protect, name="dispatch")
class SignInView(APIView):
    """Session login for any role (web clients). CSRF header required, like the admin login."""

    authentication_classes = []
    permission_classes = [AllowAny]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "login"

    @extend_schema(request=CredentialsSerializer, responses=dict)
    def post(self, request):
        data = CredentialsSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        user = _authenticate(request._request, data.validated_data)
        if user is None:
            return Response({"detail": "Invalid username or password."}, status=400)
        login(request._request, user)
        return Response({"user": account_payload(user), "csrf_token": get_token(request._request)})


class TokenView(APIView):
    """Token login for mobile clients. Tokens are revocable and never logged."""

    authentication_classes = []
    permission_classes = [AllowAny]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "login"

    @extend_schema(request=CredentialsSerializer, responses=dict)
    def post(self, request):
        data = CredentialsSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        user = _authenticate(request._request, data.validated_data)
        if user is None:
            return Response({"detail": "Invalid username or password."}, status=400)
        token, _ = Token.objects.get_or_create(user=user)
        return Response({"token": token.key, "user": account_payload(user)})


class TokenRevokeView(APIView):
    authentication_classes = [TokenAuthentication]

    @extend_schema(request=None, responses={204: None})
    def post(self, request):
        Token.objects.filter(user=request.user).delete()
        return Response(status=204)


class ProfileSerializer(serializers.Serializer):
    first_name = serializers.CharField(max_length=150, required=False)
    last_name = serializers.CharField(max_length=150, required=False, allow_blank=True)
    phone_number = serializers.CharField(max_length=20, required=False)
    email = serializers.EmailField(required=False)


class MeView(APIView):
    @extend_schema(responses=dict)
    def get(self, request):
        return Response(account_payload(request.user))

    @extend_schema(request=ProfileSerializer, responses=dict)
    def patch(self, request):
        data = ProfileSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        user = request.user
        for key, value in data.validated_data.items():  # role/is_staff/etc. are not in the serializer
            setattr(user, key, value)
        try:
            user.full_clean(exclude=["password"])
            user.save()
        except DjangoValidationError as exc:
            _fail_validation(exc)
        except IntegrityError:
            raise serializers.ValidationError({"detail": "Those details are already in use."}) from None
        return Response(account_payload(user))


class PasswordChangeSerializer(serializers.Serializer):
    current_password = serializers.CharField(write_only=True, trim_whitespace=False)
    new_password = serializers.CharField(write_only=True, trim_whitespace=False, max_length=128)


class PasswordChangeView(APIView):
    @extend_schema(request=PasswordChangeSerializer, responses={204: None})
    def post(self, request):
        data = PasswordChangeSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        if not request.user.check_password(data.validated_data["current_password"]):
            raise serializers.ValidationError({"current_password": "Your current password is incorrect."})
        try:
            validate_password(data.validated_data["new_password"], request.user)
        except DjangoValidationError as exc:
            raise serializers.ValidationError({"new_password": exc.messages}) from None
        request.user.set_password(data.validated_data["new_password"])
        request.user.save(update_fields=["password"])
        Token.objects.filter(user=request.user).delete()  # other devices must sign in again
        if request.auth is None or isinstance(request.successful_authenticator, SessionAuthentication):
            update_session_auth_hash(request._request, request.user)
        return Response(status=204)


class ResetRequestSerializer(serializers.Serializer):
    email = serializers.EmailField()


class PasswordResetRequestView(APIView):
    """Always answers 202, so the response never reveals whether an address has an account."""

    authentication_classes = []
    permission_classes = [AllowAny]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "login"

    @extend_schema(request=ResetRequestSerializer, responses={202: dict})
    def post(self, request):
        data = ResetRequestSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        user = User.objects.filter(email__iexact=data.validated_data["email"], is_active=True).first()
        enabled = bool(getattr(settings, "EMAIL_HOST", "")) or getattr(settings, "CUSTOMER_EMAIL_ENABLED", False)
        if user and enabled:
            uid = urlsafe_base64_encode(force_bytes(user.pk))
            token = default_token_generator.make_token(user)
            base = getattr(settings, "FRONTEND_BASE_URL", "").rstrip("/")
            link = f"{base}/reset-password?uid={uid}&token={token}" if base else f"uid={uid} token={token}"
            try:
                send_mail("Reset your password", f"Use this link to choose a new password:\n{link}\n\nIgnore this message if you did not ask for it.",
                          getattr(settings, "DEFAULT_FROM_EMAIL", None), [user.email], fail_silently=True)
            except Exception:
                pass
        return Response({"detail": "If that address has an account, a reset link has been sent."}, status=202)


class ResetConfirmSerializer(serializers.Serializer):
    uid = serializers.CharField()
    token = serializers.CharField()
    new_password = serializers.CharField(write_only=True, trim_whitespace=False, max_length=128)


class PasswordResetConfirmView(APIView):
    authentication_classes = []
    permission_classes = [AllowAny]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "login"

    @extend_schema(request=ResetConfirmSerializer, responses={204: None})
    def post(self, request):
        data = ResetConfirmSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        v = data.validated_data
        try:
            user = User.objects.get(pk=force_str(urlsafe_base64_decode(v["uid"])), is_active=True)
        except (User.DoesNotExist, ValueError, TypeError, OverflowError):
            user = None
        if user is None or not default_token_generator.check_token(user, v["token"]):
            raise serializers.ValidationError({"detail": "This reset link is invalid or has expired."})
        try:
            validate_password(v["new_password"], user)
        except DjangoValidationError as exc:
            raise serializers.ValidationError({"new_password": exc.messages}) from None
        user.set_password(v["new_password"])
        user.save(update_fields=["password"])
        Token.objects.filter(user=user).delete()
        return Response(status=204)


class AcceptInviteSerializer(serializers.Serializer):
    token = serializers.CharField(max_length=500)
    new_password = serializers.CharField(write_only=True, trim_whitespace=False, max_length=128)


class AcceptInviteView(APIView):
    """Store owners choose their own password from a one-time, time-limited setup link."""

    authentication_classes = []
    permission_classes = [AllowAny]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "login"

    @extend_schema(request=AcceptInviteSerializer, responses={204: None})
    def post(self, request):
        from stores.management import read_setup_token
        data = AcceptInviteSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        user = read_setup_token(data.validated_data["token"])
        if user is None:
            raise serializers.ValidationError({"detail": "This setup link is invalid, expired or already used."})
        try:
            validate_password(data.validated_data["new_password"], user)
        except DjangoValidationError as exc:
            raise serializers.ValidationError({"new_password": exc.messages}) from None
        user.set_password(data.validated_data["new_password"])
        user.save(update_fields=["password"])
        Token.objects.filter(user=user).delete()
        return Response(status=204)
