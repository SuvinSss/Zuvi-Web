from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator
from django.db import IntegrityError, transaction
from django.db.models import Prefetch, Q
from django.http import Http404, HttpResponseNotAllowed
from django.shortcuts import get_object_or_404, redirect, render

from accounts.models import AdminAuditLog

from .decorators import (
    get_portal_store_or_404,
    portal_stores_queryset,
    resolve_store_portal_membership,
    store_permission_required,
    store_portal_required,
    user_has_store_permission,
)
from .forms import (
    AddressForm,
    OptionalPrimaryStoreUserForm,
    StoreCreateForm,
    StoreForm,
    StorePortalProfileForm,
    StoreStatusChangeForm,
    StoreUserForm,
)
from .models import Store, StoreCategory, StoreStatus, StoreType, StoreUser
from .services import (
    create_additional_store_user,
    create_store,
    log_store_audit,
    record_status_change,
    transfer_store_user_primary,
)
from .status import (
    allowed_next_statuses,
    permission_for_transition,
)

def _get_store_or_404(pk):
    try:
        return (
            Store.objects.select_related("category", "address", "created_by")
            .prefetch_related(
                Prefetch(
                    "store_users",
                    queryset=StoreUser.objects.select_related("user").order_by(
                        "-is_primary", "user__username"
                    ),
                ),
                "status_history__changed_by",
            )
            .get(pk=pk)
        )
    except Store.DoesNotExist as exc:
        raise Http404("Store not found.") from exc


def _get_store_membership_or_404(store, user_id):
    return get_object_or_404(
        StoreUser.objects.select_related("user"),
        store=store,
        user_id=user_id,
    )


@store_permission_required("stores.view_store")
def store_list_view(request):
    queryset = Store.objects.select_related("category", "address").prefetch_related(
        Prefetch(
            "store_users",
            queryset=StoreUser.objects.filter(is_primary=True).select_related("user"),
            to_attr="primary_memberships",
        )
    )
    search_query = request.GET.get("q", "").strip()
    store_type_filter = request.GET.get("store_type", "").strip()
    category_filter = request.GET.get("category", "").strip()
    status_filter = request.GET.get("status", "").strip()
    is_active_filter = request.GET.get("is_active", "").strip()

    if search_query:
        queryset = queryset.filter(
            Q(store_code__icontains=search_query)
            | Q(name__icontains=search_query)
            | Q(email__icontains=search_query)
            | Q(contact_phone__icontains=search_query)
            | Q(alternative_phone__icontains=search_query)
            | Q(store_users__user__email__icontains=search_query)
        ).distinct()
    if store_type_filter:
        queryset = queryset.filter(store_type=store_type_filter)
    if category_filter:
        queryset = queryset.filter(category_id=category_filter)
    if status_filter:
        queryset = queryset.filter(status=status_filter)
    if is_active_filter == "true":
        queryset = queryset.filter(is_active=True)
    elif is_active_filter == "false":
        queryset = queryset.filter(is_active=False)

    page_obj = Paginator(queryset, 20).get_page(request.GET.get("page"))
    return render(
        request,
        "management/stores/list.html",
        {
            "page_obj": page_obj,
            "search_query": search_query,
            "store_type_filter": store_type_filter,
            "category_filter": category_filter,
            "status_filter": status_filter,
            "is_active_filter": is_active_filter,
            "store_type_choices": StoreType.choices,
            "status_choices": StoreStatus.choices,
            "categories": StoreCategory.objects.order_by("name"),
            "can_add_store": user_has_store_permission(request.user, "stores.add_store"),
        },
    )


