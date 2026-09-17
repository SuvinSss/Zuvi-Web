"""Atomic product-entry composition; business rules remain in their services."""
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.http import Http404

from inventory.decorators import user_has_inventory_permission
from inventory.models import InventoryTransaction, InventoryTransactionType
from inventory.services import record_opening_stock
from stores.decorators import attach_store_portal_context

from .decorators import user_has_catalog_permission
from .models import Product, ProductStatus
from .services import (
    apply_admin_pricing, create_product, mutate_product_images,
    record_product_status_change, update_product,
)
from .status import permission_for_transition, store_user_may_transition


def entry_permissions(request, *, merchant):
    if merchant:
        membership = attach_store_portal_context(request)
        return {"can_price": False, "can_open_stock": membership.can_manage_inventory}
    return {
        "can_price": user_has_catalog_permission(request.user, "catalog.manage_product_pricing"),
        "can_open_stock": user_has_inventory_permission(request.user, "inventory.adjust_inventory"),
    }


def may_set_status(request, product, target, *, merchant):
    if product.status == target:
        return True
    if merchant:
        return store_user_may_transition(product.status, target)
    permission = permission_for_transition(product.status, target)
    return bool(permission and user_has_catalog_permission(request.user, permission))


def opening_recorded(product):
    return bool(product and product.pk and InventoryTransaction.objects.filter(
        product=product, transaction_type=InventoryTransactionType.OPENING,
    ).exists())


@transaction.atomic
def save_product_entry(*, request, form, media, stock, pricing, action, merchant):
    """Authorization is checked again here, before any mutation in the transaction."""
    permissions = entry_permissions(request, merchant=merchant)
    editing = bool(form.instance.pk)
    if not merchant and not user_has_catalog_permission(
        request.user, "catalog.change_product" if editing else "catalog.add_product"
    ):
        raise PermissionDenied("You cannot save this product.")
    product = None
    if editing:
        product = Product.objects.select_for_update().get(pk=form.instance.pk)
        if merchant and product.store_id != request.store.pk:
            raise Http404("Product not found.")
        if merchant and product.status == ProductStatus.INACTIVE:
            raise ValidationError("Inactive products cannot be edited from the store portal.")
    targets = {"draft": ProductStatus.DRAFT, "submit": ProductStatus.PENDING,
               "submit_another": ProductStatus.PENDING}
    if action not in (set(targets) | ({"save"} if editing else set())):
        raise ValidationError("Choose a supported save action.")
    target = targets.get(action)
    if editing and target and not may_set_status(request, product, target, merchant=merchant):
        raise ValidationError("That status action is no longer available. Reload to check the product status.")
    if pricing is not None and not permissions["can_price"]:
        raise PermissionDenied("You cannot change management pricing.")
    quantity = stock.cleaned_data.get("opening_stock")
    if quantity is not None and not permissions["can_open_stock"]:
        raise PermissionDenied("You cannot record opening stock.")

    data = {key: value for key, value in form.cleaned_data.items() if key in form._meta.fields}
    store = request.store if merchant else (product.store if editing else data.pop("store"))
    data.pop("store", None)
    tags = data.pop("tags", [])
    if Product.objects.filter(store=store, sku=data["sku"]).exclude(pk=product.pk if product else None).exists():
        raise ValidationError({"sku": "This SKU already exists in this store. Check the product list before submitting again."})

    batch = media.mutations()
    if editing:
        # Check last-image protection against the locked status BEFORE a catalogue
        # edit could legitimately return an approved product to pending.
        mutate_product_images(mutations={product.pk: batch}, validate_only=True)
        # update_product supports authorized management pricing and records history.
        # Supply validated inputs together so an old discount cannot invalidate an
        # otherwise valid simultaneous store-price/discount change.
        if pricing is not None:
            data.update({key: pricing.cleaned_data[key] for key in (
                "profit_margin_type", "profit_margin", "discount_type", "discount_value",
            )})
        product = update_product(product=product, product_data=data,
            updated_by=request.user, tag_ids=[tag.pk for tag in tags],
            request=request, actor_is_store_user=merchant)
    else:
        product = create_product(store=store, product_data=data, created_by=request.user,
            tag_ids=[tag.pk for tag in tags], initial_status=target, request=request)

    if pricing is not None:
        apply_admin_pricing(product=product, changed_by=request.user, request=request,
            **{key: pricing.cleaned_data[key] for key in (
                "profit_margin_type", "profit_margin", "discount_type", "discount_value", "reason",
            )})
    mutate_product_images(mutations={product.pk: batch}, changed_by=request.user, request=request)
    # Image service may have changed APPROVED to PENDING on a different instance.
    product.refresh_from_db()
    if quantity is not None:
        record_opening_stock(product=product, store=store, quantity=quantity,
            actor=request.user, reason=stock.cleaned_data.get("opening_stock_reason", ""), request=request)
    if editing and target and product.status != target:
        record_product_status_change(product=product, new_status=target,
            changed_by=request.user, actor_is_store_user=merchant,
            reason="Submitted for approval" if target == ProductStatus.PENDING else "Saved as draft",
            request=request)
    product.refresh_from_db()
    return product


