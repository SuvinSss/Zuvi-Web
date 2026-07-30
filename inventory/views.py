from django.contrib import messages
from django.core.exceptions import ValidationError
from django.core.paginator import Paginator
from django.db.models import OuterRef, Prefetch, Q, Subquery
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_GET, require_http_methods

from accounts.models import AdminAuditLog
from catalog.models import Product, ProductCategory, ProductImage, ProductStatus
from stores.decorators import store_portal_required
from stores.models import Store

from .decorators import (
    get_management_product_or_404,
    get_portal_inventory_product_or_404,
    inventory_permission_required,
    inventory_view_permission_required,
    management_products_queryset,
    management_transactions_queryset,
    portal_inventory_products_queryset,
    portal_transactions_queryset,
    store_inventory_manage_required,
    user_has_inventory_permission,
)
from .export import (
    apply_inventory_list_filters,
    build_inventory_export_queryset,
    render_inventory_csv_response,
)
from .forms import (
    ProductScopedMovementForm,
    PurchaseEntryCreateForm,
    consume_purchase_submission_token,
    issue_purchase_submission_token,
)
from .models import InventoryTransaction, PurchaseEntry, PurchaseEntryStatus
from .services import (
    log_inventory_audit,
    record_adjustment_in,
    record_adjustment_out,
    record_damaged_stock,
    record_expired_stock,
    record_manual_stock_in,
    record_manual_stock_out,
    record_purchase_stock_in,
)
from .status import stock_status_for_product


def _permission_flags(user):
    return {
        "can_export": user_has_inventory_permission(user, "inventory.export_inventory"),
        "can_record_purchase": user_has_inventory_permission(
            user, "inventory.record_purchase"
        ),
        "can_adjust": user_has_inventory_permission(
            user, "inventory.adjust_inventory"
        ),
        "can_record_damage": user_has_inventory_permission(
            user, "inventory.record_damage"
        ),
        "can_record_expiry": user_has_inventory_permission(
            user, "inventory.record_expiry"
        ),
    }


def _latest_movement_subqueries():
    latest = InventoryTransaction.objects.filter(product_id=OuterRef("pk")).order_by(
        "-created_at"
    )
    return {
        "last_movement_at": Subquery(latest.values("created_at")[:1]),
        "last_movement_type": Subquery(latest.values("transaction_type")[:1]),
        "last_movement_number": Subquery(latest.values("transaction_number")[:1]),
    }


def _filters_from_request(request):
    return {
        "search_query": request.GET.get("q", "").strip(),
        "store_filter": request.GET.get("store", "").strip(),
        "category_filter": request.GET.get("category", "").strip(),
        "status_filter": request.GET.get("status", "").strip(),
        "stock_filter": request.GET.get("stock", "").strip(),
    }


@inventory_view_permission_required
@require_GET
def management_inventory_list_view(request):
    primary_images = Prefetch(
        "images",
        queryset=ProductImage.objects.filter(is_primary=True),
        to_attr="primary_image_list",
    )
    filters = _filters_from_request(request)
    queryset = apply_inventory_list_filters(
        management_products_queryset(request.user)
        .select_related("store", "category")
        .prefetch_related(primary_images)
        .annotate(**_latest_movement_subqueries())
        .order_by("name"),
        **filters,
    )

    page_obj = Paginator(queryset, 20).get_page(request.GET.get("page"))
    for product in page_obj.object_list:
        product.stock_status_label = stock_status_for_product(product)

    context = {
        "page_obj": page_obj,
        "status_choices": ProductStatus.choices,
        "stores": Store.objects.order_by("name"),
        "categories": ProductCategory.objects.order_by("name"),
        "export_querystring": request.GET.urlencode(),
        **filters,
        **_permission_flags(request.user),
    }
    return render(request, "management/inventory/list.html", context)


@inventory_permission_required("inventory.export_inventory")
@require_GET
def management_inventory_export_view(request):
    filters = _filters_from_request(request)
    queryset = build_inventory_export_queryset(
        apply_inventory_list_filters(
            management_products_queryset(request.user),
            **filters,
        )
    )
    return render_inventory_csv_response(
        queryset,
        filename="inventory_export.csv",
    )


