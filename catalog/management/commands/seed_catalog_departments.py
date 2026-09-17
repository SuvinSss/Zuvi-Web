"""Add the reviewed department tree without changing existing taxonomy."""
from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError
from django.db import IntegrityError, transaction
from django.utils.text import slugify

from catalog.models import ProductCategory

DEPARTMENTS = (
    ("Groceries & Daily Essentials", ("Fruits & Vegetables", "Dairy & Bakery", "Rice, Atta & Pulses", "Oils & Spices", "Snacks & Beverages", "Household Essentials")),
    ("Jewellery & Accessories", ("Earrings", "Necklaces", "Bangles & Bracelets", "Rings", "Accessories")),
    ("Mobiles & Accessories", ("Mobiles", "Cases & Protection", "Chargers & Cables", "Audio Accessories")),
    ("Home & Kitchen", ("Cookware", "Kitchen Tools", "Storage & Organisation", "Home Essentials")),
    ("Beauty & Personal Care", ("Skin Care", "Hair Care", "Bath & Body", "Grooming")),
    ("Fashion", ("Women", "Men", "Kids", "Bags & Accessories")),
    ("Stationery & Toys", ("Writing & Notebooks", "Art & Craft", "Office Supplies", "Toys & Games")),
)


def category_plan(existing):
    """Validate every match before creating anything; never infer a rename."""
    by_slug = {row.slug: row for row in existing}
    by_pk = {row.pk: row for row in existing}
    plan = []
    conflicts = []
    for department, children in DEPARTMENTS:
        for name, parent_slug in [(department, None)] + [(child, slugify(department)) for child in children]:
            slug = slugify(name)
            row = by_slug.get(slug)
            name_matches = [item for item in existing if item.name.casefold() == name.casefold()]
            if any(item is not row for item in name_matches):
                conflicts.append(f"{name}: existing name has a different slug or placement")
                continue
            if row:
                parent = by_pk.get(row.parent_id)
                if row.name != name or (parent.slug if parent else None) != parent_slug or not row.is_active:
                    conflicts.append(f"{name}: existing slug, parent, name or active state differs")
                    continue
            plan.append((name, slug, parent_slug, row))
    if conflicts:
        raise CommandError("Category conflicts; no changes made:\n" + "\n".join(conflicts))
    return plan


class Command(BaseCommand):
    help = "Preview the agreed category additions. Use --apply only after reviewing the target database and plan."

    def add_arguments(self, parser):
        parser.add_argument("--apply", action="store_true", help="Create missing entries; never modify existing entries.")

    def handle(self, *args, **options):
        try:
            with transaction.atomic():
                existing = list(ProductCategory.objects.select_for_update().order_by("pk"))
                plan = category_plan(existing)
                resolved = {row.slug: row for row in existing}
                additions = 0
                for name, slug, parent_slug, row in plan:
                    self.stdout.write(f"{'KEEP' if row else 'CREATE'} {parent_slug + ' / ' if parent_slug else ''}{name}")
                    if row is None:
                        additions += 1
                        if options["apply"]:
                            row = ProductCategory(name=name, slug=slug, parent=resolved.get(parent_slug), is_active=True)
                            row.full_clean()
                            row.save()
                            resolved[slug] = row
                self.stdout.write(self.style.SUCCESS(
                    f"{'Applied' if options['apply'] else 'Dry run'}: {additions} additions; {len(plan) - additions} unchanged."
                ))
        except (IntegrityError, ValidationError) as exc:
            raise CommandError("Category validation/concurrent conflict; transaction rolled back. Review and rerun.") from exc
