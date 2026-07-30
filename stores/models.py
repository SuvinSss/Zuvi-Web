from decimal import Decimal

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import IntegrityError, models, transaction
from django.utils.text import slugify

from accounts.models import Role

from .validators import store_image_upload_to, validate_store_image


class StoreType(models.TextChoices):
    OWN_STORE = "OWN_STORE", "Own Store"
    PARTNER_STORE = "PARTNER_STORE", "Partner Store"
    PARTNER_HOME = "PARTNER_HOME", "Partner Home"


class StoreStatus(models.TextChoices):
    PENDING = "PENDING", "Pending"
    ACTIVE = "ACTIVE", "Active"
    SUSPENDED = "SUSPENDED", "Suspended"
    REJECTED = "REJECTED", "Rejected"


class StoreCategory(models.Model):
    name = models.CharField(max_length=100, unique=True)
    slug = models.SlugField(max_length=120, unique=True, blank=True)
    description = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name_plural = "store categories"
        ordering = ["name"]

    def save(self, *args, **kwargs):
        if not self.slug:
            base_slug = slugify(self.name) or "category"
            candidate = base_slug
            suffix = 2
            while StoreCategory.objects.filter(slug=candidate).exclude(pk=self.pk).exists():
                candidate = f"{base_slug}-{suffix}"
                suffix += 1
            self.slug = candidate
        super().save(*args, **kwargs)

    def __str__(self):
        return self.name


class Store(models.Model):
    name = models.CharField(max_length=200)
    store_code = models.CharField(max_length=32, unique=True, editable=False, blank=True)
    store_type = models.CharField(max_length=32, choices=StoreType.choices)
    status = models.CharField(
        max_length=32,
        choices=StoreStatus.choices,
        default=StoreStatus.PENDING,
    )
    category = models.ForeignKey(
        StoreCategory,
        on_delete=models.PROTECT,
        related_name="stores",
    )
    address = models.OneToOneField(
        "locations.Address",
        on_delete=models.PROTECT,
        related_name="store",
    )
    contact_phone = models.CharField(max_length=20, blank=True)
    alternative_phone = models.CharField(max_length=20, blank=True)
    email = models.EmailField(blank=True)
    description = models.TextField(blank=True)
    commission_percentage = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=Decimal("0.00"),
        validators=[
            MinValueValidator(Decimal("0")),
            MaxValueValidator(Decimal("100")),
        ],
    )
    image = models.ImageField(
        upload_to=store_image_upload_to,
        blank=True,
        null=True,
        validators=[validate_store_image],
    )
    is_active = models.BooleanField(default=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="created_stores",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        permissions = (
            ("approve_store", "Can approve or reject stores"),
            ("suspend_store", "Can suspend stores"),
        )
        constraints = [
            models.CheckConstraint(
                condition=models.Q(commission_percentage__gte=Decimal("0"))
                & models.Q(commission_percentage__lte=Decimal("100")),
                name="store_commission_percentage_range",
            ),
        ]

    def clean(self):
        super().clean()
        if self.commission_percentage is not None and not (
            Decimal("0") <= self.commission_percentage <= Decimal("100")
        ):
            raise ValidationError(
                {
                    "commission_percentage": (
                        "Commission percentage must be between 0 and 100."
                    )
                }
            )

    def save(self, *args, **kwargs):
        if self.store_code:
            return super().save(*args, **kwargs)

        from .services import STORE_CODE_MAX_ATTEMPTS, generate_store_code

        last_error = None
        for _ in range(STORE_CODE_MAX_ATTEMPTS):
            self.store_code = generate_store_code(exclude_pk=self.pk)
            try:
                with transaction.atomic():
                    return super().save(*args, **kwargs)
            except IntegrityError as exc:
                last_error = exc
                self.store_code = ""
                if self.pk:
                    raise
        raise IntegrityError(
            "Could not allocate a unique store code under concurrent load."
        ) from last_error

    def __str__(self):
        return f"{self.name} ({self.store_code})"


class StoreUser(models.Model):
    store = models.ForeignKey(
        Store,
        on_delete=models.CASCADE,
        related_name="store_users",
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="store_memberships",
    )
    is_primary = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)
    can_manage_inventory = models.BooleanField(
        default=True,
        help_text="When True, this store user may change inventory for their store.",
    )
    designation = models.CharField(max_length=100, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="created_store_users",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-is_primary", "user__username"]
        constraints = [
            models.UniqueConstraint(
                fields=["store", "user"],
                name="unique_store_user_pair",
            ),
            models.UniqueConstraint(
                fields=["user"],
                name="unique_store_assignment_per_user",
            ),
            models.UniqueConstraint(
                fields=["store"],
                condition=models.Q(is_primary=True),
                name="unique_primary_store_user_per_store",
            ),
        ]

    def clean(self):
        super().clean()
        if self.user_id and self.user.role != Role.STORE_USER:
            raise ValidationError(
                {"user": "Only users with role STORE_USER can be linked to a store."}
            )

    def __str__(self):
        primary = "primary" if self.is_primary else "member"
        return f"{self.user} @ {self.store.store_code} ({primary})"


class StoreStatusHistory(models.Model):
    store = models.ForeignKey(
        Store,
        on_delete=models.CASCADE,
        related_name="status_history",
    )
    old_status = models.CharField(
        max_length=32,
        choices=StoreStatus.choices,
        blank=True,
    )
    new_status = models.CharField(max_length=32, choices=StoreStatus.choices)
    changed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="store_status_changes",
    )
    reason = models.TextField(blank=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name_plural = "store status histories"
        ordering = ["-created_at"]

    def __str__(self):
        old = self.old_status or "—"
        return f"{self.store.store_code}: {old} → {self.new_status}"
