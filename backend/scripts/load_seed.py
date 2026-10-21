"""Seed a THROWAWAY PostgreSQL database for load tests (never point at real data).

    DATABASE_URL=postgres://.../zuvi_load python manage.py shell < scripts/load_seed.py
Env: LOAD_PRODUCTS (default 3000).
"""
import os
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.utils import timezone

from accounts.models import Role
from catalog.models import Product, ProductCategory, ProductStatus
from catalog.services import create_product
from locations.models import Address
from stores.models import Store, StoreCategory, StoreStatus, StoreType

N = int(os.environ.get("LOAD_PRODUCTS", "3000"))
User = get_user_model()
admin, _ = User.objects.get_or_create(username="load_admin", defaults=dict(
    email="load@example.test", role=Role.SUPER_ADMIN, is_staff=True, is_superuser=True))
admin.set_password("Load-pass-12345!"); admin.save()

stores = []
for i in range(3):
    store = Store.objects.filter(name=f"Load Mart {i}").first() or Store.objects.create(
        name=f"Load Mart {i}", store_type=StoreType.OWN_STORE, status=StoreStatus.ACTIVE, is_active=True,
        commission_percentage=Decimal("5.00"),
        address=Address.objects.create(line1="1 Load Rd", city="Bengaluru", state="Karnataka", postal_code="560001",
                                       latitude=Decimal("12.9716"), longitude=Decimal("77.5946")),
        category=StoreCategory.objects.create(name=f"Load Cat {i}"))
    stores.append(store)
cats = [ProductCategory.objects.get_or_create(name=f"Load Category {i}")[0] for i in range(12)]

have = Product.objects.filter(sku__startswith="LOAD-").count()
for n in range(have, N):
    create_product(
        store=stores[n % 3], created_by=admin, initial_status=ProductStatus.APPROVED,
        product_data=dict(name=f"Load Product {n:05d} {'organic ' if n % 4 == 0 else ''}fresh", sku=f"LOAD-{n:05d}",
                          category=cats[n % 12], store_price=Decimal(10 + n % 400), unit="PIECE", unit_value=Decimal("1.000")),
    )
Product.objects.filter(sku__startswith="LOAD-").update(
    approved_by=admin, approved_at=timezone.now(), stock_quantity=Decimal("25.000"), selling_price=Decimal("120.00"), final_price=Decimal("120.00"))
print("products:", Product.objects.filter(sku__startswith="LOAD-").count())
