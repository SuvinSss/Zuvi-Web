from django import forms

from .models import FulfillmentType, OrderStatus, PaymentMethod, PaymentStatus


class CheckoutPlaceForm(forms.Form):
    """
    Trusted client fields for place-order only.

    Prices, totals, store IDs and customer IDs are intentionally absent.
    """

    checkout_token = forms.CharField(max_length=64)
    fulfillment_type = forms.ChoiceField(choices=FulfillmentType.choices)
    payment_method = forms.ChoiceField(choices=PaymentMethod.choices)
    delivery_address_id = forms.IntegerField(required=False)
    customer_notes = forms.CharField(
        required=False,
        max_length=2000,
        widget=forms.Textarea(attrs={"rows": 3}),
    )

    def clean(self):
        cleaned = super().clean()
        fulfillment = cleaned.get("fulfillment_type")
        payment = cleaned.get("payment_method")
        address_id = cleaned.get("delivery_address_id")

        if fulfillment == FulfillmentType.DELIVERY and not address_id:
            self.add_error(
                "delivery_address_id",
                "Select a delivery address.",
            )
        if fulfillment == FulfillmentType.FACILITY_PICKUP and address_id:
            # Address is ignored for pickup; clear so it is never applied.
            cleaned["delivery_address_id"] = None

        if (
            fulfillment == FulfillmentType.DELIVERY
            and payment
            and payment != PaymentMethod.COD
        ):
            self.add_error(
                "payment_method",
                "Cash on Delivery is required for delivery orders.",
            )
        return cleaned


class CustomerOrderCancelForm(forms.Form):
    """Customer cancellation requires an explicit reason (POST only)."""

    reason = forms.CharField(
        max_length=2000,
        widget=forms.Textarea(
            attrs={
                "rows": 3,
                "class": "form-control",
                "placeholder": "Why are you cancelling this order?",
            }
        ),
        label="Cancellation reason",
    )

    def clean_reason(self):
        reason = (self.cleaned_data.get("reason") or "").strip()
        if not reason:
            raise forms.ValidationError("A cancellation reason is required.")
        return reason


class StoreOrderRejectForm(forms.Form):
    """Store rejection requires an explicit reason (POST only)."""

    reason = forms.CharField(
        max_length=2000,
        widget=forms.Textarea(
            attrs={
                "rows": 3,
                "class": "form-control",
                "placeholder": "Why is this store order being rejected?",
            }
        ),
        label="Rejection reason",
    )

    def clean_reason(self):
        reason = (self.cleaned_data.get("reason") or "").strip()
        if not reason:
            raise forms.ValidationError("A rejection reason is required.")
        return reason


class StoreOrderStatusNoteForm(forms.Form):
    """Optional note for accept / processing / ready transitions."""

    reason = forms.CharField(
        required=False,
        max_length=2000,
        widget=forms.Textarea(
            attrs={
                "rows": 2,
                "class": "form-control",
                "placeholder": "Optional note",
            }
        ),
        label="Note",
    )

    def clean_reason(self):
        return (self.cleaned_data.get("reason") or "").strip()


class ManagementOrderStatusForm(forms.Form):
    """Management portal overall Order status change (POST only)."""

    status = forms.ChoiceField(choices=OrderStatus.choices, label="New status")
    reason = forms.CharField(
        required=False,
        max_length=2000,
        widget=forms.Textarea(
            attrs={
                "rows": 2,
                "class": "form-control",
                "placeholder": "Optional note",
            }
        ),
        label="Note",
    )

    def __init__(self, *args, allowed_statuses=None, **kwargs):
        super().__init__(*args, **kwargs)
        allowed = list(allowed_statuses or [])
        self.fields["status"].choices = [
            (value, label)
            for value, label in OrderStatus.choices
            if value in allowed
        ]

    def clean_reason(self):
        return (self.cleaned_data.get("reason") or "").strip()


class ManagementOrderCancelForm(forms.Form):
    """Administrative cancellation requires an explicit reason (POST only)."""

    reason = forms.CharField(
        max_length=2000,
        widget=forms.Textarea(
            attrs={
                "rows": 3,
                "class": "form-control",
                "placeholder": "Why is this order being cancelled?",
            }
        ),
        label="Cancellation reason",
    )

    def clean_reason(self):
        reason = (self.cleaned_data.get("reason") or "").strip()
        if not reason:
            raise forms.ValidationError("A cancellation reason is required.")
        return reason


class ManagementPaymentStatusForm(forms.Form):
    """Management portal payment-status update (POST only)."""

    payment_status = forms.ChoiceField(
        choices=PaymentStatus.choices,
        label="Payment status",
    )
    reason = forms.CharField(
        required=False,
        max_length=2000,
        widget=forms.Textarea(
            attrs={
                "rows": 2,
                "class": "form-control",
                "placeholder": "Optional note",
            }
        ),
        label="Note",
    )

    def __init__(self, *args, allowed_statuses=None, **kwargs):
        super().__init__(*args, **kwargs)
        allowed = list(allowed_statuses or [])
        self.fields["payment_status"].choices = [
            (value, label)
            for value, label in PaymentStatus.choices
            if value in allowed
        ]

    def clean_reason(self):
        return (self.cleaned_data.get("reason") or "").strip()
