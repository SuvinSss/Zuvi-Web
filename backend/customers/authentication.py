"""Customer-only Google sign-in and email password recovery."""
import base64
import hashlib
import json
import secrets
import time
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import get_user_model, login
from django.contrib.auth.forms import PasswordResetForm
from django.contrib.auth.views import PasswordResetView, PasswordResetConfirmView
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.shortcuts import redirect
from django.urls import reverse_lazy, reverse
from django.utils.decorators import method_decorator
from django.views.decorators.cache import never_cache
from django.views.decorators.debug import sensitive_variables
from django.views.decorators.http import require_POST, require_GET
from django.views.decorators.csrf import csrf_protect
from accounts.models import Role
from .models import CustomerGoogleIdentity, RegistrationSource
from .services import create_customer_with_user
from .decorators import resolve_customer_portal_profile


def google_enabled():
    return bool(settings.GOOGLE_OAUTH_CLIENT_ID and settings.GOOGLE_OAUTH_CLIENT_SECRET)


def auth_options(request):
    return {"google_signin_enabled": google_enabled()}


class CustomerPasswordResetForm(PasswordResetForm):
    def get_users(self, email):
        return (u for u in super().get_users(email) if u.role == Role.CUSTOMER and not u.is_staff and not u.is_superuser and resolve_customer_portal_profile(u)[0] is not None)


class CustomerPasswordResetView(PasswordResetView):
    form_class = CustomerPasswordResetForm
    template_name = "customer_portal/password_reset.html"
    email_template_name = "customer_portal/password_reset_email.txt"
    subject_template_name = "customer_portal/password_reset_subject.txt"
    success_url = reverse_lazy("customers:password_reset_done")

    def form_valid(self, form):
        if not settings.CUSTOMER_EMAIL_ENABLED:
            form.add_error(None, "Password recovery is temporarily unavailable. Please try again later.")
            return self.form_invalid(form)
        try:
            return super().form_valid(form)
        except (OSError, __import__('smtplib').SMTPException):
            # Same response for existing and unknown addresses on delivery failure.
            return redirect(self.success_url)


class CustomerPasswordResetConfirmView(PasswordResetConfirmView):
    template_name = "customer_portal/password_reset_confirm.html"
    success_url = reverse_lazy("customers:password_reset_complete")

    def get_user(self, uidb64):
        user = super().get_user(uidb64)
        if user and user.role == Role.CUSTOMER and not user.is_staff and not user.is_superuser and resolve_customer_portal_profile(user)[0] is not None:
            return user
        return None


@require_POST
@csrf_protect
@never_cache
def google_start(request):
    if not google_enabled():
        messages.error(request, "Google sign-in is not available yet. Please use your password.")
        return redirect("customers:customer_portal_login")
    if request.POST.get("accept_terms") != "on":
        messages.error(request, "Accept the Terms & Conditions to continue with Google.")
        return redirect("customers:customer_portal_login")
    state, nonce, verifier = secrets.token_urlsafe(32), secrets.token_urlsafe(32), secrets.token_urlsafe(48)
    request.session["google_login"] = {"state":state,"nonce":nonce,"verifier":verifier,"created":time.time(),"next":request.POST.get("next", "")}
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    return redirect("https://accounts.google.com/o/oauth2/v2/auth?" + urlencode({
        "client_id":settings.GOOGLE_OAUTH_CLIENT_ID,"redirect_uri":request.build_absolute_uri(reverse("customers:google_callback")),
        "response_type":"code","scope":"openid email profile","state":state,"nonce":nonce,
        "code_challenge":challenge,"code_challenge_method":"S256","prompt":"select_account",
    }))


@sensitive_variables()
def verified_google_claims(code, flow, callback):
    from google.auth.transport.requests import Request as GoogleRequest
    from google.oauth2.id_token import verify_oauth2_token
    body=urlencode({"code":code,"client_id":settings.GOOGLE_OAUTH_CLIENT_ID,"client_secret":settings.GOOGLE_OAUTH_CLIENT_SECRET,
                    "redirect_uri":callback,"grant_type":"authorization_code","code_verifier":flow["verifier"]}).encode()
    req=Request("https://oauth2.googleapis.com/token",data=body,headers={"Content-Type":"application/x-www-form-urlencoded"})
    with urlopen(req, timeout=10) as response:
        token=json.load(response)["id_token"]
    claims=verify_oauth2_token(token, GoogleRequest(), settings.GOOGLE_OAUTH_CLIENT_ID)
    if not claims.get("sub") or claims.get("email_verified") is not True or not claims.get("email") or not secrets.compare_digest(str(claims.get("nonce", "")), flow["nonce"]):
        raise ValueError("Invalid identity claims")
    return claims


@require_GET
@never_cache
@sensitive_variables()
def google_callback(request):
    flow=request.session.pop("google_login", None)
    if not google_enabled() or not flow or time.time()-flow["created"] > 600 or not secrets.compare_digest(request.GET.get("state", ""),flow["state"]) or not request.GET.get("code"):
        messages.error(request, "Google sign-in expired or was cancelled. Please try again.")
        return redirect("customers:customer_portal_login")
    try:
        claims=verified_google_claims(request.GET["code"],flow,request.build_absolute_uri(reverse("customers:google_callback")))
        with transaction.atomic():
            identity=CustomerGoogleIdentity.objects.select_related("user").filter(subject=claims["sub"]).first()
            if identity:
                user=identity.user
            else:
                # Never take over an existing password account, including staff accounts.
                if get_user_model().objects.filter(email__iexact=claims["email"]).exists():
                    messages.error(request, "An account already uses this email. Sign in with your password.")
                    return redirect("customers:customer_portal_login")
                customer, user=create_customer_with_user(user_data={"username":"google_"+secrets.token_hex(12),"email":claims["email"].lower(),"first_name":claims.get("given_name", "")[:150],"last_name":claims.get("family_name", "")[:150],"password":secrets.token_urlsafe(48)},registration_source=RegistrationSource.WEBSITE,request=request)
                user.set_unusable_password()
                user.save(update_fields=["password"])
                CustomerGoogleIdentity.objects.create(user=user,subject=claims["sub"])
            if user.role != Role.CUSTOMER or user.is_staff or user.is_superuser or resolve_customer_portal_profile(user)[0] is None:
                raise ValidationError("Account unavailable")
    except Exception:
        # OAuth exceptions may contain tokens; never include them in logs or UI.
        messages.error(request, "Google sign-in could not be completed. Please try again or use your password.")
        return redirect("customers:customer_portal_login")
    login(request,user)
    from django.utils.http import url_has_allowed_host_and_scheme
    target=flow.get("next", "")
    if target and url_has_allowed_host_and_scheme(target,allowed_hosts={request.get_host()},require_https=request.is_secure()):
        return redirect(target)
    return redirect("catalog:public_home")
