import random

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import get_user_model, login, logout
from django.contrib.auth.forms import AuthenticationForm
from django.core.exceptions import ValidationError
from django.core.paginator import Paginator
from django.db.models import Count, Prefetch, Q
from django.http import HttpResponseNotAllowed
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.crypto import get_random_string
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.cache import never_cache
from django.views.decorators.csrf import csrf_protect

from accounts.models import Role

from .decorators import (
    customer_permission_required,
    customer_portal_required,
    get_portal_customer_address_or_404,
    portal_customer_addresses_queryset,
    resolve_customer_portal_profile,
    user_has_customer_permission,
)
from .forms import (
    CustomerDeactivationForm,
    CustomerOTPPhoneForm,
    CustomerOTPProfileForm,
    CustomerOTPVerifyForm,
    CustomerPortalAddressForm,
    CustomerPortalProfileForm,
    CustomerSelfRegistrationForm,
    CustomerVerificationForm,
    ManagementCustomerCreateForm,
    ManagementCustomerEditForm,
)
from .models import Customer, CustomerAddress, RegistrationSource, VerificationStatus
from .services import (
    create_customer_delivery_address,
    create_customer_with_user,
    deactivate_customer_address,
    get_customer_portal_dashboard_context,
    set_customer_active,
    set_customer_address_as_default,
    set_customer_verification,
    update_customer_delivery_address,
    update_customer_profile,
)

User = get_user_model()

OTP_SESSION_KEY = "customer_otp"
OTP_LENGTH = 4


def _get_customer_or_404(pk):
    return get_object_or_404(
        Customer.objects.select_related("user", "created_by").prefetch_related(
            Prefetch(
                "addresses",
                queryset=CustomerAddress.objects.select_related("address").order_by(
                    "-is_active",
                    "-is_default",
                    "-created_at",
                ),
            )
        ),
        pk=pk,
    )


def _management_list_query_string(request, *, page=None):
    params = request.GET.copy()
    if page is None:
        params.pop("page", None)
    else:
        params["page"] = page
    return params.urlencode()


@customer_permission_required("customers.view_customer")
def customer_list_view(request):
    queryset = (
        Customer.objects.select_related("user", "created_by")
        .annotate(
            saved_address_count=Count(
                "addresses",
                filter=Q(addresses__is_active=True),
            )
        )
        .order_by("-created_at")
    )
    search_query = request.GET.get("q", "").strip()
    source_filter = request.GET.get("registration_source", "").strip()
    verification_filter = request.GET.get("verification_status", "").strip()
    is_active_filter = request.GET.get("is_active", "").strip()

    if search_query:
        queryset = queryset.filter(
            Q(customer_code__icontains=search_query)
            | Q(user__username__icontains=search_query)
            | Q(user__email__icontains=search_query)
            | Q(user__phone_number__icontains=search_query)
            | Q(user__first_name__icontains=search_query)
            | Q(user__last_name__icontains=search_query)
        )
    if source_filter:
        queryset = queryset.filter(registration_source=source_filter)
    if verification_filter:
        queryset = queryset.filter(verification_status=verification_filter)
    if is_active_filter == "true":
        queryset = queryset.filter(user__is_active=True)
    elif is_active_filter == "false":
        queryset = queryset.filter(user__is_active=False)

    paginator = Paginator(queryset, 25)
    page_obj = paginator.get_page(request.GET.get("page"))
    return render(
        request,
        "management/customers/list.html",
        {
            "page_obj": page_obj,
            "search_query": search_query,
            "source_filter": source_filter,
            "verification_filter": verification_filter,
            "is_active_filter": is_active_filter,
            "registration_source_choices": RegistrationSource.choices,
            "verification_status_choices": VerificationStatus.choices,
            "query_string": _management_list_query_string(request),
            "can_add_customer": user_has_customer_permission(
                request.user, "customers.add_customer"
            ),
            "can_change_customer": user_has_customer_permission(
                request.user, "customers.change_customer"
            ),
            "can_activate_customer": user_has_customer_permission(
                request.user, "customers.activate_customer"
            ),
            "can_verify_customer": user_has_customer_permission(
                request.user, "customers.verify_customer"
            ),
        },
    )


