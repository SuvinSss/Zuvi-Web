from django import forms
from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from decimal import Decimal

from .models import AddressLabel, VerificationStatus

User = get_user_model()


class CustomerSelfRegistrationForm(forms.Form):
    first_name = forms.CharField(max_length=150, required=True)
    last_name = forms.CharField(max_length=150, required=True)
    username = forms.CharField(max_length=150, required=True)
    email = forms.EmailField(required=True)
    phone_number = forms.CharField(max_length=20, required=True)
    password = forms.CharField(widget=forms.PasswordInput, required=True)
    confirm_password = forms.CharField(widget=forms.PasswordInput, required=True)
    accept_terms = forms.BooleanField(
        required=True,
        error_messages={"required": "You must accept the terms to register."},
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for name, field in self.fields.items():
            if name == "accept_terms":
                field.widget.attrs.update({"class": "form-check-input"})
            else:
                field.widget.attrs.update({"class": "form-control"})

    def clean_username(self):
        username = self.cleaned_data["username"].strip()
        if User.objects.filter(username__iexact=username).exists():
            raise ValidationError("This username is already in use.")
        return username

    def clean_email(self):
        email = self.cleaned_data["email"].strip().lower()
        if User.objects.filter(email__iexact=email).exists():
            raise ValidationError("This email is already in use.")
        return email

    def clean_phone_number(self):
        phone_number = self.cleaned_data["phone_number"].strip()
        if not phone_number:
            raise ValidationError("Phone number is required.")
        if User.objects.filter(phone_number=phone_number).exists():
            raise ValidationError("This phone number is already in use.")
        return phone_number

    def clean(self):
        cleaned_data = super().clean()
        password = cleaned_data.get("password")
        confirm_password = cleaned_data.get("confirm_password")
        if password and confirm_password and password != confirm_password:
            self.add_error("confirm_password", "Passwords do not match.")
        if password:
            try:
                validate_password(password)
            except ValidationError as exc:
                self.add_error("password", exc)
        return cleaned_data


class ManagementCustomerCreateForm(forms.Form):
    first_name = forms.CharField(max_length=150, required=True)
    last_name = forms.CharField(max_length=150, required=True)
    username = forms.CharField(max_length=150, required=True)
    email = forms.EmailField(required=True)
    phone_number = forms.CharField(max_length=20, required=False, label="Phone number")
    password = forms.CharField(
        widget=forms.PasswordInput,
        required=True,
        label="Temporary password",
    )
    confirm_password = forms.CharField(
        widget=forms.PasswordInput,
        required=True,
        label="Confirm password",
    )
    notes = forms.CharField(
        widget=forms.Textarea,
        required=False,
        label="Management notes",
    )

    # Optional first delivery address
    address_label = forms.ChoiceField(
        choices=[("", "---------")] + list(AddressLabel.choices),
        required=False,
        label="Address label",
    )
    address_recipient_name = forms.CharField(
        max_length=150,
        required=False,
        label="Recipient name",
    )
    address_phone_number = forms.CharField(
        max_length=20,
        required=False,
        label="Address contact number",
    )
    address_line1 = forms.CharField(
        max_length=255,
        required=False,
        label="Address line 1",
    )
    address_line2 = forms.CharField(
        max_length=255,
        required=False,
        label="Address line 2",
    )
    address_landmark = forms.CharField(max_length=255, required=False, label="Landmark")
    address_city = forms.CharField(max_length=100, required=False, label="City")
    address_district = forms.CharField(max_length=100, required=False, label="District")
    address_state = forms.CharField(max_length=100, required=False, label="State")
    address_postal_code = forms.CharField(
        max_length=20,
        required=False,
        label="Postal code",
    )
    address_latitude = forms.DecimalField(
        max_digits=9,
        decimal_places=6,
        required=False,
        label="Latitude",
        widget=forms.HiddenInput(),
        help_text="Set on the map below.",
    )
    address_longitude = forms.DecimalField(
        max_digits=9,
        decimal_places=6,
        required=False,
        label="Longitude",
        widget=forms.HiddenInput(),
        help_text="Set on the map below.",
    )
    address_delivery_instructions = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={"rows": 2}),
        label="Delivery instructions",
    )

    ADDRESS_FIELD_NAMES = (
        "address_label",
        "address_recipient_name",
        "address_phone_number",
        "address_line1",
        "address_line2",
        "address_landmark",
        "address_city",
        "address_district",
        "address_state",
        "address_postal_code",
        "address_latitude",
        "address_longitude",
        "address_delivery_instructions",
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for name, field in self.fields.items():
            if isinstance(field.widget, forms.HiddenInput):
                continue
            if isinstance(field.widget, forms.CheckboxInput):
                field.widget.attrs.update({"class": "form-check-input"})
            elif isinstance(field.widget, forms.Select):
                field.widget.attrs.update({"class": "form-select"})
            elif isinstance(field.widget, forms.Textarea):
                field.widget.attrs.update({"class": "form-control", "rows": 3})
            else:
                field.widget.attrs.update({"class": "form-control"})

    def clean_username(self):
        username = self.cleaned_data["username"].strip()
        if User.objects.filter(username__iexact=username).exists():
            raise ValidationError("This username is already in use.")
        return username

    def clean_email(self):
        email = self.cleaned_data["email"].strip().lower()
        if User.objects.filter(email__iexact=email).exists():
            raise ValidationError("This email is already in use.")
        return email

    def clean_phone_number(self):
        phone_number = self.cleaned_data["phone_number"].strip()
        if phone_number and User.objects.filter(phone_number=phone_number).exists():
            raise ValidationError("This phone number is already in use.")
        return phone_number

    def _address_provided(self, cleaned_data):
        markers = (
            "address_recipient_name",
            "address_phone_number",
            "address_line1",
            "address_line2",
            "address_landmark",
            "address_city",
            "address_district",
            "address_state",
            "address_postal_code",
            "address_latitude",
            "address_longitude",
            "address_delivery_instructions",
        )
        for name in markers:
            value = cleaned_data.get(name)
            if value not in (None, ""):
                return True
        return False

    def clean(self):
        cleaned_data = super().clean()
        password = cleaned_data.get("password")
        confirm_password = cleaned_data.get("confirm_password")
        if password and confirm_password and password != confirm_password:
            self.add_error("confirm_password", "Passwords do not match.")
        if password:
            try:
                validate_password(password)
            except ValidationError as exc:
                self.add_error("password", exc)

        if self._address_provided(cleaned_data):
            required_address = {
                "address_label": "Address label is required when adding an address.",
                "address_recipient_name": "Recipient name is required when adding an address.",
                "address_phone_number": "Address contact number is required when adding an address.",
                "address_line1": "Address line 1 is required when adding an address.",
                "address_city": "City is required when adding an address.",
                "address_state": "State is required when adding an address.",
                "address_postal_code": "Postal code is required when adding an address.",
                "address_latitude": "Set a location on the map when adding an address.",
                "address_longitude": "Set a location on the map when adding an address.",
            }
            for field_name, message in required_address.items():
                value = cleaned_data.get(field_name)
                if value in (None, ""):
                    self.add_error(field_name, message)

            latitude = cleaned_data.get("address_latitude")
            longitude = cleaned_data.get("address_longitude")
            if latitude is not None and not (Decimal("-90") <= latitude <= Decimal("90")):
                self.add_error(
                    "address_latitude",
                    "Latitude must be between -90 and 90.",
                )
            if longitude is not None and not (
                Decimal("-180") <= longitude <= Decimal("180")
            ):
                self.add_error(
                    "address_longitude",
                    "Longitude must be between -180 and 180.",
                )
        return cleaned_data

    def cleaned_initial_address_data(self):
        if not self._address_provided(self.cleaned_data):
            return None
        return {
            "label": self.cleaned_data["address_label"] or AddressLabel.HOME,
            "recipient_name": self.cleaned_data["address_recipient_name"].strip(),
            "phone_number": self.cleaned_data["address_phone_number"].strip(),
            "line1": self.cleaned_data["address_line1"].strip(),
            "line2": (self.cleaned_data.get("address_line2") or "").strip(),
            "landmark": (self.cleaned_data.get("address_landmark") or "").strip(),
            "city": self.cleaned_data["address_city"].strip(),
            "district": (self.cleaned_data.get("address_district") or "").strip(),
            "state": self.cleaned_data["address_state"].strip(),
            "postal_code": self.cleaned_data["address_postal_code"].strip(),
            "latitude": self.cleaned_data["address_latitude"],
            "longitude": self.cleaned_data["address_longitude"],
            "delivery_instructions": (
                self.cleaned_data.get("address_delivery_instructions") or ""
            ).strip(),
            "is_default": True,
        }


class ManagementCustomerEditForm(forms.Form):
    first_name = forms.CharField(max_length=150, required=True)
    last_name = forms.CharField(max_length=150, required=True)
    email = forms.EmailField(required=True)
    phone_number = forms.CharField(max_length=20, required=False, label="Phone number")
    date_of_birth = forms.DateField(
        required=False,
        widget=forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"),
        input_formats=["%Y-%m-%d"],
    )
    notes = forms.CharField(
        widget=forms.Textarea,
        required=False,
        label="Management notes",
    )

    def __init__(self, *args, customer=None, **kwargs):
        self.customer = customer
        super().__init__(*args, **kwargs)
        for name, field in self.fields.items():
            css = "form-control"
            if isinstance(field.widget, forms.Textarea):
                field.widget.attrs.update({"class": css, "rows": 3})
            else:
                field.widget.attrs.update({"class": css})

    def clean_email(self):
        email = self.cleaned_data["email"].strip().lower()
        qs = User.objects.filter(email__iexact=email)
        if self.customer is not None:
            qs = qs.exclude(pk=self.customer.user_id)
        if qs.exists():
            raise ValidationError("This email is already in use.")
        return email

    def clean_phone_number(self):
        phone_number = self.cleaned_data["phone_number"].strip()
        if phone_number:
            qs = User.objects.filter(phone_number=phone_number)
            if self.customer is not None:
                qs = qs.exclude(pk=self.customer.user_id)
            if qs.exists():
                raise ValidationError("This phone number is already in use.")
        return phone_number


class CustomerVerificationForm(forms.Form):
    verification_status = forms.ChoiceField(
        choices=VerificationStatus.choices,
        widget=forms.Select(attrs={"class": "form-select"}),
    )


class CustomerDeactivationForm(forms.Form):
    reason = forms.CharField(
        required=True,
        label="Reason for deactivation",
        widget=forms.Textarea(attrs={"rows": 3, "class": "form-control"}),
        error_messages={"required": "A reason is required to deactivate a customer."},
    )

    def clean_reason(self):
        reason = self.cleaned_data["reason"].strip()
        if not reason:
            raise ValidationError("A reason is required to deactivate a customer.")
        return reason


class CustomerOTPPhoneForm(forms.Form):
    """Step 1 of the mobile-first login/signup flow: capture the number to OTP."""

    phone_number = forms.CharField(
        max_length=20,
        min_length=10,
        label="Mobile number",
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["phone_number"].widget.attrs.update(
            {
                "class": "form-control form-control-lg",
                "inputmode": "numeric",
                "placeholder": "10-digit mobile number",
                "autocomplete": "tel",
                "autofocus": True,
            }
        )

    def clean_phone_number(self):
        raw = self.cleaned_data["phone_number"]
        digits = "".join(ch for ch in raw if ch.isdigit())
        if len(digits) < 10:
            raise ValidationError("Enter a valid 10-digit mobile number.")
        return digits[-10:]


class CustomerOTPVerifyForm(forms.Form):
    """Step 2: the 4-digit code. Verification logic itself is backend-side."""

    otp_code = forms.CharField(max_length=4, min_length=4, label="OTP")

    def clean_otp_code(self):
        code = self.cleaned_data["otp_code"].strip()
        if not code.isdigit() or len(code) != 4:
            raise ValidationError("Enter the 4-digit code.")
        return code


class CustomerOTPProfileForm(forms.Form):
    """Step 3, new numbers only: the minimum details needed to create an account."""

    first_name = forms.CharField(max_length=150, required=True)
    last_name = forms.CharField(max_length=150, required=False)
    email = forms.EmailField(required=True)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            field.widget.attrs.update({"class": "form-control form-control-lg"})

    def clean_email(self):
        email = self.cleaned_data["email"].strip().lower()
        if User.objects.filter(email__iexact=email).exists():
            raise ValidationError("This email is already in use.")
        return email


class CustomerPortalProfileForm(forms.Form):
    """
    Customer-portal self-service fields only.

    Username, role, privileges, verification, and account status are excluded.
    """

    first_name = forms.CharField(max_length=150, required=True)
    last_name = forms.CharField(max_length=150, required=True)
    email = forms.EmailField(required=True)
    phone_number = forms.CharField(max_length=20, required=True)

    def __init__(self, *args, user=None, **kwargs):
        self.user = user
        super().__init__(*args, **kwargs)
        if user is not None and not self.is_bound:
            self.fields["first_name"].initial = user.first_name
            self.fields["last_name"].initial = user.last_name
            self.fields["email"].initial = user.email
            self.fields["phone_number"].initial = user.phone_number or ""
        for field in self.fields.values():
            field.widget.attrs.update({"class": "form-control"})

    def clean_email(self):
        email = self.cleaned_data["email"].strip().lower()
        qs = User.objects.filter(email__iexact=email)
        if self.user is not None:
            qs = qs.exclude(pk=self.user.pk)
        if qs.exists():
            raise ValidationError("This email is already in use.")
        return email

    def clean_phone_number(self):
        phone_number = self.cleaned_data["phone_number"].strip()
        if not phone_number:
            raise ValidationError("Phone number is required.")
        qs = User.objects.filter(phone_number=phone_number)
        if self.user is not None:
            qs = qs.exclude(pk=self.user.pk)
        if qs.exists():
            raise ValidationError("This phone number is already in use.")
        return phone_number


class CustomerPortalAddressForm(forms.Form):
    label = forms.ChoiceField(choices=AddressLabel.choices, required=True)
    recipient_name = forms.CharField(max_length=150, required=True, label="Recipient name")
    phone_number = forms.CharField(
        max_length=20,
        required=True,
        label="Contact number",
    )
    line1 = forms.CharField(max_length=255, required=True, label="Address line 1")
    line2 = forms.CharField(
        max_length=255,
        required=False,
        label="Address line 2",
    )
    landmark = forms.CharField(max_length=255, required=False)
    city = forms.CharField(max_length=100, required=True)
    district = forms.CharField(max_length=100, required=False)
    state = forms.CharField(max_length=100, required=True)
    postal_code = forms.CharField(max_length=20, required=True, label="Postal code")
    latitude = forms.DecimalField(
        max_digits=9,
        decimal_places=6,
        required=True,
        widget=forms.HiddenInput(),
        help_text="Set on the map below.",
        error_messages={"required": "Set a location on the map."},
    )
    longitude = forms.DecimalField(
        max_digits=9,
        decimal_places=6,
        required=True,
        widget=forms.HiddenInput(),
        help_text="Set on the map below.",
        error_messages={"required": "Set a location on the map."},
    )
    delivery_instructions = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={"rows": 3}),
        label="Delivery instructions",
    )
    is_default = forms.BooleanField(required=False, label="Is default")

    def __init__(self, *args, customer_address=None, **kwargs):
        self.customer_address = customer_address
        super().__init__(*args, **kwargs)
        if customer_address is not None and not self.is_bound:
            address = customer_address.address
            self.fields["label"].initial = customer_address.label
            self.fields["recipient_name"].initial = customer_address.recipient_name
            self.fields["phone_number"].initial = customer_address.phone_number
            self.fields["line1"].initial = address.line1
            self.fields["line2"].initial = address.line2
            self.fields["landmark"].initial = address.landmark
            self.fields["city"].initial = address.city
            self.fields["district"].initial = address.district
            self.fields["state"].initial = address.state
            self.fields["postal_code"].initial = address.postal_code
            self.fields["latitude"].initial = address.latitude
            self.fields["longitude"].initial = address.longitude
            self.fields["delivery_instructions"].initial = (
                customer_address.delivery_instructions
            )
            self.fields["is_default"].initial = customer_address.is_default

        for name, field in self.fields.items():
            if isinstance(field.widget, forms.HiddenInput):
                continue
            if isinstance(field.widget, forms.CheckboxInput):
                field.widget.attrs.update({"class": "form-check-input"})
            elif isinstance(field.widget, forms.Select):
                field.widget.attrs.update({"class": "form-select"})
            elif isinstance(field.widget, forms.Textarea):
                field.widget.attrs.update({"class": "form-control", "rows": 3})
            else:
                field.widget.attrs.update({"class": "form-control"})

    def clean_phone_number(self):
        phone_number = self.cleaned_data["phone_number"].strip()
        if not phone_number:
            raise ValidationError("Contact number is required.")
        return phone_number

    def clean_latitude(self):
        latitude = self.cleaned_data["latitude"]
        if not (Decimal("-90") <= latitude <= Decimal("90")):
            raise ValidationError("Latitude must be between -90 and 90.")
        return latitude

    def clean_longitude(self):
        longitude = self.cleaned_data["longitude"]
        if not (Decimal("-180") <= longitude <= Decimal("180")):
            raise ValidationError("Longitude must be between -180 and 180.")
        return longitude

    def cleaned_address_data(self):
        return {
            "label": self.cleaned_data["label"],
            "recipient_name": self.cleaned_data["recipient_name"].strip(),
            "phone_number": self.cleaned_data["phone_number"],
            "line1": self.cleaned_data["line1"].strip(),
            "line2": (self.cleaned_data.get("line2") or "").strip(),
            "landmark": (self.cleaned_data.get("landmark") or "").strip(),
            "city": self.cleaned_data["city"].strip(),
            "district": (self.cleaned_data.get("district") or "").strip(),
            "state": self.cleaned_data["state"].strip(),
            "postal_code": self.cleaned_data["postal_code"].strip(),
            "latitude": self.cleaned_data["latitude"],
            "longitude": self.cleaned_data["longitude"],
            "delivery_instructions": (
                self.cleaned_data.get("delivery_instructions") or ""
            ).strip(),
            "is_default": bool(self.cleaned_data.get("is_default")),
        }
