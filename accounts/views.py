from django.contrib.auth import login, logout
from django.contrib.auth.forms import AuthenticationForm
from django.contrib.auth import get_user_model
from django.db import transaction
from django.db.models import Q
from django.http import Http404, HttpResponseNotAllowed
from django.shortcuts import redirect, render
from django.utils.http import url_has_allowed_host_and_scheme

from stores.decorators import user_has_store_permission
from stores.services import get_store_dashboard_stats

from catalog.decorators import user_has_catalog_permission
from catalog.services import get_product_dashboard_stats
from customers.decorators import user_has_customer_permission
from customers.services import get_customer_dashboard_stats
from inventory.decorators import user_can_view_management_inventory
from inventory.status import get_inventory_dashboard_stats

from .audit_ip import get_client_ip
from .decorators import (
    MANAGEMENT_ALLOWED_ROLES,
    can_access_management_portal,
    management_portal_required,
    super_admin_required,
)
from .forms import AdminCreateForm, AdminUpdateForm
from .models import AdminAuditLog, AdminProfile, Role
from .templatetags.management_permissions import MANAGEMENT_MODULES

User = get_user_model()


def management_login_view(request):
    if request.user.is_authenticated:
        if can_access_management_portal(request.user):
            return redirect("accounts:management_dashboard")
        return management_permission_denied_view(request, exception=None)

    form = AuthenticationForm(request, data=request.POST or None)
    if request.method == "POST" and form.is_valid():
        user = form.get_user()
        if not can_access_management_portal(user):
            form.add_error(None, "This account cannot access the management portal.")
        else:
            login(request, user)
            redirect_to = request.POST.get("next") or request.GET.get("next")
            if redirect_to and url_has_allowed_host_and_scheme(
                url=redirect_to,
                allowed_hosts={request.get_host()},
                require_https=request.is_secure(),
            ):
                return redirect(redirect_to)
            return redirect("accounts:management_dashboard")

    return render(
        request,
        "management/login.html",
        {
            "form": form,
        },
    )


@management_portal_required
def management_dashboard_view(request):
    store_stats = None
    if user_has_store_permission(request.user, "stores.view_store"):
        store_stats = get_store_dashboard_stats()

    product_stats = None
    if user_has_catalog_permission(request.user, "catalog.view_product"):
        product_stats = get_product_dashboard_stats()

    inventory_stats = None
    if user_can_view_management_inventory(request.user):
        inventory_stats = get_inventory_dashboard_stats()

    customer_stats = None
    if user_has_customer_permission(request.user, "customers.view_customer"):
        customer_stats = get_customer_dashboard_stats()

    return render(
        request,
        "management/dashboard.html",
        {
            "management_modules": MANAGEMENT_MODULES,
            "assigned_groups": request.user.groups.all(),
            "store_stats": store_stats,
            "product_stats": product_stats,
            "inventory_stats": inventory_stats,
            "customer_stats": customer_stats,
        },
    )


@management_portal_required
def management_logout_view(request):
    if request.method != "POST":
        return HttpResponseNotAllowed(["POST"])
    logout(request)
    return redirect("accounts:management_login")


def management_permission_denied_view(request, exception):
    return render(request, "management/403.html", status=403)


def _get_admin_user_or_404(pk):
    try:
        return (
            User.objects.select_related("admin_profile")
            .prefetch_related("groups", "user_permissions")
            .get(pk=pk, role=Role.ADMIN)
        )
    except User.DoesNotExist as exc:
        raise Http404("Admin user not found.") from exc


def _get_admin_profile(user):
    try:
        return user.admin_profile
    except AdminProfile.DoesNotExist:
        return None


def _log_admin_audit(actor, action, description, request, target_user=None, metadata=None):
    AdminAuditLog.objects.create(
        actor=actor,
        action=action,
        target_user=target_user,
        description=description,
        metadata=metadata or {},
        ip_address=get_client_ip(request),
    )


@super_admin_required
def admin_list_view(request):
    query = request.GET.get("q", "").strip()
    is_active_filter = request.GET.get("is_active", "").strip()
    admin_users = (
        User.objects.filter(role=Role.ADMIN)
        .select_related("admin_profile")
        .prefetch_related("groups")
        .order_by("-date_joined")
    )

    if query:
        admin_users = admin_users.filter(
            Q(first_name__icontains=query)
            | Q(last_name__icontains=query)
            | Q(username__icontains=query)
            | Q(email__icontains=query)
            | Q(admin_profile__employee_id__icontains=query)
        )

    if is_active_filter in {"true", "false"}:
        admin_users = admin_users.filter(is_active=(is_active_filter == "true"))

    from django.core.paginator import Paginator

    paginator = Paginator(admin_users, 10)
    page_number = request.GET.get("page")
    page_obj = paginator.get_page(page_number)
    for user in page_obj:
        user.profile = _get_admin_profile(user)

    return render(
        request,
        "management/admins/list.html",
        {
            "page_obj": page_obj,
            "search_query": query,
            "is_active_filter": is_active_filter,
        },
    )