@customer_permission_required("customers.view_customer")
def customer_detail_view(request, pk):
    customer = _get_customer_or_404(pk)
    addresses = list(customer.addresses.all())
    active_address_count = sum(1 for address in addresses if address.is_active)
    return render(
        request,
        "management/customers/detail.html",
        {
            "customer": customer,
            "addresses": addresses,
            "saved_address_count": active_address_count,
            "can_change_customer": user_has_customer_permission(
                request.user, "customers.change_customer"
            ),
            "can_activate_customer": user_has_customer_permission(
                request.user, "customers.activate_customer"
            ),
            "can_verify_customer": user_has_customer_permission(
                request.user, "customers.verify_customer"
            ),
            "verification_form": CustomerVerificationForm(
                initial={"verification_status": customer.verification_status}
            ),
            "deactivation_form": CustomerDeactivationForm(),
        },
    )


@csrf_protect
@customer_permission_required("customers.add_customer")
def customer_create_view(request):
    form = ManagementCustomerCreateForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        data = form.cleaned_data
        customer, user = create_customer_with_user(
            user_data={
                "username": data["username"],
                "email": data["email"],
                "first_name": data["first_name"],
                "last_name": data["last_name"],
                "phone_number": data["phone_number"] or None,
                "password": data["password"],
            },
            registration_source=RegistrationSource.MANAGEMENT_PORTAL,
            created_by=request.user,
            notes=data.get("notes") or "",
            initial_address_data=form.cleaned_initial_address_data(),
            request=request,
        )
        messages.success(
            request,
            f"Customer {user.username} ({customer.customer_code}) created.",
        )
        return redirect("customers:customer_detail", pk=customer.pk)

    return render(
        request,
        "management/customers/create.html",
        {
            "form": form,
            "account_fields": [
                field for field in form if not field.name.startswith("address_")
            ],
            "address_fields": [
                field for field in form if field.name.startswith("address_")
            ],
        },
    )


@csrf_protect
@customer_permission_required("customers.change_customer")
def customer_edit_view(request, pk):
    customer = _get_customer_or_404(pk)
    initial = {
        "first_name": customer.user.first_name,
        "last_name": customer.user.last_name,
        "email": customer.user.email,
        "phone_number": customer.user.phone_number or "",
        "date_of_birth": customer.date_of_birth,
        "notes": customer.notes,
    }
    form = ManagementCustomerEditForm(
        request.POST or None,
        initial=initial,
        customer=customer,
    )
    if request.method == "POST" and form.is_valid():
        data = form.cleaned_data
        update_customer_profile(
            customer=customer,
            user_fields={
                "first_name": data["first_name"],
                "last_name": data["last_name"],
                "email": data["email"],
                "phone_number": data["phone_number"] or None,
            },
            date_of_birth=data.get("date_of_birth"),
            notes=data.get("notes") or "",
            actor=request.user,
            request=request,
        )
        messages.success(
            request,
            f"Customer {customer.user.username} updated.",
        )
        return redirect("customers:customer_detail", pk=customer.pk)

    return render(
        request,
        "management/customers/edit.html",
        {"form": form, "customer": customer},
    )


@csrf_protect
@customer_permission_required("customers.activate_customer")
def customer_toggle_status_view(request, pk):
    if request.method != "POST":
        return HttpResponseNotAllowed(["POST"])

    customer = _get_customer_or_404(pk)
    new_active = not customer.user.is_active

    reason = ""
    if not new_active:
        form = CustomerDeactivationForm(request.POST)
        if not form.is_valid():
            messages.error(
                request,
                form.errors.get("reason", ["A reason is required to deactivate a customer."])[0],
            )
            return redirect("customers:customer_detail", pk=customer.pk)
        reason = form.cleaned_data["reason"]

    try:
        set_customer_active(
            customer=customer,
            is_active=new_active,
            actor=request.user,
            request=request,
            reason=reason,
        )
    except ValidationError as exc:
        messages.error(request, "; ".join(exc.messages))
        return redirect("customers:customer_detail", pk=customer.pk)

    state = "activated" if new_active else "deactivated"
    messages.success(request, f"Customer {customer.user.username} {state}.")
    return redirect("customers:customer_detail", pk=customer.pk)