@inventory_view_permission_required
@require_GET
def management_product_inventory_view(request, product_id):
    product = get_management_product_or_404(request.user, product_id)
    product = (
        Product.objects.select_related("store", "category", "brand")
        .prefetch_related(
            Prefetch(
                "images",
                queryset=ProductImage.objects.order_by("sort_order", "pk"),
            )
        )
        .get(pk=product.pk)
    )
    transactions = (
        management_transactions_queryset(request.user)
        .filter(product=product)
        .select_related("created_by", "purchase_entry")
        .order_by("-created_at")[:100]
    )
    purchases = (
        PurchaseEntry.objects.filter(lines__product=product)
        .select_related("created_by", "confirmed_by", "store")
        .distinct()
        .order_by("-created_at")[:50]
    )
    context = {
        "product": product,
        "stock_status_label": stock_status_for_product(product),
        "transactions": transactions,
        "purchases": purchases,
        **_permission_flags(request.user),
    }
    return render(request, "management/inventory/product_detail.html", context)


def _render_product_movement(request, *, product, title, form):
    return render(
        request,
        "management/inventory/movement_form.html",
        {
            "title": title,
            "form": form,
            "product": product,
            **_permission_flags(request.user),
        },
    )


def _audit_movement(*, actor, action, product, txn, request, extra=None):
    metadata = {
        "product_id": product.pk,
        "product_code": product.product_code,
        "store_id": product.store_id,
        "transaction_number": txn.transaction_number,
        "quantity": str(txn.quantity),
        "previous_quantity": str(txn.previous_quantity),
        "new_quantity": str(txn.new_quantity),
        "transaction_type": txn.transaction_type,
    }
    if extra:
        metadata.update(extra)
    log_inventory_audit(
        actor=actor,
        action=action,
        description=(
            f"{txn.get_transaction_type_display()} on '{product.name}' "
            f"({product.product_code}): {txn.previous_quantity} → {txn.new_quantity}."
        ),
        request=request,
        metadata=metadata,
    )


@inventory_permission_required("inventory.adjust_inventory")
@require_http_methods(["GET", "POST"])
def management_product_stock_in_view(request, product_id):
    product = get_management_product_or_404(request.user, product_id)
    form = ProductScopedMovementForm(request.POST or None, product=product)
    if request.method == "POST" and form.is_valid():
        try:
            txn = record_manual_stock_in(
                product=product,
                store=product.store,
                quantity=form.cleaned_data["quantity"],
                actor=request.user,
                reason=form.cleaned_data.get("reason", ""),
                notes=form.cleaned_data.get("notes", ""),
                reference=form.cleaned_data.get("reference", ""),
                unit_cost=form.cleaned_data.get("unit_cost"),
                manufacturing_date=form.cleaned_data.get("manufacturing_date"),
                expiry_date=form.cleaned_data.get("expiry_date"),
                request=request,
            )
        except ValidationError as exc:
            form.add_error(None, exc)
        else:
            _audit_movement(
                actor=request.user,
                action=AdminAuditLog.Action.INVENTORY_STOCK_IN,
                product=product,
                txn=txn,
                request=request,
            )
            messages.success(request, "Stock-in recorded.")
            return redirect("inventory:management_product_inventory", product_id=product.pk)
    return _render_product_movement(
        request, product=product, title="Manual stock-in", form=form
    )


@inventory_permission_required("inventory.adjust_inventory")
@require_http_methods(["GET", "POST"])
def management_product_stock_out_view(request, product_id):
    product = get_management_product_or_404(request.user, product_id)
    form = ProductScopedMovementForm(
        request.POST or None, product=product, require_reason=True
    )
    if request.method == "POST" and form.is_valid():
        try:
            txn = record_manual_stock_out(
                product=product,
                store=product.store,
                quantity=form.cleaned_data["quantity"],
                actor=request.user,
                reason=form.cleaned_data["reason"],
                notes=form.cleaned_data.get("notes", ""),
                reference=form.cleaned_data.get("reference", ""),
                request=request,
            )
        except ValidationError as exc:
            form.add_error(None, exc)
        else:
            _audit_movement(
                actor=request.user,
                action=AdminAuditLog.Action.INVENTORY_STOCK_OUT,
                product=product,
                txn=txn,
                request=request,
            )
            messages.success(request, "Stock-out recorded.")
            return redirect("inventory:management_product_inventory", product_id=product.pk)
    return _render_product_movement(
        request, product=product, title="Manual stock-out", form=form
    )