@super_admin_required
def admin_create_view(request):
    form = AdminCreateForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        with transaction.atomic():
            user = User(
                first_name=form.cleaned_data["first_name"],
                last_name=form.cleaned_data["last_name"],
                username=form.cleaned_data["username"],
                email=form.cleaned_data["email"],
                phone_number=form.cleaned_data["phone_number"] or None,
                role=Role.ADMIN,
                is_staff=True,
                is_superuser=False,
                is_active=True,
            )
            user.set_password(form.cleaned_data["password"])
            user.full_clean()
            user.save()
            user.groups.set(form.cleaned_data["groups"])
            user.user_permissions.set(form.cleaned_data["user_permissions"])

            profile = AdminProfile(
                user=user,
                employee_id=form.cleaned_data["employee_id"] or None,
                designation=form.cleaned_data["designation"],
                notes=form.cleaned_data["notes"],
                created_by=request.user,
            )
            profile.full_clean()
            profile.save()

            _log_admin_audit(
                actor=request.user,
                action=AdminAuditLog.Action.ADMIN_CREATED,
                description=f"Created admin account '{user.username}'.",
                request=request,
                target_user=user,
                metadata={
                    "groups": [group.name for group in user.groups.all()],
                    "permissions": [
                        permission.codename for permission in user.user_permissions.all()
                    ],
                },
            )

        return redirect("accounts:admin_detail", pk=user.pk)

    return render(request, "management/admins/create.html", {"form": form})


@super_admin_required
def admin_detail_view(request, pk):
    admin_user = _get_admin_user_or_404(pk)
    profile = _get_admin_profile(admin_user)
    return render(
        request,
        "management/admins/detail.html",
        {
            "admin_user": admin_user,
            "profile": profile,
        },
    )


@super_admin_required
def admin_edit_view(request, pk):
    admin_user = _get_admin_user_or_404(pk)
    profile = _get_admin_profile(admin_user)
    before_state = {
        "first_name": admin_user.first_name,
        "last_name": admin_user.last_name,
        "username": admin_user.username,
        "email": admin_user.email,
        "phone_number": admin_user.phone_number or "",
        "employee_id": profile.employee_id if profile else "",
        "designation": profile.designation if profile else "",
        "notes": profile.notes if profile else "",
        "groups": sorted(admin_user.groups.values_list("name", flat=True)),
        "permissions": sorted(admin_user.user_permissions.values_list("codename", flat=True)),
    }

    form = AdminUpdateForm(request.POST or None, instance=admin_user)
    if request.method == "POST" and form.is_valid():
        with transaction.atomic():
            form.save()
            profile_defaults = {
                "designation": form.cleaned_data["designation"],
                "notes": form.cleaned_data["notes"],
                "created_by": profile.created_by if profile else request.user,
            }
            admin_profile, created = AdminProfile.objects.get_or_create(
                user=admin_user,
                defaults={
                    "employee_id": form.cleaned_data["employee_id"] or None,
                    **profile_defaults,
                },
            )
            if not created:
                admin_profile.employee_id = form.cleaned_data["employee_id"] or None
                admin_profile.designation = form.cleaned_data["designation"]
                admin_profile.notes = form.cleaned_data["notes"]
            admin_profile.full_clean()
            admin_profile.save()

            after_state = {
                "first_name": admin_user.first_name,
                "last_name": admin_user.last_name,
                "username": admin_user.username,
                "email": admin_user.email,
                "phone_number": admin_user.phone_number or "",
                "employee_id": admin_profile.employee_id or "",
                "designation": admin_profile.designation,
                "notes": admin_profile.notes,
                "groups": sorted(admin_user.groups.values_list("name", flat=True)),
                "permissions": sorted(admin_user.user_permissions.values_list("codename", flat=True)),
            }
            changed_fields = {
                key: {"from": before_state.get(key), "to": after_state.get(key)}
                for key in after_state
                if before_state.get(key) != after_state.get(key)
            }

            if changed_fields:
                _log_admin_audit(
                    actor=request.user,
                    action=AdminAuditLog.Action.ADMIN_UPDATED,
                    description=f"Updated admin account '{admin_user.username}'.",
                    request=request,
                    target_user=admin_user,
                    metadata={"changed_fields": changed_fields},
                )

                if "groups" in changed_fields:
                    _log_admin_audit(
                        actor=request.user,
                        action=AdminAuditLog.Action.GROUP_ASSIGNED,
                        description=f"Updated groups for '{admin_user.username}'.",
                        request=request,
                        target_user=admin_user,
                        metadata={"groups": after_state["groups"]},
                    )
                if "permissions" in changed_fields:
                    _log_admin_audit(
                        actor=request.user,
                        action=AdminAuditLog.Action.PERMISSION_ASSIGNED,
                        description=f"Updated permissions for '{admin_user.username}'.",
                        request=request,
                        target_user=admin_user,
                        metadata={"permissions": after_state["permissions"]},
                    )

        return redirect("accounts:admin_detail", pk=admin_user.pk)

    return render(
        request,
        "management/admins/edit.html",
        {
            "form": form,
            "admin_user": admin_user,
        },
    )


@super_admin_required
def admin_toggle_status_view(request, pk):
    if request.method != "POST":
        return HttpResponseNotAllowed(["POST"])

    if request.user.pk == pk:
        return render(
            request,
            "management/403.html",
            {
                "error_message": "You cannot deactivate your own Super Admin account."
            },
            status=403,
        )

    admin_user = _get_admin_user_or_404(pk)

    with transaction.atomic():
        admin_user.is_active = not admin_user.is_active
        admin_user.save(update_fields=["is_active"])

        action = (
            AdminAuditLog.Action.ADMIN_ACTIVATED
            if admin_user.is_active
            else AdminAuditLog.Action.ADMIN_DEACTIVATED
        )
        _log_admin_audit(
            actor=request.user,
            action=action,
            description=f"{'Activated' if admin_user.is_active else 'Deactivated'} admin '{admin_user.username}'.",
            request=request,
            target_user=admin_user,
            metadata={"is_active": admin_user.is_active},
        )

    return redirect("accounts:admin_detail", pk=admin_user.pk)
