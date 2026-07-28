from django import forms
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group, Permission
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError

from .models import AdminProfile, Role

User = get_user_model()


class AdminCreateForm(forms.Form):
    first_name = forms.CharField(max_length=150, required=True)
    last_name = forms.CharField(max_length=150, required=True)
    username = forms.CharField(max_length=150, required=True)
    email = forms.EmailField(required=True)
    phone_number = forms.CharField(max_length=20, required=False)
    employee_id = forms.CharField(max_length=50, required=False)
    designation = forms.CharField(max_length=100, required=False)
    notes = forms.CharField(widget=forms.Textarea, required=False)
    password = forms.CharField(widget=forms.PasswordInput, required=True)
    confirm_password = forms.CharField(widget=forms.PasswordInput, required=True)
    groups = forms.ModelMultipleChoiceField(
        queryset=Group.objects.all(),
        required=False,
        widget=forms.CheckboxSelectMultiple,
    )
    user_permissions = forms.ModelMultipleChoiceField(
        queryset=Permission.objects.select_related("content_type").all(),
        required=False,
        widget=forms.CheckboxSelectMultiple,
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        text_fields = [
            "first_name",
            "last_name",
            "username",
            "email",
            "phone_number",
            "employee_id",
            "designation",
            "password",
            "confirm_password",
        ]
        for field_name in text_fields:
            self.fields[field_name].widget.attrs.update({"class": "form-control"})
        self.fields["notes"].widget.attrs.update({"class": "form-control", "rows": 3})

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

    def clean_employee_id(self):
        employee_id = self.cleaned_data["employee_id"].strip()
        if employee_id and AdminProfile.objects.filter(employee_id=employee_id).exists():
            raise ValidationError("This employee ID is already in use.")
        return employee_id

    def clean(self):
        cleaned_data = super().clean()
        password = cleaned_data.get("password")
        confirm_password = cleaned_data.get("confirm_password")

        if password and confirm_password and password != confirm_password:
            self.add_error("confirm_password", "Passwords do not match.")

        if password:
            temp_user = User(
                username=cleaned_data.get("username", ""),
                email=cleaned_data.get("email", ""),
                first_name=cleaned_data.get("first_name", ""),
                last_name=cleaned_data.get("last_name", ""),
            )
            try:
                validate_password(password, user=temp_user)
            except ValidationError as exc:
                self.add_error("password", exc)

        return cleaned_data


class AdminUpdateForm(forms.Form):
    first_name = forms.CharField(max_length=150, required=True)
    last_name = forms.CharField(max_length=150, required=True)
    username = forms.CharField(max_length=150, required=True)
    email = forms.EmailField(required=True)
    phone_number = forms.CharField(max_length=20, required=False)
    employee_id = forms.CharField(max_length=50, required=False)
    designation = forms.CharField(max_length=100, required=False)
    notes = forms.CharField(widget=forms.Textarea, required=False)
    groups = forms.ModelMultipleChoiceField(
        queryset=Group.objects.all(),
        required=False,
        widget=forms.CheckboxSelectMultiple,
    )
    user_permissions = forms.ModelMultipleChoiceField(
        queryset=Permission.objects.select_related("content_type").all(),
        required=False,
        widget=forms.CheckboxSelectMultiple,
    )

    def __init__(self, *args, **kwargs):
        self.instance = kwargs.pop("instance")
        super().__init__(*args, **kwargs)
        text_fields = [
            "first_name",
            "last_name",
            "username",
            "email",
            "phone_number",
            "employee_id",
            "designation",
        ]
        for field_name in text_fields:
            self.fields[field_name].widget.attrs.update({"class": "form-control"})
        self.fields["notes"].widget.attrs.update({"class": "form-control", "rows": 3})
        self.fields["first_name"].initial = self.instance.first_name
        self.fields["last_name"].initial = self.instance.last_name
        self.fields["username"].initial = self.instance.username
        self.fields["email"].initial = self.instance.email
        self.fields["phone_number"].initial = self.instance.phone_number
        self.fields["groups"].initial = self.instance.groups.all()
        self.fields["user_permissions"].initial = self.instance.user_permissions.all()
        try:
            profile = self.instance.admin_profile
        except AdminProfile.DoesNotExist:
            profile = None
        if profile:
            self.fields["employee_id"].initial = profile.employee_id
            self.fields["designation"].initial = profile.designation
            self.fields["notes"].initial = profile.notes

    def clean_username(self):
        username = self.cleaned_data["username"].strip()
        if User.objects.filter(username__iexact=username).exclude(pk=self.instance.pk).exists():
            raise ValidationError("This username is already in use.")
        return username

    def clean_email(self):
        email = self.cleaned_data["email"].strip().lower()
        if User.objects.filter(email__iexact=email).exclude(pk=self.instance.pk).exists():
            raise ValidationError("This email is already in use.")
        return email

    def clean_phone_number(self):
        phone_number = self.cleaned_data["phone_number"].strip()
        if phone_number and User.objects.filter(phone_number=phone_number).exclude(
            pk=self.instance.pk
        ).exists():
            raise ValidationError("This phone number is already in use.")
        return phone_number

    def clean_employee_id(self):
        employee_id = self.cleaned_data["employee_id"].strip()
        profile_qs = AdminProfile.objects.filter(employee_id=employee_id)
        try:
            profile = self.instance.admin_profile
        except AdminProfile.DoesNotExist:
            profile = None
        if profile:
            profile_qs = profile_qs.exclude(pk=profile.pk)
        if employee_id and profile_qs.exists():
            raise ValidationError("This employee ID is already in use.")
        return employee_id

    def save(self):
        self.instance.first_name = self.cleaned_data["first_name"]
        self.instance.last_name = self.cleaned_data["last_name"]
        self.instance.username = self.cleaned_data["username"]
        self.instance.email = self.cleaned_data["email"]
        self.instance.phone_number = self.cleaned_data["phone_number"] or None
        self.instance.role = Role.ADMIN
        self.instance.is_staff = True
        self.instance.is_superuser = False
        self.instance.save()
        self.instance.groups.set(self.cleaned_data["groups"])
        self.instance.user_permissions.set(self.cleaned_data["user_permissions"])
        return self.instance