@store_permission_required("stores.view_store")
def store_detail_view(request, pk):
    store = _get_store_or_404(pk)
    primary_user = next(
        (membership for membership in store.store_users.all() if membership.is_primary),
        None,
    )
    next_statuses = allowed_next_statuses(store.status)
    can_approve = user_has_store_permission(request.user, "stores.approve_store")
    can_suspend = user_has_store_permission(request.user, "stores.suspend_store")
    available_transitions = []
    for status_value in next_statuses:
        required = permission_for_transition(store.status, status_value)
        if required == "stores.suspend_store" and can_suspend:
            available_transitions.append(status_value)
        elif required == "stores.approve_store" and can_approve:
            available_transitions.append(status_value)

    return render(
        request,
        "management/stores/detail.html",
        {
            "store": store,
            "primary_user": primary_user,
            "status_form": StoreStatusChangeForm(current_status=store.status),
            "available_transitions": available_transitions,
            "can_change_store": user_has_store_permission(
                request.user, "stores.change_store"
            ),
            "can_approve_store": can_approve,
            "can_suspend_store": can_suspend,
            "can_view_store_users": user_has_store_permission(
                request.user, "stores.view_storeuser"
            ),
            "can_add_store_user": user_has_store_permission(
                request.user, "stores.add_storeuser"
            ),
            "can_change_store_user": user_has_store_permission(
                request.user, "stores.change_storeuser"
            ),
            "can_change_status": bool(available_transitions),
        },
    )

@store_permission_required("stores.add_store")
def store_create_view(request):
    can_activate = user_has_store_permission(request.user, "stores.approve_store")
    store_form = StoreCreateForm(
        request.POST or None,
        request.FILES or None,
        can_activate=can_activate,
    )
    address_form = AddressForm(request.POST or None, prefix="address")
    user_form = OptionalPrimaryStoreUserForm(request.POST or None, prefix="user")

    if request.method == "POST":
        forms_valid = all(
            form.is_valid() for form in (store_form, address_form, user_form)
        )
        if forms_valid:
            store_data = store_form.cleaned_data.copy()
            activate = store_data.pop("activate_on_create", False) and can_activate
            initial_status = (
                StoreStatus.ACTIVE if activate else StoreStatus.PENDING
            )
            store, _primary_user = create_store(
                store_data=store_data,
                address_data=address_form.cleaned_data,
                created_by=request.user,
                primary_user_data=user_form.to_user_data(),
                initial_status=initial_status,
                request=request,
            )
            messages.success(
                request,
                f"Store {store.store_code} created successfully.",
            )
            return redirect("stores:store_detail", pk=store.pk)

    return render(
        request,
        "management/stores/create.html",
        {
            "store_form": store_form,
            "address_form": address_form,
            "user_form": user_form,
            "can_activate": can_activate,
        },
    )


@store_permission_required("stores.change_store")
def store_edit_view(request, pk):
    store = _get_store_or_404(pk)
    store_form = StoreForm(
        request.POST or None,
        request.FILES or None,
        instance=store,
    )
    address_form = AddressForm(
        request.POST or None,
        instance=store.address,
        prefix="address",
    )

    if request.method == "POST" and store_form.is_valid() and address_form.is_valid():
        with transaction.atomic():
            address_form.save()
            updated = store_form.save()
            log_store_audit(
                actor=request.user,
                action=AdminAuditLog.Action.STORE_UPDATED,
                description=f"Updated store '{updated.store_code}'.",
                request=request,
                metadata={"store_id": updated.pk, "store_code": updated.store_code},
            )
        messages.success(request, "Store updated successfully.")
        return redirect("stores:store_detail", pk=store.pk)

    return render(
        request,
        "management/stores/edit.html",
        {
            "store": store,
            "store_form": store_form,
            "address_form": address_form,
        },
    )


