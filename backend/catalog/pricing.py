from decimal import ROUND_HALF_UP, Decimal

from django.db import models
from django.core.exceptions import ValidationError

TWOPLACES = Decimal("0.01")
HUNDRED = Decimal("100")


class MarginType(models.TextChoices):
    FIXED = "FIXED", "Fixed"
    PERCENTAGE = "PERCENTAGE", "Percentage"


class DiscountType(models.TextChoices):
    FIXED = "FIXED", "Fixed"
    PERCENTAGE = "PERCENTAGE", "Percentage"


# Backwards-compatible aliases used by forms/imports.
MARGIN_TYPE_CHOICES = MarginType.choices
DISCOUNT_TYPE_CHOICES = DiscountType.choices


def _as_decimal(value):
    if value is None:
        return None
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def quantize_money(value):
    return _as_decimal(value).quantize(TWOPLACES, rounding=ROUND_HALF_UP)


def calculate_selling_price(*, store_price, profit_margin_type, profit_margin):
    """
    Calculate selling_price from store_price and admin margin settings.

    FIXED:      store_price + profit_margin
    PERCENTAGE: store_price * (1 + profit_margin / 100)
    """
    store_price = _as_decimal(store_price)
    profit_margin = _as_decimal(profit_margin)

    if store_price is None:
        raise ValidationError({"store_price": "Store price is required."})
    if store_price < 0:
        raise ValidationError({"store_price": "Store price cannot be negative."})
    if not profit_margin_type:
        raise ValidationError(
            {"profit_margin_type": "Profit margin type is required."}
        )
    if profit_margin is None:
        raise ValidationError({"profit_margin": "Profit margin is required."})
    if profit_margin < 0:
        raise ValidationError({"profit_margin": "Profit margin cannot be negative."})

    if profit_margin_type == MarginType.PERCENTAGE:
        if profit_margin > HUNDRED:
            raise ValidationError(
                {"profit_margin": "Percentage margin cannot exceed 100."}
            )
        selling = store_price * (Decimal("1") + (profit_margin / HUNDRED))
    elif profit_margin_type == MarginType.FIXED:
        selling = store_price + profit_margin
    else:
        raise ValidationError(
            {"profit_margin_type": "Invalid profit margin type."}
        )

    selling = quantize_money(selling)
    if selling <= 0:
        raise ValidationError(
            {"selling_price": "Selling price must be greater than zero."}
        )
    return selling


def calculate_final_price(*, selling_price, discount_type="", discount_value=None):
    """
    Calculate final_price from selling_price and optional discount.

    FIXED:      selling_price - discount_value
    PERCENTAGE: selling_price * (1 - discount_value / 100)
    No discount type: final_price = selling_price
    """
    selling_price = _as_decimal(selling_price)
    if selling_price is None:
        raise ValidationError({"selling_price": "Selling price is required."})
    if selling_price < 0:
        raise ValidationError(
            {"selling_price": "Selling price cannot be negative."}
        )

    if not discount_type:
        return quantize_money(selling_price)

    discount_value = _as_decimal(discount_value)
    if discount_value is None:
        discount_value = Decimal("0.00")
    if discount_value < 0:
        raise ValidationError(
            {"discount_value": "Discount value cannot be negative."}
        )

    if discount_type == DiscountType.PERCENTAGE:
        if discount_value > HUNDRED:
            raise ValidationError(
                {"discount_value": "Percentage discount must be between 0 and 100."}
            )
        final = selling_price * (Decimal("1") - (discount_value / HUNDRED))
    elif discount_type == DiscountType.FIXED:
        if discount_value > selling_price:
            raise ValidationError(
                {
                    "discount_value": (
                        "Fixed discount cannot exceed the selling price."
                    )
                }
            )
        final = selling_price - discount_value
    else:
        raise ValidationError({"discount_type": "Invalid discount type."})

    final = quantize_money(final)
    if final <= 0:
        raise ValidationError(
            {"final_price": "Final price must be greater than zero."}
        )
    return final


