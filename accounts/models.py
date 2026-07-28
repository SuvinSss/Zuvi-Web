from django.contrib.auth.models import AbstractUser
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

    def __str__(self):
        return self.username