@csrf_protect
@customer_permission_required("customers.verify_customer")
def customer_verify_view(request, pk):
    if request.method != "POST":
        return HttpResponseNotAllowed(["POST"])

    customer = _get_customer_or_404(pk)
    form = CustomerVerificationForm(request.POST)
    if not form.is_valid():
        messages.error(request, "Invalid verification status.")
        return redirect("customers:customer_detail", pk=customer.pk)

    set_customer_verification(
        customer=customer,
        verification_status=form.cleaned_data["verification_status"],
        actor=request.user,
        request=request,
    )
    messages.success(
        request,
        f"Customer {customer.user.username} verification updated.",
    )
    return redirect("customers:customer_detail", pk=customer.pk)


def customer_register_view(request):
    form = CustomerSelfRegistrationForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        data = form.cleaned_data
        create_customer_with_user(
            user_data={
                "username": data["username"],
                "email": data["email"],
                "first_name": data["first_name"],
                "last_name": data["last_name"],
                "phone_number": data["phone_number"],
                "password": data["password"],
            },
            registration_source=RegistrationSource.WEBSITE,
            created_by=None,
            request=request,
        )
        messages.success(request, "Registration successful. Please log in.")
        return redirect(getattr(settings, "CUSTOMER_LOGIN_URL", "/customer/login/"))

    return render(
        request,
        "customer_portal/register.html",
        {"form": form},
    )


def _safe_customer_redirect(request, fallback_name="customers:customer_portal_dashboard"):
    """Honor a safe next URL from GET/POST; otherwise use the customer dashboard."""
    redirect_to = request.POST.get("next") or request.GET.get("next")
    if redirect_to and url_has_allowed_host_and_scheme(
        url=redirect_to,
        allowed_hosts={request.get_host()},
        require_https=request.is_secure(),
    ):
        return redirect(redirect_to)
    return redirect(fallback_name)


@csrf_protect
@never_cache
def customer_portal_login_view(request):
    if request.user.is_authenticated and request.user.role == Role.CUSTOMER:
        customer, _ = resolve_customer_portal_profile(request.user)
        if customer is not None:
            return _safe_customer_redirect(request)

    form = AuthenticationForm(request, data=request.POST or None)
    if request.method == "POST" and form.is_valid():
        user = form.get_user()
        customer, denial = resolve_customer_portal_profile(user)
        if customer is None:
            form.add_error(
                None,
                denial or "This account cannot access the customer portal.",
            )
        else:
            login(request, user)
            return _safe_customer_redirect(request)

    return render(request, "customer_portal/login.html", {"form": form})


def _generate_otp():
    """
    Placeholder OTP generator for the design/demo flow.

    TODO(backend): replace with real OTP generation + dispatch through an
    SMS gateway. Nothing here should ship to production as-is.
    """
    return "".join(str(random.randint(0, 9)) for _ in range(OTP_LENGTH))


@csrf_protect
@never_cache
def customer_otp_start_view(request):
    """Step 1 of the mobile-first login/signup flow: collect the phone number."""
    if request.user.is_authenticated and request.user.role == Role.CUSTOMER:
        customer, _ = resolve_customer_portal_profile(request.user)
        if customer is not None:
            return _safe_customer_redirect(request)

    form = CustomerOTPPhoneForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        phone_number = form.cleaned_data["phone_number"]
        otp_code = _generate_otp()
        request.session[OTP_SESSION_KEY] = {
            "phone_number": phone_number,
            "code": otp_code,
            "next": request.POST.get("next") or request.GET.get("next", ""),
        }
        # TODO(backend): send otp_code to phone_number via the SMS gateway
        # instead of surfacing it in a message banner.
        messages.info(
            request,
            f"Demo mode (no SMS gateway connected yet): your OTP is {otp_code}.",
        )
        return redirect("customers:customer_otp_verify")

    return render(request, "customer_portal/otp_start.html", {"form": form})


