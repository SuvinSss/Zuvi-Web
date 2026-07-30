from django import forms
from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password
from django.contrib.auth.validators import UnicodeUsernameValidator
from django.core.exceptions import ValidationError

from locations.models import Address

from .models import Store, StoreCategory, StoreStatus, StoreUser

User = get_user_model()
USERNAME_VALIDATOR = UnicodeUsernameValidator()


def _apply_bootstrap(form):
    for name, field in form.fields.items():
        widget = field.widget
        if isinstance(widget, forms.CheckboxInput):
            widget.attrs.setdefault("class", "form-check-input")
        elif isinstance(widget, forms.Select):
            widget.attrs.setdefault("class", "form-select")
        elif isinstance(widget, forms.FileInput):
            widget.attrs.setdefault("class", "form-control")
        elif isinstance(widget, forms.Textarea):
            widget.attrs.setdefault("class", "form-control")
            widget.attrs.setdefault("rows", 3)
        else:
            widget.attrs.setdefault("class", "form-control")


class AddressForm(forms.ModelForm):
    class Meta:
        model = Address
        fields = (
            "line1",
            "line2",
            "city",
            "state",
            "postal_code",
            "country",
            "latitude",
            "longitude",
        )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        _apply_bootstrap(self)


class StoreForm(forms.ModelForm):
    class Meta:
        model = Store
        fields = (
            "name",
            "description",
            "contact_phone",
            "alternative_phone",
            "email",
            "image",
            "store_type",
            "category",
            "commission_percentage",
            "is_active",
        )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["category"].queryset = StoreCategory.objects.filter(
            is_active=True
        ).order_by("name")
        if self.instance and self.instance.pk and self.instance.category_id:
            self.fields["category"].queryset = (
                StoreCategory.objects.filter(is_active=True)
                | StoreCategory.objects.filter(pk=self.instance.category_id)
            ).distinct().order_by("name")
        _apply_bootstrap(self)


class StoreCreateForm(StoreForm):
    activate_on_create = forms.BooleanField(
        required=False,
        label="Activate store immediately",
        help_text="Requires approve permission. Otherwise the store stays PENDING.",
    )

    class Meta(StoreForm.Meta):
        fields = StoreForm.Meta.fields

    def __init__(self, *args, can_activate=False, **kwargs):
        super().__init__(*args, **kwargs)
        self.can_activate = can_activate
        if not can_activate:
            self.fields.pop("activate_on_create", None)
        else:
            _apply_bootstrap(self)


class OptionalPrimaryStoreUserForm(forms.Form):
    create_primary_user = forms.BooleanField(
        required=False,
        label="Create primary Store User now",
    )
    first_name = forms.CharField(max_length=150, required=False)
    last_name = forms.CharField(max_length=150, required=False)
    username = forms.CharField(
        max_length=150,
        required=False,
        validators=[USERNAME_VALIDATOR],
    )
    email = forms.EmailField(required=False)
    phone_number = forms.CharField(max_length=20, required=False)
    password = forms.CharField(widget=forms.PasswordInput, required=False)
    confirm_password = forms.CharField(widget=forms.PasswordInput, required=False)
    designation = forms.CharField(max_length=100, required=False)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        _apply_bootstrap(self)

    def clean(self):
        cleaned = super().clean()
        create_user = cleaned.get("create_primary_user")
        if not create_user:
            return cleaned

        required_fields = ("username", "email", "password", "confirm_password")
        for field_name in required_fields:
            if not cleaned.get(field_name):
                self.add_error(field_name, "This field is required when creating a primary user.")

        username = (cleaned.get("username") or "").strip()
        email = (cleaned.get("email") or "").strip().lower()
        phone_number = (cleaned.get("phone_number") or "").strip()
        password = cleaned.get("password")
        confirm = cleaned.get("confirm_password")

        if username:
            cleaned["username"] = username
            try:
                USERNAME_VALIDATOR(username)
            except ValidationError as exc:
                self.add_error("username", exc)
            if (
                "username" not in self.errors
                and User.objects.filter(username__iexact=username).exists()
            ):
                self.add_error("username", "This username is already in use.")
        if email:
            cleaned["email"] = email
            if User.objects.filter(email__iexact=email).exists():
                self.add_error("email", "This email is already in use.")
        if phone_number:
            cleaned["phone_number"] = phone_number
            if User.objects.filter(phone_number=phone_number).exists():
                self.add_error("phone_number", "This phone number is already in use.")
        else:
            cleaned["phone_number"] = None

        if password and confirm and password != confirm:
            self.add_error("confirm_password", "Passwords do not match.")
        if password:
            try:
                validate_password(password)
            except ValidationError as exc:
                self.add_error("password", exc)
        return cleaned

    def to_user_data(self):
        if not self.cleaned_data.get("create_primary_user"):
            return None
        return {
            "username": self.cleaned_data["username"],
            "email": self.cleaned_data["email"],
            "first_name": self.cleaned_data.get("first_name", ""),
            "last_name": self.cleaned_data.get("last_name", ""),
            "phone_number": self.cleaned_data.get("phone_number"),
            "password": self.cleaned_data["password"],
            "designation": self.cleaned_data.get("designation", ""),
        }


