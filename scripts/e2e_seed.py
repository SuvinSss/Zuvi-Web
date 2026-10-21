"""Seed a throwaway database for the Playwright run: one Super Admin, one store, one category.

Usage:  python manage.py shell < scripts/e2e_seed.py   (local SQLite only)
"""
from decimal import Decimal

from django.contrib.auth import get_user_model

from accounts.models import Role
from catalog.models import ProductCategory
from locations.models import Address
from stores.models import Store, StoreCategory, StoreStatus, StoreType

User = get_user_model()
if not User.objects.filter(username="e2e_admin").exists():
    User.objects.create_user(
        username="e2e_admin", email="e2e@example.test", password="E2e-pass-12345!",
        role=Role.SUPER_ADMIN, is_staff=True, is_superuser=True,
    )
if not Store.objects.filter(name="E2E Mart").exists():
    Store.objects.create(
        name="E2E Mart", store_type=StoreType.OWN_STORE, status=StoreStatus.ACTIVE, is_active=True,
        commission_percentage=Decimal("5.00"),
        address=Address.objects.create(line1="1 Test Rd", city="Bengaluru", state="Karnataka", postal_code="560001",
                                       latitude=Decimal("12.9716"), longitude=Decimal("77.5946")),
        category=StoreCategory.objects.create(name="E2E Grocery"),
    )
ProductCategory.objects.get_or_create(name="E2E Fruit")
print("seeded")
