from decimal import Decimal

from django.core.exceptions import ValidationError
from django.utils import timezone

from stores.models import StoreStatus

from .models import ProductStatus
from .pricing import product_has_complete_pricing

# Explicit allow-list of product status transitions.
ALLOWED_STATUS_TRANSITIONS = {
    ProductStatus.DRAFT: frozenset({ProductStatus.PENDING}),
    ProductStatus.PENDING: frozenset(
        {ProductStatus.APPROVED, ProductStatus.REJECTED}
    ),
    ProductStatus.REJECTED: frozenset(
        {ProductStatus.PENDING, ProductStatus.DRAFT}
    ),
    # APPROVED → PENDING: store/management resubmission after catalogue edits.
    ProductStatus.APPROVED: frozenset(
        {ProductStatus.INACTIVE, ProductStatus.PENDING}
    ),
    # INACTIVE → PENDING (re-queue) or APPROVED (reactivate with full checks).
    ProductStatus.INACTIVE: frozenset(
        {ProductStatus.APPROVED, ProductStatus.PENDING}
    ),
}

STATUSES_REQUIRING_REASON = frozenset({ProductStatus.REJECTED})

# Store users may only perform these transitions on their own products.
STORE_USER_ALLOWED_TRANSITIONS = frozenset(
    {
        (ProductStatus.DRAFT, ProductStatus.PENDING),
        (ProductStatus.REJECTED, ProductStatus.PENDING),
        (ProductStatus.REJECTED, ProductStatus.DRAFT),
        (ProductStatus.APPROVED, ProductStatus.PENDING),
    }
)


def allowed_next_statuses(current_status):
    return ALLOWED_STATUS_TRANSITIONS.get(current_status, frozenset())


def is_transition_allowed(current_status, new_status):
    if current_status == new_status:
        return False
    return new_status in allowed_next_statuses(current_status)


def permission_for_transition(current_status, new_status):
    """
    Map a management-portal transition to the Django permission that authorizes it.

    - PENDING→APPROVED / PENDING→REJECTED / INACTIVE→APPROVED → catalog.approve_product
    - APPROVED→INACTIVE / INACTIVE→PENDING / APPROVED→PENDING → catalog.change_product
    - DRAFT→PENDING / REJECTED→PENDING → catalog.change_product
    """
    if not is_transition_allowed(current_status, new_status):
        return None
    if new_status == ProductStatus.INACTIVE:
        return "catalog.change_product"
    if (
        current_status == ProductStatus.APPROVED
        and new_status == ProductStatus.PENDING
    ):
        return "catalog.change_product"
    if (
        current_status == ProductStatus.INACTIVE
        and new_status == ProductStatus.PENDING
    ):
        return "catalog.change_product"
    if new_status in {
        ProductStatus.APPROVED,
        ProductStatus.REJECTED,
    }:
        return "catalog.approve_product"
    return "catalog.change_product"


def reason_required_for(new_status):
    return new_status in STATUSES_REQUIRING_REASON


def store_user_may_transition(current_status, new_status):
    return (current_status, new_status) in STORE_USER_ALLOWED_TRANSITIONS


def product_is_publicly_available(product):
    """
    Customer-facing availability.

    Only APPROVED and active products may be shown publicly. PENDING /
    REJECTED / DRAFT / INACTIVE products are never publicly available.
    """
    return bool(
        product
        and getattr(product, "is_active", False)
        and product.status == ProductStatus.APPROVED
    )


def product_has_sufficient_required_information(product):
    """Core catalogue fields required before a product can be approved."""
    if not (product.name or "").strip():
        return False
    if not (product.sku or "").strip():
        return False
    if product.category_id is None:
        return False
    if not product.unit:
        return False
    if product.unit_value is None or product.unit_value < 0:
        return False
    if product.store_price is None:
        return False
    return True


def product_has_valid_image(product):
    """True when the product has at least one stored image file."""
    if product is None or not product.pk:
        return False
    return product.images.exclude(image="").exclude(image__isnull=True).exists()


def validate_product_for_approval(product):
    """
    Enforce business rules required to move a product to APPROVED.

    Raises ValidationError with one or more messages when requirements fail.
    """
    if product is None:
        raise ValidationError("Product is required for approval.")

    errors = []
    store = getattr(product, "store", None)
    if store is None:
        errors.append("Product must belong to a store.")
    else:
        if not store.is_active:
            errors.append("Product must have an active store.")
        if store.status != StoreStatus.ACTIVE:
            errors.append("Store status must be ACTIVE.")

    category = getattr(product, "category", None)
    if category is None:
        errors.append("Product must have a category.")
    elif not category.is_active:
        errors.append("Product category must be active.")

    if product.store_price is None or product.store_price < 0:
        errors.append("Store price must be valid.")

    if not product_has_complete_pricing(product):
        errors.append("Product pricing must be set before approval.")
    elif product.final_price is None or product.final_price <= Decimal("0"):
        errors.append("Final price must be greater than zero.")

    if not product_has_valid_image(product):
        errors.append("Product must have at least one valid image.")

    if not product_has_sufficient_required_information(product):
        errors.append("Product is missing required catalogue information.")

    if errors:
        raise ValidationError(errors)


def validate_status_transition(
    *,
    current_status,
    new_status,
    reason="",
    product=None,
    actor_is_store_user=False,
):
    """Raise ValidationError when the transition or reason is invalid."""
    if current_status == new_status:
        raise ValidationError("Product already has that status.")
    if not is_transition_allowed(current_status, new_status):
        raise ValidationError(
            f"Cannot change product status from {current_status} to {new_status}."
        )
    if actor_is_store_user and not store_user_may_transition(
        current_status, new_status
    ):
        raise ValidationError(
            "Store users cannot perform that product status change."
        )
    if reason_required_for(new_status) and not (reason or "").strip():
        raise ValidationError("A reason is required when rejecting a product.")
    if new_status == ProductStatus.APPROVED and product is not None:
        validate_product_for_approval(product)


def clear_approval_metadata(product):
    """Clear approved_by / approved_at when a product is no longer approved."""
    product.approved_by = None
    product.approved_at = None


def apply_approval_metadata(product, *, approved_by):
    """Stamp approval actor and timestamp on the product instance."""
    product.approved_by = approved_by
    product.approved_at = timezone.now()
