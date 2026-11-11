"""Move every current product of one Store into one top-level category.

A one-time management correction: status, approval, prices and stock are left
untouched, so the products stay visible on the shop. Dry run unless --apply.
"""

import json

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.db.models import Count

from accounts.models import AdminAuditLog
from catalog.models import Product, ProductCategory
from catalog.photo_import import require_permissions
from catalog.services import log_product_audit
from stores.models import Store


class Command(BaseCommand):
    help = (
        "Set the category of all existing products of a store. "
        "Dry run unless --apply is given."
    )

    def add_arguments(self, parser):
        parser.add_argument("--store", required=True, help="Exact store name (case-insensitive).")
        parser.add_argument("--category", required=True, help="Top-level category name.")
        parser.add_argument("--actor", type=int, required=True, help="User id of the admin.")
        parser.add_argument("--apply", action="store_true")

    def handle(self, *args, **options):
        try:
            actor = get_user_model().objects.get(pk=options["actor"])
        except get_user_model().DoesNotExist:
            raise CommandError("--actor does not match a user.")
        require_permissions(actor, "catalog.change_product")
        store = self.get_store(options["store"].strip())
        category_name = options["category"].strip()
        if not category_name:
            raise CommandError("--category must not be empty.")
        category = ProductCategory.objects.filter(
            name__iexact=category_name, parent__isnull=True
        ).first()

        products = Product.objects.filter(store=store)
        breakdown = {
            row["category__name"]: row["n"]
            for row in products.values("category__name").annotate(n=Count("id")).order_by("category__name")
        }
        to_move = products.exclude(category=category) if category else products
        report = {
            "store": store.name,
            "store_id": store.pk,
            "category": category.name if category else category_name,
            "category_id": category.pk if category else None,
            "category_exists": category is not None,
            "products_total": products.count(),
            "current_categories": breakdown,
            "to_move": to_move.count(),
            "applied": options["apply"],
        }
        if options["apply"]:
            report["moved"], report["category_id"] = self.apply(
                store, category, category_name, actor
            )
        self.stdout.write(json.dumps(report, indent=2))

    def get_store(self, name):
        stores = list(Store.objects.filter(name__iexact=name))
        if len(stores) != 1:
            raise CommandError(f"Expected exactly one store named {name!r}, found {len(stores)}.")
        return stores[0]

    @transaction.atomic
    def apply(self, store, category, category_name, actor):
        if category is None:
            category = ProductCategory.objects.create(name=category_name)
        locked = list(
            Product.objects.select_for_update()
            .filter(store=store)
            .exclude(category=category)
            .values_list("pk", "category_id")
        )
        if not locked:
            return 0, category.pk
        Product.objects.filter(pk__in=[pk for pk, _ in locked]).update(category=category)
        log_product_audit(
            actor=actor,
            action=AdminAuditLog.Action.PRODUCT_UPDATED,
            description=(
                f"Moved {len(locked)} products of store {store.store_code} "
                f"to category '{category.name}'."
            ),
            metadata={
                "store_id": store.pk,
                "category_id": category.pk,
                "previous_category_by_product": {str(pk): old for pk, old in locked},
            },
        )
        return len(locked), category.pk
