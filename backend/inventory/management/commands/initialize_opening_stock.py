from django.core.management.base import BaseCommand

from inventory.services import initialize_opening_stock_from_catalogue


class Command(BaseCommand):
    help = (
        "Idempotently create OPENING InventoryTransaction rows for products "
        "that already have a positive stock_quantity and no inventory history. "
        "Never changes Product.stock_quantity."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="List candidate products without writing any transactions.",
        )

    def handle(self, *args, **options):
        dry_run = options["dry_run"]
        result = initialize_opening_stock_from_catalogue(dry_run=dry_run)

        if dry_run:
            self.stdout.write(
                self.style.WARNING(
                    f"Dry run: {result['candidate_count']} product(s) would "
                    "receive an OPENING transaction."
                )
            )
            for product_id in result["product_ids"]:
                self.stdout.write(f"  - product_id={product_id}")
            return

        self.stdout.write(
            self.style.SUCCESS(
                f"Initialized OPENING stock for {result['converted']} product(s). "
                "Product.stock_quantity values were not changed."
            )
        )
        if result["converted"] == 0:
            self.stdout.write("Nothing to do (already initialized or zero stock).")