@inventory_permission_required("inventory.adjust_inventory")
@require_http_methods(["GET", "POST"])
def management_product_adjust_view(request, product_id):
    product = get_management_product_or_404(request.user, product_id)
    form = ProductScopedMovementForm(
        request.POST or None,
        product=product,
        require_reason=True,
        show_direction=True,
    )
    if request.method == "POST" and form.is_valid():
        direction = form.cleaned_data.get("direction") or "IN"
        try:
            kwargs = dict(
                product=product,
                store=product.store,
                quantity=form.cleaned_data["quantity"],
                actor=request.user,
                reason=form.cleaned_data["reason"],
                notes=form.cleaned_data.get("notes", ""),
                reference=form.cleaned_data.get("reference", ""),
                request=request,
            )
            if direction == "OUT":
                txn = record_adjustment_out(**kwargs)
            else:
                txn = record_adjustment_in(**kwargs)
        except ValidationError as exc:
            form.add_error(None, exc)
        else:
            _audit_movement(
                actor=request.user,
                action=AdminAuditLog.Action.INVENTORY_ADJUSTED,
                product=product,
                txn=txn,
                request=request,
                extra={"direction": direction},
            )
            messages.success(request, "Inventory adjustment recorded.")
            return redirect("inventory:management_product_inventory", product_id=product.pk)
    return _render_product_movement(
        request, product=product, title="Adjust inventory", form=form
    )


@inventory_permission_required("inventory.record_damage")
@require_http_methods(["GET", "POST"])
def management_product_damage_view(request, product_id):
    product = get_management_product_or_404(request.user, product_id)
    form = ProductScopedMovementForm(
        request.POST or None, product=product, require_reason=True
    )
    if request.method == "POST" and form.is_valid():
        try:
            txn = record_damaged_stock(
                product=product,
                store=product.store,
                quantity=form.cleaned_data["quantity"],
                actor=request.user,
                reason=form.cleaned_data["reason"],
                notes=form.cleaned_data.get("notes", ""),
                reference=form.cleaned_data.get("reference", ""),
                request=request,
            )
        except ValidationError as exc:
            form.add_error(None, exc)
        else:
            _audit_movement(
                actor=request.user,
                action=AdminAuditLog.Action.INVENTORY_DAMAGE_RECORDED,
                product=product,
                txn=txn,
                request=request,
            )
            messages.success(request, "Damaged stock recorded.")
            return redirect("inventory:management_product_inventory", product_id=product.pk)
    return _render_product_movement(
        request, product=product, title="Record damaged stock", form=form
    )


@inventory_permission_required("inventory.record_expiry")
@require_http_methods(["GET", "POST"])
def management_product_expire_view(request, product_id):
    product = get_management_product_or_404(request.user, product_id)
    form = ProductScopedMovementForm(
        request.POST or None, product=product, require_reason=True
    )
    if request.method == "POST" and form.is_valid():
        try:
            txn = record_expired_stock(
                product=product,
                store=product.store,
                quantity=form.cleaned_data["quantity"],
                actor=request.user,
                reason=form.cleaned_data["reason"],
                notes=form.cleaned_data.get("notes", ""),
                reference=form.cleaned_data.get("reference", ""),
                manufacturing_date=form.cleaned_data.get("manufacturing_date"),
                expiry_date=form.cleaned_data.get("expiry_date"),
                request=request,
            )
        except ValidationError as exc:
            form.add_error(None, exc)
        else:
            _audit_movement(
                actor=request.user,
                action=AdminAuditLog.Action.INVENTORY_EXPIRY_RECORDED,
                product=product,
                txn=txn,
                request=request,
            )
            messages.success(request, "Expired stock recorded.")
            return redirect("inventory:management_product_inventory", product_id=product.pk)
    return _render_product_movement(
        request, product=product, title="Record expired stock", form=form
    )


