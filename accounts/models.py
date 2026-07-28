from django.conf import settings
from django.contrib.auth.models import AbstractUser
from django.core.exceptions import ValidationError
from django.db import models


class Role(models.TextChoices):
    SUPER_ADMIN = "SUPER_ADMIN", "Super Admin"
    ADMIN = "ADMIN", "Admin"
    STORE_USER = "STORE_USER", "Store User"
    CUSTOMER = "CUSTOMER", "Customer"
    DELIVERY_AGENT = "DELIVERY_AGENT", "Delivery Agent"


class User(AbstractUser):
    email = models.EmailField(unique=True)
    phone_number = models.CharField(
        max_length=20,
        unique=True,
        null=True,
        blank=True,
    )
    role = models.CharField(
        max_length=32,
        choices=Role.choices,
        default=Role.CUSTOMER,
    )
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        permissions = (
            ("access_stores_module", "Can access stores module"),
            ("access_products_module", "Can access products module"),
            ("access_inventory_module", "Can access inventory module"),
            ("access_customers_module", "Can access customers module"),
            ("access_orders_module", "Can access orders module"),
            ("access_delivery_module", "Can access delivery module"),
        )

    def __str__(self):
        return self.username


class AdminProfile(models.Model):
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="admin_profile",
    )
    employee_id = models.CharField(max_length=50, unique=True, blank=True, null=True)
    designation = models.CharField(max_length=100, blank=True)
    notes = models.TextField(blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="created_admin_profiles",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def clean(self):
        super().clean()
        if self.user and self.user.role not in {Role.ADMIN, Role.SUPER_ADMIN}:
            raise ValidationError(
                {"user": "AdminProfile can only be assigned to ADMIN or SUPER_ADMIN users."}
            )

    def __str__(self):
        return f"{self.user.username} profile"


class AdminAuditLog(models.Model):
    class Action(models.TextChoices):
        ADMIN_CREATED = "ADMIN_CREATED", "Admin Created"
        ADMIN_UPDATED = "ADMIN_UPDATED", "Admin Updated"
        ADMIN_ACTIVATED = "ADMIN_ACTIVATED", "Admin Activated"
        ADMIN_DEACTIVATED = "ADMIN_DEACTIVATED", "Admin Deactivated"
        GROUP_ASSIGNED = "GROUP_ASSIGNED", "Group Assigned"
        GROUP_REMOVED = "GROUP_REMOVED", "Group Removed"
        PERMISSION_ASSIGNED = "PERMISSION_ASSIGNED", "Permission Assigned"
        PERMISSION_REMOVED = "PERMISSION_REMOVED", "Permission Removed"

    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="admin_audit_actions",
    )
    action = models.CharField(max_length=50, choices=Action.choices)
    target_user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="admin_audit_targets",
    )
    description = models.TextField()
    metadata = models.JSONField(default=dict, blank=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.action} by {self.actor.username}"