@store_permission_required("stores.view_store")
def store_change_status_view(request, pk):
    if request.method != "POST":
        return HttpResponseNotAllowed(["POST"])

    store = _get_store_or_404(pk)
    form = StoreStatusChangeForm(request.POST, current_status=store.status)
    if not form.is_valid():
        for error in form.errors.get("reason", []):
            messages.error(request, error)
        for error in form.errors.get("new_status", []):
            messages.error(request, error)
        if not form.errors.get("reason") and not form.errors.get("new_status"):
            messages.error(request, "Invalid status change request.")
        return redirect("stores:store_detail", pk=store.pk)

    new_status = form.cleaned_data["new_status"]
    required_permission = permission_for_transition(store.status, new_status)
    if not required_permission or not user_has_store_permission(
        request.user, required_permission
    ):
        raise PermissionDenied("You do not have permission to set that store status.")

    record_status_change(
        store=store,
        new_status=new_status,
        changed_by=request.user,
        reason=form.cleaned_data.get("reason", ""),
        request=request,
    )
    messages.success(request, f"Store status changed to {new_status}.")
    return redirect("stores:store_detail", pk=store.pk)


@store_permission_required("stores.view_storeuser")
def store_user_list_view(request, pk):
    store = _get_store_or_404(pk)
    memberships = store.store_users.select_related("user", "created_by")
    return render(
        request,
        "management/stores/users_list.html",
        {
            "store": store,
            "memberships": memberships,
            "can_add_store_user": user_has_store_permission(
                request.user, "stores.add_storeuser"
            ),
            "can_change_store_user": user_has_store_permission(
                request.user, "stores.change_storeuser"
            ),
        },
    )


@store_permission_required("stores.add_storeuser")
def store_user_create_view(request, pk):
    store = _get_store_or_404(pk)
    form = StoreUserForm(
        request.POST or None,
        store=store,
        require_password=True,
    )

    if request.method == "POST" and form.is_valid():
        user_data = {
            "username": form.cleaned_data["username"],
            "email": form.cleaned_data["email"],
            "first_name": form.cleaned_data.get("first_name", ""),
            "last_name": form.cleaned_data.get("last_name", ""),
            "phone_number": form.cleaned_data.get("phone_number"),
            "password": form.cleaned_data["password"],
            "designation": form.cleaned_data.get("designation", ""),
        }
        try:
            membership, user = create_additional_store_user(
                store=store,
                user_data=user_data,
                created_by=request.user,
                request=request,
                is_primary=bool(form.cleaned_data.get("is_primary")),
            )
        except IntegrityError:
            messages.error(
                request,
                "Could not save Store User because of a concurrent primary assignment.",
            )
            return render(
                request,
                "management/stores/user_create.html",
                {"store": store, "form": form},
            )
        messages.success(
            request,
            f"Store user {user.username} created successfully.",
        )
        return redirect("stores:store_user_list", pk=store.pk)

    return render(
        request,
        "management/stores/user_create.html",
        {"store": store, "form": form},
    )


@store_permission_required("stores.change_storeuser")
def store_user_edit_view(request, pk, user_id):
    store = _get_store_or_404(pk)
    membership = _get_store_membership_or_404(store, user_id)
    form = StoreUserForm(
        request.POST or None,
        instance=membership,
        store=store,
        require_password=False,
    )

    if request.method == "POST" and form.is_valid():
        user = membership.user
        user.first_name = form.cleaned_data.get("first_name", "")
        user.last_name = form.cleaned_data.get("last_name", "")
        user.username = form.cleaned_data["username"]
        user.email = form.cleaned_data["email"]
        user.phone_number = form.cleaned_data.get("phone_number")
        password = form.cleaned_data.get("password")
        try:
            with transaction.atomic():
                if password:
                    user.set_password(password)
                user.full_clean()
                user.save()
                membership.designation = form.cleaned_data.get("designation", "")
                if form.cleaned_data.get("is_primary"):
                    transfer_store_user_primary(store=store, membership=membership)
                else:
                    membership.is_primary = False
                membership.full_clean()
                membership.save()
                log_store_audit(
                    actor=request.user,
                    action=AdminAuditLog.Action.STORE_USER_UPDATED,
                    description=(
                        f"Updated store user '{user.username}' "
                        f"for store '{store.store_code}'."
                    ),
                    request=request,
                    target_user=user,
                    metadata={
                        "store_id": store.pk,
                        "store_code": store.store_code,
                        "password_changed": bool(password),
                    },
                )
        except IntegrityError:
            messages.error(
                request,
                "Could not update Store User because of a concurrent primary assignment.",
            )
            return render(
                request,
                "management/stores/user_edit.html",
                {"store": store, "membership": membership, "form": form},
            )
        messages.success(request, f"Store user {user.username} updated.")
        return redirect("stores:store_user_list", pk=store.pk)

    return render(
        request,
        "management/stores/user_edit.html",
        {"store": store, "membership": membership, "form": form},
    )