# ---------------------------------------------------------------------------
# Purchases
# ---------------------------------------------------------------------------


def _purchase_form_with_fresh_token(request, post_data, **form_kwargs):
    """Rebuild a bound purchase form with a new one-time submission token."""
    data = post_data.copy()
    data["submission_token"] = issue_purchase_submission_token(request)
    return PurchaseEntryCreateForm(data, **form_kwargs)


@inventory_view_permission_required
@require_GET
def management_purchase_list_view(request):
    queryset = PurchaseEntry.objects.select_related(
        "store", "created_by", "confirmed_by"
    ).order_by("-created_at")
    store_filter = request.GET.get("store", "").strip()
    status_filter = request.GET.get("status", "").strip()
    search_query = request.GET.get("q", "").strip()
    if store_filter:
        queryset = queryset.filter(store_id=store_filter)
    if status_filter:
        queryset = queryset.filter(status=status_filter)
    if search_query:
        queryset = queryset.filter(
            Q(entry_number__icontains=search_query)
            | Q(supplier_name__icontains=search_query)
            | Q(supplier_invoice_number__icontains=search_query)
        )
    page_obj = Paginator(queryset, 20).get_page(request.GET.get("page"))
    return render(
        request,
        "management/inventory/purchase_list.html",
        {
            "page_obj": page_obj,
            "stores": Store.objects.order_by("name"),
            "store_filter": store_filter,
            "status_filter": status_filter,
            "search_query": search_query,
            "status_choices": PurchaseEntryStatus.choices,
            **_permission_flags(request.user),
        },
    )


@inventory_permission_required("inventory.record_purchase")
@require_http_methods(["GET", "POST"])
def management_purchase_create_view(request):
    initial_product = request.GET.get("product")
    product_qs = management_products_queryset(request.user)

    if request.method == "POST":
        token_ok = consume_purchase_submission_token(
            request, request.POST.get("submission_token", "")
        )
        form = PurchaseEntryCreateForm(request.POST, product_queryset=product_qs)
        if not token_ok:
            form = _purchase_form_with_fresh_token(
                request, request.POST, product_queryset=product_qs
            )
            form.is_valid()
            form.add_error(
                None,
                "This purchase form was already submitted or expired. "
                "Please try again.",
            )
        elif form.is_valid():
            product = form.cleaned_data["product"]
            try:
                entry, txns = record_purchase_stock_in(
                    store=product.store,
                    supplier_name=form.cleaned_data["supplier_name"],
                    entry_date=form.cleaned_data["entry_date"],
                    actor=request.user,
                    supplier_invoice_number=form.cleaned_data.get(
                        "supplier_invoice_number", ""
                    ),
                    notes=form.cleaned_data.get("notes", ""),
                    lines=[
                        {
                            "product": product,
                            "quantity": form.cleaned_data["quantity"],
                            "unit_cost": form.cleaned_data["unit_cost"],
                        }
                    ],
                    request=request,
                )
            except ValidationError as exc:
                form = _purchase_form_with_fresh_token(
                    request, request.POST, product_queryset=product_qs
                )
                form.is_valid()
                form.add_error(None, exc)
            else:
                log_inventory_audit(
                    actor=request.user,
                    action=AdminAuditLog.Action.PURCHASE_ENTRY_CONFIRMED,
                    description=(
                        f"Confirmed purchase {entry.entry_number} for store "
                        f"{entry.store.store_code}."
                    ),
                    request=request,
                    metadata={
                        "purchase_entry_id": entry.pk,
                        "entry_number": entry.entry_number,
                        "total_cost": str(entry.total_cost),
                        "transaction_numbers": [t.transaction_number for t in txns],
                    },
                )
                messages.success(request, f"Purchase {entry.entry_number} confirmed.")
                return redirect("inventory:management_purchase_detail", pk=entry.pk)
        else:
            form = _purchase_form_with_fresh_token(
                request, request.POST, product_queryset=product_qs
            )
            form.is_valid()
    else:
        form = PurchaseEntryCreateForm(
            product_queryset=product_qs,
            submission_token=issue_purchase_submission_token(request),
            initial={"product": initial_product} if initial_product else None,
        )

    return render(
        request,
        "management/inventory/purchase_form.html",
        {
            "form": form,
            "title": "Create purchase entry",
            **_permission_flags(request.user),
        },
    )


