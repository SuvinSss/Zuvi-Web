"""Resume a reviewed website batch from the command line using the same checks."""

import json
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from catalog.models import PhotoImportBatch
from catalog.photo_import import import_item, require_permissions


class Command(BaseCommand):
    help = "Dry-run or import a reviewed photo batch; defaults to dry-run."

    def add_arguments(self, parser):
        parser.add_argument("--batch", type=int, required=True)
        parser.add_argument("--actor", type=int, required=True)
        parser.add_argument("--apply", action="store_true")
        parser.add_argument("--publish", action="store_true")

    def handle(self, *args, **options):
        actor = get_user_model().objects.get(pk=options["actor"])
        require_permissions(
            actor, "catalog.add_product", "catalog.manage_product_pricing"
        )
        batch = PhotoImportBatch.objects.get(pk=options["batch"])
        failed = 0
        for item in batch.items.all():
            try:
                result = import_item(
                    item_id=item.pk,
                    actor=actor,
                    publish=options["publish"],
                    dry_run=not options["apply"],
                )
            except Exception as exc:
                from django.core.exceptions import ValidationError, PermissionDenied

                if not isinstance(exc, (ValidationError, PermissionDenied)):
                    raise
                result = {"state": "blocked", "error": str(exc)}
                failed += 1
            self.stdout.write(json.dumps({"source_key": item.source_key, **result}))
        if failed:
            raise CommandError(
                f"{failed} items need review. Other eligible items were processed."
            )