class StoreUserForm(forms.Form):
    first_name = forms.CharField(max_length=150, required=False)
    last_name = forms.CharField(max_length=150, required=False)
    username = forms.CharField(
        max_length=150,
        validators=[USERNAME_VALIDATOR],
    )
    email = forms.EmailField()
    phone_number = forms.CharField(max_length=20, required=False)
    designation = forms.CharField(max_length=100, required=False)
    is_primary = forms.BooleanField(required=False, label="Primary Store User")
    can_manage_inventory = forms.BooleanField(
        required=False,
        label="Can manage inventory",
        help_text="Allow this user to change stock for their assigned store.",
    )
    password = forms.CharField(widget=forms.PasswordInput, required=False)
    confirm_password = forms.CharField(widget=forms.PasswordInput, required=False)

    def __init__(self, *args, instance=None, store=None, require_password=True, **kwargs):
        self.instance = instance
        self.store = store
        self.require_password = require_password
        super().__init__(*args, **kwargs)
        if require_password:
            self.fields["password"].required = True
            self.fields["confirm_password"].required = True
        if instance is not None:
            self.fields["username"].initial = instance.user.username
            self.fields["email"].initial = instance.user.email
            self.fields["first_name"].initial = instance.user.first_name
            self.fields["last_name"].initial = instance.user.last_name
            self.fields["phone_number"].initial = instance.user.phone_number or ""
            self.fields["designation"].initial = instance.designation
            self.fields["is_primary"].initial = instance.is_primary
            self.fields["can_manage_inventory"].initial = instance.can_manage_inventory
        else:
            self.fields["can_manage_inventory"].initial = True
        _apply_bootstrap(self)

    def clean_username(self):
        username = self.cleaned_data["username"].strip()
        USERNAME_VALIDATOR(username)
        qs = User.objects.filter(username__iexact=username)
        if self.instance is not None:
            qs = qs.exclude(pk=self.instance.user_id)
        if qs.exists():
            raise ValidationError("This username is already in use.")
        return username

    def clean_email(self):
        email = self.cleaned_data["email"].strip().lower()
        qs = User.objects.filter(email__iexact=email)
        if self.instance is not None:
            qs = qs.exclude(pk=self.instance.user_id)
        if qs.exists():
            raise ValidationError("This email is already in use.")
        return email

    def clean_phone_number(self):
        phone_number = self.cleaned_data["phone_number"].strip()
        if not phone_number:
            return None
        qs = User.objects.filter(phone_number=phone_number)
        if self.instance is not None:
            qs = qs.exclude(pk=self.instance.user_id)
        if qs.exists():
            raise ValidationError("This phone number is already in use.")
        return phone_number

    def clean(self):
        cleaned = super().clean()
        password = cleaned.get("password")
        confirm = cleaned.get("confirm_password")
        if self.require_password and not password:
            self.add_error("password", "This field is required.")
        if password or confirm:
            if password != confirm:
                self.add_error("confirm_password", "Passwords do not match.")
            if password:
                try:
                    validate_password(password)
                except ValidationError as exc:
                    self.add_error("password", exc)
        # Primary reassignment is allowed; the service/view demotes the previous primary.
        return cleaned