@inventory_view_permission_required
@require_GET
def management_purchase_detail_view(request, pk):
    entry = get_object_or_404(
        PurchaseEntry.objects.select_related(
            "store", "created_by", "confirmed_by"
        ).prefetch_related("lines__product", "inventory_transactions"),
        pk=pk,
    )
    return render(
        request,
        "management/inventory/purchase_detail.html",
        {
            "entry": entry,
            "lines": entry.lines.select_related("product"),
            "transactions": entry.inventory_transactions.select_related(
                "product", "created_by"
            ),
            **_permission_flags(request.user),
        },
    )


# ---------------------------------------------------------------------------
# Store portal
# ---------------------------------------------------------------------------


def _store_can_manage(request):
    return bool(
        getattr(request, "store_membership", None)
        and request.store_membership.can_manage_inventory
    )


def _render_store_movement(request, *, product, title, form):
    return render(
        request,
        "store_portal/inventory/movement_form.html",
        {
            "title": title,
            "form": form,
            "product": product,
            "can_manage_inventory": _store_can_manage(request),
        },
    )


@store_portal_required
@require_GET
def store_inventory_list_view(request):
    filters = {
        "search_query": request.GET.get("q", "").strip(),
        "stock_filter": request.GET.get("stock", "").strip(),
    }
    queryset = apply_inventory_list_filters(
        portal_inventory_products_queryset(request).order_by("name"),
        search_query=filters["search_query"],
        stock_filter=filters["stock_filter"],
    )

    page_obj = Paginator(queryset, 20).get_page(request.GET.get("page"))
    for product in page_obj.object_list:
        product.stock_status_label = stock_status_for_product(product)

    return render(
        request,
        "store_portal/inventory/list.html",
        {
            "page_obj": page_obj,
            "export_querystring": request.GET.urlencode(),
            "can_manage_inventory": _store_can_manage(request),
            **filters,
        },
    )


@store_portal_required
@require_GET
def store_inventory_export_view(request):
    """Store Users may export only their authenticated store's inventory."""
    queryset = build_inventory_export_queryset(
        apply_inventory_list_filters(
            portal_inventory_products_queryset(request),
            search_query=request.GET.get("q", "").strip(),
            stock_filter=request.GET.get("stock", "").strip(),
        )
    )
    store_code = getattr(request.store, "store_code", "store")
    return render_inventory_csv_response(
        queryset,
        filename=f"inventory_export_{store_code}.csv",
    )


@store_portal_required
@require_GET
def store_product_inventory_view(request, product_id):
    product = get_portal_inventory_product_or_404(request, product_id)
    transactions = (
        portal_transactions_queryset(request)
        .filter(product=product)
        .select_related("created_by")
        .order_by("-created_at")[:100]
    )
    purchases = (
        PurchaseEntry.objects.filter(store=request.store, lines__product=product)
        .distinct()
        .order_by("-created_at")[:50]
    )
    return render(
        request,
        "store_portal/inventory/product_detail.html",
        {
            "product": product,
            "stock_status_label": stock_status_for_product(product),
            "transactions": transactions,
            "purchases": purchases,
            "can_manage_inventory": _store_can_manage(request),
        },
    )


