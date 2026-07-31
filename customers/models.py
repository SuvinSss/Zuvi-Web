from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import IntegrityError, models, router, transaction

from accounts.models import Role


class RegistrationSource(models.TextChoices):
    WEBSITE = "WEBSITE", "Website"
    MANAGEMENT_PORTAL = "MANAGEMENT_PORTAL", "Management Portal"
    MOBILE_APP = "MOBILE_APP", "Mobile App"


class VerificationStatus(models.TextChoices):
    UNVERIFIED = "UNVERIFIED", "Unverified"
    VERIFIED = "VERIFIED", "Verified"


class AddressLabel(models.TextChoices):
    HOME = "HOME", "Home"
    WORK = "WORK", "Work"
    OTHER = "OTHER", "Other"


class Customer(models.Model):
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="customer_profile",
    )
    customer_code = models.CharField(
        max_length=32,
        unique=True,
        editable=False,
        blank=True,
    )
    registration_source = models.CharField(
        max_length=32,
        choices=RegistrationSource.choices,
    )
    verification_status = models.CharField(
        max_length=32,
        choices=VerificationStatus.choices,
        default=VerificationStatus.UNVERIFIED,
    )
    date_of_birth = models.DateField(null=True, blank=True)
    notes = models.TextField(blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="created_customers",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        permissions = (
            ("activate_customer", "Can activate or deactivate customers"),
            ("verify_customer", "Can verify or unverify customers"),
        )

    def clean(self):
        super().clean()
        user = getattr(self, "user", None)
        if user is None:
            return
        if user.role != Role.CUSTOMER:
            raise ValidationError(
                {"user": "Customer profile can only be assigned to CUSTOMER users."}
            )
        if user.is_staff or user.is_superuser:
            raise ValidationError(
                {
                    "user": (
                        "Customer users must have is_staff=False and "
                        "is_superuser=False."
                    )
                }
            )

    def save(self, *args, **kwargs):
        if self.customer_code:
            return super().save(*args, **kwargs)

        from .services import CUSTOMER_CODE_MAX_ATTEMPTS, generate_customer_code

        last_error = None
        for _ in range(CUSTOMER_CODE_MAX_ATTEMPTS):
            self.customer_code = generate_customer_code(exclude_pk=self.pk)
            try:
                with transaction.atomic():
                    return super().save(*args, **kwargs)
            except IntegrityError as exc:
                last_error = exc
                self.customer_code = ""
                if self.pk:
                    raise
        raise IntegrityError(
            "Could not allocate a unique customer code under concurrent load."
        ) from last_error

    def __str__(self):
        return f"{self.user.get_username()} ({self.customer_code or 'pending'})"


class CustomerAddress(models.Model):
    customer = models.ForeignKey(
        Customer,
        on_delete=models.CASCADE,
        related_name="addresses",
    )
    address = models.OneToOneField(
        "locations.Address",
        on_delete=models.PROTECT,
        related_name="customer_address",
    )
    label = models.CharField(
        max_length=32,
        choices=AddressLabel.choices,
        default=AddressLabel.HOME,
    )
    recipient_name = models.CharField(max_length=150)
    phone_number = models.CharField(max_length=20)
    delivery_instructions = models.TextField(blank=True)
    is_default = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-is_default", "-is_active", "-created_at"]
        verbose_name_plural = "customer addresses"
        constraints = [
            models.UniqueConstraint(
                fields=["customer"],
                condition=models.Q(is_default=True, is_active=True),
                name="unique_active_default_address_per_customer",
            ),
        ]

    def validate_constraints(self, exclude=None):
        """
        Skip model-level validation of the active-default uniqueness rule.

        save() clears other active defaults in the same transaction before
        writing, so full_clean()/ModelForm would otherwise reject promoting a
        new default. The database UniqueConstraint still enforces integrity.
        """
        constraints = self.get_constraints()
        using = router.db_for_write(self.__class__, instance=self)

        errors = {}
        for model_class, model_constraints in constraints:
            for constraint in model_constraints:
                if (
                    getattr(constraint, "name", None)
                    == "unique_active_default_address_per_customer"
                ):
                    continue
                try:
                    constraint.validate(
                        model_class, self, exclude=exclude, using=using
                    )
                except ValidationError as exc:
                    if (
                        getattr(exc, "code", None) == "unique"
                        and len(constraint.fields) == 1
                    ):
                        errors.setdefault(constraint.fields[0], []).append(exc)
                    else:
                        errors = exc.update_error_dict(errors)
        if errors:
            raise ValidationError(errors)

    def clean(self):
        super().clean()
        address = getattr(self, "address", None)
        if address is not None:
            address.full_clean()

    def save(self, *args, **kwargs):
        with transaction.atomic():
            if self.is_default and self.is_active and self.customer_id:
                (
                    CustomerAddress.objects.filter(
                        customer_id=self.customer_id,
                        is_default=True,
                        is_active=True,
                    )
                    .exclude(pk=self.pk)
                    .update(is_default=False)
                )
            super().save(*args, **kwargs)

    def __str__(self):
        default = "default" if self.is_default else "secondary"
        return f"{self.customer.customer_code} · {self.get_label_display()} ({default})"