@store_permission_required("stores.change_storeuser")
def store_user_toggle_status_view(request, pk, user_id):
    if request.method != "POST":
        return HttpResponseNotAllowed(["POST"])

    store = _get_store_or_404(pk)
    membership = _get_store_membership_or_404(store, user_id)
    with transaction.atomic():
        membership.is_active = not membership.is_active
        membership.save(update_fields=["is_active", "updated_at"])
        action = (
            AdminAuditLog.Action.STORE_USER_ACTIVATED
            if membership.is_active
            else AdminAuditLog.Action.STORE_USER_DEACTIVATED
        )
        state = "activated" if membership.is_active else "deactivated"
        log_store_audit(
            actor=request.user,
            action=action,
            description=(
                f"{state.capitalize()} store user '{membership.user.username}' "
                f"for store '{store.store_code}'."
            ),
            request=request,
            target_user=membership.user,
            metadata={
                "store_id": store.pk,
                "store_code": store.store_code,
                "is_active": membership.is_active,
            },
        )
    messages.success(request, f"Store user {membership.user.username} {state}.")
    return redirect("stores:store_user_list", pk=store.pk)

def store_portal_login_view(request):
    from django.contrib.auth import login
    from django.contrib.auth.forms import AuthenticationForm

    from accounts.models import Role

    if request.user.is_authenticated and request.user.role == Role.STORE_USER:
        membership, denial = resolve_store_portal_membership(request.user)
        if membership is not None:
            return redirect("stores:store_portal_dashboard")

    form = AuthenticationForm(request, data=request.POST or None)
    if request.method == "POST" and form.is_valid():
        user = form.get_user()
        membership, denial = resolve_store_portal_membership(user)
        if membership is None:
            # AuthenticationForm already authenticated credentials; deny portal entry.
            form.add_error(None, denial or "This account cannot access the store portal.")
        else:
            login(request, user)
            return redirect("stores:store_portal_dashboard")

    return render(request, "store_portal/login.html", {"form": form})


def store_portal_logout_view(request):
    from django.contrib.auth import logout

    if request.method != "POST":
        return HttpResponseNotAllowed(["POST"])
    logout(request)
    return redirect("stores:store_portal_login")


@store_portal_required
def store_portal_dashboard_view(request):
    store = get_portal_store_or_404(request.user)
    return render(
        request,
        "store_portal/dashboard.html",
        {
            "store": store,
            "membership": request.store_membership,
        },
    )


@store_portal_required
def store_portal_profile_view(request):
    # Client-supplied store IDs must resolve through the membership queryset so
    # foreign IDs return 404 instead of confirming another store exists.
    requested_store_id = request.GET.get("store_id") or request.POST.get("store_id")
    store = get_portal_store_or_404(
        request.user,
        store_id=requested_store_id if requested_store_id else None,
    )

    membership = request.store_membership
    form = StorePortalProfileForm(
        request.POST or None,
        user=request.user,
        membership=membership,
        store=store,
    )
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Profile updated successfully.")
        return redirect("stores:store_portal_profile")

    return render(
        request,
        "store_portal/profile.html",
        {
            "store": store,
            "membership": membership,
            "form": form,
            "stores_queryset": portal_stores_queryset(request.user),
        },
    )