@store_inventory_manage_required
@require_http_methods(["GET", "POST"])
def store_product_stock_in_view(request, product_id):
    product = get_portal_inventory_product_or_404(request, product_id)
    form = ProductScopedMovementForm(request.POST or None, product=product)
    if request.method == "POST" and form.is_valid():
        try:
            record_manual_stock_in(
                product=product,
                store=request.store,
                quantity=form.cleaned_data["quantity"],
                actor=request.user,
                reason=form.cleaned_data.get("reason", "") or "Store stock-in",
                notes=form.cleaned_data.get("notes", ""),
                reference=form.cleaned_data.get("reference", ""),
                unit_cost=form.cleaned_data.get("unit_cost"),
                manufacturing_date=form.cleaned_data.get("manufacturing_date"),
                expiry_date=form.cleaned_data.get("expiry_date"),
                request=request,
            )
        except ValidationError as exc:
            form.add_error(None, exc)
        else:
            messages.success(request, "Stock-in recorded.")
            return redirect(
                "inventory:store_product_inventory", product_id=product.pk
            )
    return _render_store_movement(
        request, product=product, title="Stock-in", form=form
    )


@store_inventory_manage_required
@require_http_methods(["GET", "POST"])
def store_product_stock_out_view(request, product_id):
    product = get_portal_inventory_product_or_404(request, product_id)
    form = ProductScopedMovementForm(
        request.POST or None, product=product, require_reason=True
    )
    if request.method == "POST" and form.is_valid():
        try:
            record_manual_stock_out(
                product=product,
                store=request.store,
                quantity=form.cleaned_data["quantity"],
                actor=request.user,
                reason=form.cleaned_data["reason"],
                notes=form.cleaned_data.get("notes", ""),
                reference=form.cleaned_data.get("reference", ""),
                request=request,
            )
        except ValidationError as exc:
            form.add_error(None, exc)
        else:
            messages.success(request, "Stock-out recorded.")
            return redirect(
                "inventory:store_product_inventory", product_id=product.pk
            )
    return _render_store_movement(
        request, product=product, title="Stock-out", form=form
    )


@store_inventory_manage_required
@require_http_methods(["GET", "POST"])
def store_product_adjust_view(request, product_id):
    product = get_portal_inventory_product_or_404(request, product_id)
    form = ProductScopedMovementForm(
        request.POST or None,
        product=product,
        require_reason=True,
        show_direction=True,
    )
    if request.method == "POST" and form.is_valid():
        direction = form.cleaned_data.get("direction") or "IN"
        try:
            kwargs = dict(
                product=product,
                store=request.store,
                quantity=form.cleaned_data["quantity"],
                actor=request.user,
                reason=form.cleaned_data["reason"],
                notes=form.cleaned_data.get("notes", ""),
                reference=form.cleaned_data.get("reference", ""),
                request=request,
            )
            if direction == "OUT":
                record_adjustment_out(**kwargs)
            else:
                record_adjustment_in(**kwargs)
        except ValidationError as exc:
            form.add_error(None, exc)
        else:
            messages.success(request, "Inventory adjustment recorded.")
            return redirect(
                "inventory:store_product_inventory", product_id=product.pk
            )
    return _render_store_movement(
        request, product=product, title="Adjust inventory", form=form
    )


@store_inventory_manage_required
@require_http_methods(["GET", "POST"])
def store_product_damage_view(request, product_id):
    product = get_portal_inventory_product_or_404(request, product_id)
    form = ProductScopedMovementForm(
        request.POST or None, product=product, require_reason=True
    )
    if request.method == "POST" and form.is_valid():
        try:
            record_damaged_stock(
                product=product,
                store=request.store,
                quantity=form.cleaned_data["quantity"],
                actor=request.user,
                reason=form.cleaned_data["reason"],
                notes=form.cleaned_data.get("notes", ""),
                reference=form.cleaned_data.get("reference", ""),
                request=request,
            )
        except ValidationError as exc:
            form.add_error(None, exc)
        else:
            messages.success(request, "Damaged stock recorded.")
            return redirect(
                "inventory:store_product_inventory", product_id=product.pk
            )
    return _render_store_movement(
        request, product=product, title="Record damaged stock", form=form
    )


