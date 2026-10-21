from decimal import Decimal

from django import forms


def _bootstrap(form):
    for field in form.fields.values():
        css = field.widget.attrs.get("class", "")
        field.widget.attrs["class"] = f"{css} form-control".strip()


class CartItemQuantityForm(forms.Form):
    quantity = forms.DecimalField(
        min_value=Decimal("0.001"),
        max_digits=12,
        decimal_places=3,
        label="Quantity",
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        _bootstrap(self)
