from decimal import Decimal

from django.core.management.base import BaseCommand, CommandError

from catalog.models import Product, ProductStatus
from inventory.status import inventory_today
from stores.models import Store, StoreStatus


def hidden_reasons(product, today):
    """Each public_products_q rule this product fails (read-only diagnosis)."""
    store = product.store
    checks = [
        (product.status != ProductStatus.APPROVED, f"status is {product.status}"),
        (not product.is_active, "product inactive"),
        (product.final_price <= Decimal("0"), "final price is 0"),
        (product.stock_quantity <= Decimal("0"), "out of stock"),
        (not product.category.is_active, "category inactive"),
        (product.expiry_date is not None and product.expiry_date < today, "expired"),
        (store.status != StoreStatus.ACTIVE, f"store status is {store.status}"),
        (not store.is_active, "store inactive"),
    ]
    return [reason for failed, reason in checks if failed]


class Command(BaseCommand):
    help = "List a store's products and why any are hidden from public search. Read-only."

    def add_arguments(self, parser):
        parser.add_argument("--store", required=True, help="Store name or store code")
        parser.add_argument("--hidden-only", action="store_true")

    def handle(self, *args, **options):
        stores = Store.objects.filter(name__iexact=options["store"]) | Store.objects.filter(
            store_code__iexact=options["store"]
        )
        store = stores.first()
        if store is None:
            raise CommandError(f"No store named {options['store']!r}.")
        today = inventory_today()
        products = Product.objects.filter(store=store).select_related("store", "category").order_by("name")
        public = hidden = 0
        for product in products:
            reasons = hidden_reasons(product, today)
            if reasons:
                hidden += 1
                self.stdout.write(f"HIDDEN  {product.product_code}  {product.name}  — {'; '.join(reasons)}")
            else:
                public += 1
                if not options["hidden_only"]:
                    keywords = product.search_keywords or "-"
                    self.stdout.write(f"PUBLIC  {product.product_code}  {product.name}  [keywords: {keywords}]")
        self.stdout.write(f"\n{store.name}: {public} public, {hidden} hidden.")