@csrf_protect
@never_cache
def customer_otp_verify_view(request):
    """Step 2: verify the OTP, then sign in an existing customer or continue to profile capture."""
    otp_session = request.session.get(OTP_SESSION_KEY)
    if not otp_session:
        return redirect("customers:customer_otp_start")

    form = CustomerOTPVerifyForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        if form.cleaned_data["otp_code"] != otp_session.get("code"):
            form.add_error("otp_code", "Incorrect OTP. Please try again.")
        else:
            phone_number = otp_session["phone_number"]
            user = User.objects.filter(phone_number=phone_number).first()
            if user is not None:
                customer, denial = resolve_customer_portal_profile(user)
                if customer is None:
                    messages.error(
                        request,
                        denial or "This account cannot access the customer portal.",
                    )
                    request.session.pop(OTP_SESSION_KEY, None)
                    return redirect("customers:customer_otp_start")
                login(request, user)
                request.session.pop(OTP_SESSION_KEY, None)
                return _safe_customer_redirect(request)
            return redirect("customers:customer_otp_profile")

    return render(
        request,
        "customer_portal/otp_verify.html",
        {"form": form, "phone_number": otp_session["phone_number"]},
    )


@csrf_protect
@never_cache
def customer_otp_resend_view(request):
    otp_session = request.session.get(OTP_SESSION_KEY)
    if not otp_session or request.method != "POST":
        return redirect("customers:customer_otp_start")

    otp_session["code"] = _generate_otp()
    request.session[OTP_SESSION_KEY] = otp_session
    # TODO(backend): trigger a fresh SMS dispatch here.
    messages.info(
        request,
        f"Demo mode (no SMS gateway connected yet): your new OTP is {otp_session['code']}.",
    )
    return redirect("customers:customer_otp_verify")


@csrf_protect
@never_cache
def customer_otp_profile_view(request):
    """Step 3, new numbers only: collect the minimum details to create the account."""
    otp_session = request.session.get(OTP_SESSION_KEY)
    if not otp_session:
        return redirect("customers:customer_otp_start")

    phone_number = otp_session["phone_number"]
    if User.objects.filter(phone_number=phone_number).exists():
        return redirect("customers:customer_otp_verify")

    form = CustomerOTPProfileForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        # OTP is the credential going forward, so the password is random and
        # immediately disabled — nothing meaningful to hand to a backend dev
        # here since sign-in never uses it.
        _, user = create_customer_with_user(
            user_data={
                "username": f"zoop{phone_number}",
                "email": form.cleaned_data["email"],
                "first_name": form.cleaned_data["first_name"],
                "last_name": form.cleaned_data.get("last_name") or "",
                "phone_number": phone_number,
                "password": get_random_string(32),
            },
            registration_source=RegistrationSource.WEBSITE,
            created_by=None,
            request=request,
        )
        user.set_unusable_password()
        user.save(update_fields=["password"])
        login(request, user)
        request.session.pop(OTP_SESSION_KEY, None)
        return _safe_customer_redirect(request)

    return render(
        request,
        "customer_portal/otp_profile.html",
        {"form": form, "phone_number": phone_number},
    )


@csrf_protect
@never_cache
def customer_portal_logout_view(request):
    if request.method != "POST":
        return HttpResponseNotAllowed(["POST"])
    logout(request)
    return redirect("customers:customer_portal_login")


@never_cache
@customer_portal_required
def customer_portal_dashboard_view(request):
    # Always resolve from the authenticated user — ignore any customer_id param.
    context = get_customer_portal_dashboard_context(request.user)
    return render(request, "customer_portal/dashboard.html", context)