def calculate_prices(
    *,
    store_price,
    profit_margin_type,
    profit_margin,
    discount_type="",
    discount_value=None,
):
    """
    Dedicated price-calculation service.

    Returns (selling_price, final_price). Never accept those values from forms —
    always derive them here from store_price + admin margin/discount inputs.
    """
    selling = calculate_selling_price(
        store_price=store_price,
        profit_margin_type=profit_margin_type,
        profit_margin=profit_margin,
    )
    final = calculate_final_price(
        selling_price=selling,
        discount_type=discount_type or "",
        discount_value=discount_value,
    )
    return selling, final


def apply_calculated_prices(product):
    """
    Write selling_price and final_price onto a Product from trusted inputs only.

    Ignores any pre-existing selling_price / final_price on the instance unless
    ``_freeze_calculated_prices`` is set (used when an APPROVED product is
    returned to PENDING so prior admin pricing is preserved until review).
    """
    if getattr(product, "_freeze_calculated_prices", False):
        return product
    if product.profit_margin_type and product.profit_margin is not None:
        selling, final = calculate_prices(
            store_price=product.store_price,
            profit_margin_type=product.profit_margin_type,
            profit_margin=product.profit_margin,
            discount_type=product.discount_type or "",
            discount_value=product.discount_value,
        )
        product.selling_price = selling
        product.final_price = final
    else:
        product.selling_price = None
        product.final_price = None
    return product


def product_has_complete_pricing(product):
    """True when admin margin is set and final_price has been computed."""
    return bool(
        product.profit_margin_type
        and product.profit_margin is not None
        and product.selling_price is not None
        and product.final_price is not None
    )


# --------------------------------------------------------------------------
# Pricing explanations for the admin calculator.
#
# Zuuvi model (from the existing schema): the store supplies a product at
# ``store_price`` (Zuuvi's unit cost); management adds a margin to get the
# ``selling_price``; an optional discount gives the ``final_price`` customers
# pay. Tax, payment fees and commission are NOT modelled in the catalogue, so
# every profit figure here is an *estimated gross profit*, never net profit.
# --------------------------------------------------------------------------
def _pct(numerator, denominator):
    """Percentage rounded to 2 places, or None when the denominator is not positive."""
    if denominator is None or denominator <= 0:
        return None
    return quantize_money(numerator / denominator * HUNDRED)


def price_breakdown(*, cost, selling_price, discount_type="", discount_value=None):
    """Explain a price: discount, final price, estimated gross profit, margin and markup.

    Margin = profit / final price. Markup = profit / cost. They are different
    numbers and are never mixed up. Zero cost or zero price yields ``None``
    percentages instead of a division error.
    """
    cost = quantize_money(cost)
    selling = quantize_money(selling_price)
    final = calculate_final_price(selling_price=selling, discount_type=discount_type or "", discount_value=discount_value)
    profit = quantize_money(final - cost)
    warnings = []
    if final < cost:
        warnings.append("The final price is below the store price, so every sale would lose money.")
    elif profit == 0:
        warnings.append("No profit at this price.")
    return {
        "cost": str(cost),
        "selling_price": str(selling),
        "discount_amount": str(quantize_money(selling - final)),
        "final_price": str(final),
        "profit_per_unit": str(profit),
        "margin_percent": None if _pct(profit, final) is None else str(_pct(profit, final)),
        "markup_percent": None if _pct(profit, cost) is None else str(_pct(profit, cost)),
        "label": "Estimated gross profit (before tax, fees and commission)",
        "warnings": warnings,
        "below_cost": final < cost,
    }


def suggest_selling_price(*, cost, target_margin_percent):
    """Selling price that earns ``target_margin_percent`` of the price: cost / (1 - margin)."""
    cost = _as_decimal(cost)
    margin = _as_decimal(target_margin_percent)
    if cost is None or cost <= 0:
        raise ValidationError({"cost": "Enter a store price above zero to suggest a selling price."})
    if margin is None or margin < 0 or margin >= HUNDRED:
        raise ValidationError({"target_margin": "Target margin must be at least 0 and below 100%."})
    return quantize_money(cost / (Decimal("1") - margin / HUNDRED))
