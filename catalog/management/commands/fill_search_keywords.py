from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from catalog.models import Product
from catalog.search_synonyms import keywords_for_name
from stores.models import Store


class Command(BaseCommand):
    help = (
        "Add English / Manglish / Malayalam synonyms to Product.search_keywords "
        "from the built-in dictionary. Existing keywords are kept."
    )

    def add_arguments(self, parser):
        parser.add_argument("--store", help="Store name or store code (default: all stores)")
        parser.add_argument("--dry-run", action="store_true")
        parser.add_argument("--overwrite", action="store_true", help="Replace existing keywords")

    def handle(self, *args, **options):
        products = Product.objects.order_by("store_id", "name")
        if options["store"]:
            store = (
                Store.objects.filter(name__iexact=options["store"])
                | Store.objects.filter(store_code__iexact=options["store"])
            ).first()
            if store is None:
                raise CommandError(f"No store named {options['store']!r}.")
            products = products.filter(store=store)

        updated, unmatched = 0, []
        with transaction.atomic():
            for product in products.select_for_update():
                existing = "" if options["overwrite"] else product.search_keywords.strip()
                added = keywords_for_name(product.name, existing=existing)
                if not added:
                    if not existing:
                        unmatched.append(product)
                    continue
                keywords = ", ".join(part for part in (existing, added) if part)
                self.stdout.write(f"{product.product_code}  {product.name}  -> {keywords}")
                if keywords != product.search_keywords:
                    updated += 1
                    if not options["dry_run"]:
                        product.search_keywords = keywords
                        product.save(update_fields=["search_keywords"])

        if unmatched:
            self.stdout.write("\nNo dictionary match — add keywords by hand on the product edit page:")
            for product in unmatched:
                self.stdout.write(f"  {product.product_code}  {product.name}")
        verb = "Would update" if options["dry_run"] else "Updated"
        self.stdout.write(f"\n{verb} {updated} products; {len(unmatched)} need manual keywords.")
