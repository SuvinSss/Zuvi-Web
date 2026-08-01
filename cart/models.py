from decimal import Decimal

from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator
from django.db import models


class Cart(models.Model):
    """One active shopping cart per Customer."""

    customer = models.OneToOneField(
        "customers.Customer",
        on_delete=models.CASCADE,
        related_name="cart",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-updated_at"]

    def __str__(self):
        code = self.customer.customer_code if self.customer_id else "—"
        return f"Cart for {code}"


class CartItem(models.Model):
    """
    A single product line in a cart.

    Prices are never stored here — checkout recalculates from Product.final_price.
    """

    cart = models.ForeignKey(
        Cart,
        on_delete=models.CASCADE,
        related_name="items",
    )
    product = models.ForeignKey(
        "catalog.Product",
        on_delete=models.PROTECT,
        related_name="cart_items",
    )
    quantity = models.DecimalField(
        max_digits=12,
        decimal_places=3,
        validators=[MinValueValidator(Decimal("0.001"))],
    )
    # Preview warning only — checkout never trusts this value.
    unit_price_snapshot = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        null=True,
        blank=True,
        help_text=(
            "Customer-facing final price when the line was last updated. "
            "Used only to detect price changes in the cart UI."
        ),
    )
    added_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-updated_at", "-added_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["cart", "product"],
                name="unique_cart_item_per_cart_product",
            ),
            models.CheckConstraint(
                condition=models.Q(quantity__gt=Decimal("0")),
                name="cart_item_quantity_positive",
            ),
        ]

    def clean(self):
        super().clean()
        if self.quantity is not None and self.quantity <= 0:
            raise ValidationError(
                {"quantity": "Cart item quantity must be greater than zero."}
            )

    def __str__(self):
        product = self.product.product_code if self.product_id else "—"
        return f"{product} × {self.quantity}"