@store_inventory_manage_required
@require_http_methods(["GET", "POST"])
def store_product_expire_view(request, product_id):
    product = get_portal_inventory_product_or_404(request, product_id)
    form = ProductScopedMovementForm(
        request.POST or None, product=product, require_reason=True
    )
    if request.method == "POST" and form.is_valid():
        try:
            record_expired_stock(
                product=product,
                store=request.store,
                quantity=form.cleaned_data["quantity"],
                actor=request.user,
                reason=form.cleaned_data["reason"],
                notes=form.cleaned_data.get("notes", ""),
                reference=form.cleaned_data.get("reference", ""),
                manufacturing_date=form.cleaned_data.get("manufacturing_date"),
                expiry_date=form.cleaned_data.get("expiry_date"),
                request=request,
            )
        except ValidationError as exc:
            form.add_error(None, exc)
        else:
            messages.success(request, "Expired stock recorded.")
            return redirect(
                "inventory:store_product_inventory", product_id=product.pk
            )
    return _render_store_movement(
        request, product=product, title="Record expired stock", form=form
    )


@store_portal_required
@require_GET
def store_purchase_list_view(request):
    from django.core.paginator import Paginator

    from .decorators import portal_purchase_entries_queryset

    queryset = portal_purchase_entries_queryset(request).order_by("-created_at")
    page_obj = Paginator(queryset, 20).get_page(request.GET.get("page"))
    return render(
        request,
        "store_portal/inventory/purchase_list.html",
        {
            "page_obj": page_obj,
            "can_manage_inventory": _store_can_manage(request),
        },
    )


@store_inventory_manage_required
@require_http_methods(["GET", "POST"])
def store_purchase_create_view(request):
    initial_product = request.GET.get("product")
    product_qs = portal_inventory_products_queryset(request)
    form_kwargs = {
        "product_queryset": product_qs,
        "locked_store": request.store,
    }

    if request.method == "POST":
        token_ok = consume_purchase_submission_token(
            request, request.POST.get("submission_token", "")
        )
        form = PurchaseEntryCreateForm(request.POST, **form_kwargs)
        if not token_ok:
            form = _purchase_form_with_fresh_token(request, request.POST, **form_kwargs)
            form.is_valid()
            form.add_error(
                None,
                "This purchase form was already submitted or expired. "
                "Please try again.",
            )
        elif form.is_valid():
            # Always use authenticated store membership — never trust form store_id.
            try:
                entry, _txns = record_purchase_stock_in(
                    store=request.store,
                    supplier_name=form.cleaned_data["supplier_name"],
                    entry_date=form.cleaned_data["entry_date"],
                    actor=request.user,
                    supplier_invoice_number=form.cleaned_data.get(
                        "supplier_invoice_number", ""
                    ),
                    notes=form.cleaned_data.get("notes", ""),
                    lines=[
                        {
                            "product": form.cleaned_data["product"],
                            "quantity": form.cleaned_data["quantity"],
                            "unit_cost": form.cleaned_data["unit_cost"],
                        }
                    ],
                    request=request,
                )
            except ValidationError as exc:
                form = _purchase_form_with_fresh_token(
                    request, request.POST, **form_kwargs
                )
                form.is_valid()
                form.add_error(None, exc)
            else:
                messages.success(request, f"Purchase {entry.entry_number} confirmed.")
                return redirect("inventory:store_purchase_detail", pk=entry.pk)
        else:
            form = _purchase_form_with_fresh_token(request, request.POST, **form_kwargs)
            form.is_valid()
    else:
        form = PurchaseEntryCreateForm(
            submission_token=issue_purchase_submission_token(request),
            initial={"product": initial_product} if initial_product else None,
            **form_kwargs,
        )

    return render(
        request,
        "store_portal/inventory/purchase_form.html",
        {
            "form": form,
            "title": "Create purchase",
            "can_manage_inventory": True,
        },
    )


@store_portal_required
@require_GET
def store_purchase_detail_view(request, pk):
    from .decorators import portal_purchase_entries_queryset

    entry = get_object_or_404(
        portal_purchase_entries_queryset(request)
        .select_related("created_by", "confirmed_by", "store")
        .prefetch_related("lines__product", "inventory_transactions__product"),
        pk=pk,
    )
    return render(
        request,
        "store_portal/inventory/purchase_detail.html",
        {
            "entry": entry,
            "lines": entry.lines.select_related("product"),
            "transactions": entry.inventory_transactions.select_related(
                "product", "created_by"
            ),
            "can_manage_inventory": _store_can_manage(request),
        },
    )