class StoreStatusChangeForm(forms.Form):
    new_status = forms.ChoiceField(choices=StoreStatus.choices)
    reason = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={"rows": 2}),
    )

    def __init__(self, *args, current_status=None, **kwargs):
        from .status import allowed_next_statuses

        super().__init__(*args, **kwargs)
        self.current_status = current_status
        if current_status is not None:
            next_statuses = allowed_next_statuses(current_status)
            self.fields["new_status"].choices = [
                (value, label)
                for value, label in StoreStatus.choices
                if value in next_statuses
            ]
        _apply_bootstrap(self)

    def clean(self):
        from .status import validate_status_transition

        cleaned = super().clean()
        new_status = cleaned.get("new_status")
        reason = cleaned.get("reason", "")
        if self.current_status is not None and new_status:
            try:
                validate_status_transition(
                    current_status=self.current_status,
                    new_status=new_status,
                    reason=reason,
                )
            except ValidationError as exc:
                message = exc.messages[0] if getattr(exc, "messages", None) else str(exc)
                if "reason" in message.lower():
                    self.add_error("reason", message)
                else:
                    self.add_error("new_status", message)
        return cleaned


class StorePortalProfileForm(forms.Form):
    """
    Allowed store-portal profile/contact fields only.

    Store code, type, status, commission, category and ownership are excluded.
    """

    first_name = forms.CharField(max_length=150, required=False)
    last_name = forms.CharField(max_length=150, required=False)
    phone_number = forms.CharField(max_length=20, required=False)
    designation = forms.CharField(max_length=100, required=False)
    contact_phone = forms.CharField(max_length=20, required=False, label="Store contact phone")
    alternative_phone = forms.CharField(
        max_length=20,
        required=False,
        label="Store alternative phone",
    )
    email = forms.EmailField(required=False, label="Store email")
    description = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={"rows": 3}),
        label="Store description",
    )

    def __init__(self, *args, user=None, membership=None, store=None, **kwargs):
        self.user = user
        self.membership = membership
        self.store = store
        super().__init__(*args, **kwargs)
        if user is not None:
            self.fields["first_name"].initial = user.first_name
            self.fields["last_name"].initial = user.last_name
            self.fields["phone_number"].initial = user.phone_number or ""
        if membership is not None:
            self.fields["designation"].initial = membership.designation
        if store is not None:
            self.fields["contact_phone"].initial = store.contact_phone
            self.fields["alternative_phone"].initial = store.alternative_phone
            self.fields["email"].initial = store.email
            self.fields["description"].initial = store.description
        _apply_bootstrap(self)

    def clean_phone_number(self):
        phone_number = self.cleaned_data["phone_number"].strip()
        if not phone_number:
            return None
        qs = User.objects.filter(phone_number=phone_number)
        if self.user is not None:
            qs = qs.exclude(pk=self.user.pk)
        if qs.exists():
            raise ValidationError("This phone number is already in use.")
        return phone_number

    def save(self):
        from django.db import transaction

        with transaction.atomic():
            self.user.first_name = self.cleaned_data.get("first_name", "")
            self.user.last_name = self.cleaned_data.get("last_name", "")
            self.user.phone_number = self.cleaned_data.get("phone_number")
            self.user.save(update_fields=["first_name", "last_name", "phone_number"])

            self.membership.designation = self.cleaned_data.get("designation", "")
            self.membership.save(update_fields=["designation", "updated_at"])

            store = Store.objects.select_for_update().get(pk=self.store.pk)
            store.contact_phone = self.cleaned_data.get("contact_phone", "")
            store.alternative_phone = self.cleaned_data.get("alternative_phone", "")
            store.email = self.cleaned_data.get("email", "")
            store.description = self.cleaned_data.get("description", "")
            store.save(
                update_fields=[
                    "contact_phone",
                    "alternative_phone",
                    "email",
                    "description",
                    "updated_at",
                ]
            )
        return store