def issue_entry_token(request):
    from secrets import token_urlsafe
    from time import time_ns
    from django.core import signing
    return signing.dumps({"user": request.user.pk, "session": request.session.session_key,
                          "path": request.path, "nonce": token_urlsafe(16), "issued": time_ns()}, salt="catalog.product-entry")


def lock_entry_receipt(request):
    """Use the existing DB session as a bounded receipt store, without a migration.

    Called inside the view transaction. Locking the session serializes repeated
    submissions, and the receipt commits with the product. Legacy POSTs without
    a token retain their existing behavior and the store/SKU uniqueness backstop.
    """
    import hashlib
    import json
    from django.contrib.sessions.models import Session
    from django.core import signing
    token = request.POST.get("entry_token")
    if not token:
        return None, None, None
    try:
        payload = signing.loads(token, salt="catalog.product-entry", max_age=7200)
    except signing.BadSignature as exc:
        raise ValidationError("This form has expired. Check the product list, then reload before saving.") from exc
    if (payload.get("user"), payload.get("session"), payload.get("path")) != (
        request.user.pk, request.session.session_key, request.path,
    ):
        raise ValidationError("This save token belongs to a different form or session.")
    session = Session.objects.select_for_update().filter(session_key=request.session.session_key).first()
    if session is None:
        raise PermissionDenied("Your session expired. Sign in again before saving.")
    values = {key: request.POST.getlist(key) for key in sorted(request.POST)
              if key not in {"csrfmiddlewaretoken", "entry_token"}}
    file_hashes = []
    for key in sorted(request.FILES):
        for upload in request.FILES.getlist(key):
            digest = hashlib.sha256()
            for chunk in upload.chunks():
                digest.update(chunk)
            upload.seek(0)
            file_hashes.append([key, upload.name, digest.hexdigest()])
    fingerprint = hashlib.sha256(json.dumps([values, file_hashes], sort_keys=True).encode()).hexdigest()
    state = session.get_decoded()
    receipts = state.get("catalog_entry_receipts", {})
    receipt = receipts.get(payload["nonce"])
    if not receipt and payload.get("issued", 0) <= state.get("catalog_entry_receipts_floor", 0):
        raise ValidationError("This form is too old to retry safely. Check the product list and open a fresh form.")
    if receipt and receipt["fingerprint"] != fingerprint:
        raise ValidationError("This form was already saved with different values. Check the product list and open a fresh form.")
    return (session, state, payload["nonce"], payload["issued"]), fingerprint, receipt


def store_entry_receipt(request, locked, fingerprint, result):
    if locked is None:
        return
    session, state, nonce, issued = locked
    receipts = state.get("catalog_entry_receipts", {})
    receipts[nonce] = {"fingerprint": fingerprint, "result": result, "issued": issued}
    # Bound session growth; receipts also expire with the authenticated session.
    ordered = list(receipts.items())
    if len(ordered) > 30:
        state["catalog_entry_receipts_floor"] = max(
            state.get("catalog_entry_receipts_floor", 0),
            *(receipt["issued"] for _, receipt in ordered[:-30]),
        )
    state["catalog_entry_receipts"] = dict(ordered[-30:])
    session.session_data = request.session.encode(state)
    session.save(update_fields=["session_data"])
    # Keep SessionMiddleware from replacing the new receipt with stale cached data.
    request.session.update(state)
    request.session.modified = False
