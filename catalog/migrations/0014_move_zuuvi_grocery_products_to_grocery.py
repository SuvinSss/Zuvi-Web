"""One-time data fix: move every existing ZuuVi Grocery product into "Grocery".

Status, approval, prices and stock are untouched, so products stay on the shop.
Products added after this migration runs keep whatever category they are given.
"""

from django.db import migrations
from django.utils.text import slugify

STORE_NAME = "ZuuVi Grocery"
CATEGORY_NAME = "Grocery"


def _unique_slug(ProductCategory, base):
    candidate, suffix = base, 2
    while ProductCategory.objects.filter(slug=candidate).exists():
        candidate = f"{base}-{suffix}"
        suffix += 1
    return candidate


def forward(apps, schema_editor):
    Store = apps.get_model("stores", "Store")
    Product = apps.get_model("catalog", "Product")
    ProductCategory = apps.get_model("catalog", "ProductCategory")
    AdminAuditLog = apps.get_model("accounts", "AdminAuditLog")
    User = apps.get_model("accounts", "User")

    stores = list(Store.objects.filter(name__iexact=STORE_NAME))
    if len(stores) != 1:
        return
    store = stores[0]

    grocery = ProductCategory.objects.filter(
        name__iexact=CATEGORY_NAME, parent__isnull=True
    ).order_by("pk").first()
    if grocery is None:
        grocery = ProductCategory.objects.create(
            name=CATEGORY_NAME,
            slug=_unique_slug(ProductCategory, slugify(CATEGORY_NAME)),
            is_active=True,
        )

    moved = list(
        Product.objects.select_for_update()
        .filter(store=store)
        .exclude(category=grocery)
        .values_list("pk", "category_id")
    )
    if not moved:
        return
    Product.objects.filter(pk__in=[pk for pk, _ in moved]).update(category=grocery)

    actor = User.objects.filter(is_superuser=True, is_active=True).order_by("pk").first()
    if actor is not None:
        AdminAuditLog.objects.create(
            actor=actor,
            action="PRODUCT_UPDATED",
            description=(
                f"Data migration moved {len(moved)} products of store "
                f"{store.store_code} to category '{grocery.name}'."
            ),
            metadata={
                "store_id": store.pk,
                "category_id": grocery.pk,
                "previous_category_by_product": {str(pk): old for pk, old in moved},
            },
        )


class Migration(migrations.Migration):

    dependencies = [
        ("catalog", "0013_product_search_keywords"),
        ("stores", "0006_storeuser_can_manage_orders"),
        ("accounts", "0008_alter_user_managers"),
    ]

    operations = [
        migrations.RunPython(forward, migrations.RunPython.noop),
    ]