def _get_portal_customer(user):
    """Load the authenticated user's Customer profile; never by client id."""
    return Customer.objects.select_related("user", "created_by").get(user_id=user.pk)


@never_cache
@customer_portal_required
def customer_portal_profile_view(request):
    customer = _get_portal_customer(request.user)
    return render(
        request,
        "customer_portal/profile.html",
        {"customer": customer},
    )


@csrf_protect
@never_cache
@customer_portal_required
def customer_portal_profile_edit_view(request):
    customer = _get_portal_customer(request.user)
    form = CustomerPortalProfileForm(
        request.POST or None,
        user=request.user,
    )
    if request.method == "POST" and form.is_valid():
        update_customer_profile(
            customer=customer,
            user_fields={
                "first_name": form.cleaned_data["first_name"],
                "last_name": form.cleaned_data["last_name"],
                "email": form.cleaned_data["email"],
                "phone_number": form.cleaned_data["phone_number"],
            },
            request=request,
        )
        messages.success(request, "Profile updated successfully.")
        return redirect("customers:customer_portal_profile")

    return render(
        request,
        "customer_portal/profile_edit.html",
        {
            "customer": customer,
            "form": form,
        },
    )


@never_cache
@customer_portal_required
def customer_portal_address_list_view(request):
    addresses = portal_customer_addresses_queryset(request.user).order_by(
        "-is_active",
        "-is_default",
        "-created_at",
    )
    return render(
        request,
        "customer_portal/addresses/list.html",
        {"addresses": addresses},
    )


@csrf_protect
@never_cache
@customer_portal_required
def customer_portal_address_create_view(request):
    customer = _get_portal_customer(request.user)
    form = CustomerPortalAddressForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        create_customer_delivery_address(
            customer=customer,
            data=form.cleaned_address_data(),
        )
        messages.success(request, "Delivery address added.")
        return _safe_customer_redirect(
            request, fallback_name="customers:customer_portal_address_list"
        )

    return render(
        request,
        "customer_portal/addresses/form.html",
        {
            "form": form,
            "form_title": "Add delivery address",
            "submit_label": "Save address",
        },
    )


@csrf_protect
@never_cache
@customer_portal_required
def customer_portal_address_edit_view(request, pk):
    customer_address = get_portal_customer_address_or_404(request.user, pk)
    if not customer_address.is_active:
        messages.error(request, "Inactive addresses cannot be edited.")
        return redirect("customers:customer_portal_address_list")

    form = CustomerPortalAddressForm(
        request.POST or None,
        customer_address=customer_address,
    )
    if request.method == "POST" and form.is_valid():
        # Always update the address resolved from request.user — ignore customer_id.
        update_customer_delivery_address(
            customer_address=customer_address,
            data=form.cleaned_address_data(),
        )
        messages.success(request, "Delivery address updated.")
        return redirect("customers:customer_portal_address_list")

    return render(
        request,
        "customer_portal/addresses/form.html",
        {
            "form": form,
            "customer_address": customer_address,
            "form_title": "Edit delivery address",
            "submit_label": "Save changes",
        },
    )


@csrf_protect
@never_cache
@customer_portal_required
def customer_portal_address_set_default_view(request, pk):
    if request.method != "POST":
        return HttpResponseNotAllowed(["POST"])

    customer_address = get_portal_customer_address_or_404(request.user, pk)
    try:
        set_customer_address_as_default(customer_address=customer_address)
    except ValidationError as exc:
        messages.error(request, "; ".join(exc.messages))
        return redirect("customers:customer_portal_address_list")
    messages.success(request, "Default delivery address updated.")
    return redirect("customers:customer_portal_address_list")


@csrf_protect
@never_cache
@customer_portal_required
def customer_portal_address_deactivate_view(request, pk):
    if request.method != "POST":
        return HttpResponseNotAllowed(["POST"])

    customer_address = get_portal_customer_address_or_404(request.user, pk)
    deactivate_customer_address(customer_address=customer_address)
    messages.success(request, "Delivery address deactivated.")
    return redirect("customers:customer_portal_address_list")
