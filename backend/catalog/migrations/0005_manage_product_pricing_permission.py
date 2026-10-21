from django.db import migrations


def rename_pricing_permission(apps, schema_editor):
    Permission = apps.get_model("auth", "Permission")
    ContentType = apps.get_model("contenttypes", "ContentType")
    try:
        ct = ContentType.objects.get(app_label="catalog", model="product")
    except ContentType.DoesNotExist:
        return

    old = Permission.objects.filter(
        content_type=ct, codename="set_product_pricing"
    ).first()
    new_exists = Permission.objects.filter(
        content_type=ct, codename="manage_product_pricing"
    ).exists()

    if old and not new_exists:
        old.codename = "manage_product_pricing"
        old.name = "Can manage product pricing"
        old.save(update_fields=["codename", "name"])
    elif old and new_exists:
        # Prefer the renamed permission; drop the legacy codename.
        old.delete()


def revert_pricing_permission(apps, schema_editor):
    Permission = apps.get_model("auth", "Permission")
    ContentType = apps.get_model("contenttypes", "ContentType")
    try:
        ct = ContentType.objects.get(app_label="catalog", model="product")
    except ContentType.DoesNotExist:
        return

    current = Permission.objects.filter(
        content_type=ct, codename="manage_product_pricing"
    ).first()
    old_exists = Permission.objects.filter(
        content_type=ct, codename="set_product_pricing"
    ).exists()

    if current and not old_exists:
        current.codename = "set_product_pricing"
        current.name = "Can set product pricing"
        current.save(update_fields=["codename", "name"])
    elif current and old_exists:
        current.delete()


class Migration(migrations.Migration):

    dependencies = [
        ("catalog", "0004_product_unit_value_low_stock_featured"),
        ("auth", "0012_alter_user_first_name_max_length"),
        ("contenttypes", "0002_remove_content_type_name"),
    ]

    operations = [
        migrations.AlterModelOptions(
            name="product",
            options={
                "ordering": ["-created_at"],
                "permissions": (
                    ("approve_product", "Can approve or reject products"),
                    ("manage_product_pricing", "Can manage product pricing"),
                ),
            },
        ),
        migrations.RunPython(rename_pricing_permission, revert_pricing_permission),
    ]
