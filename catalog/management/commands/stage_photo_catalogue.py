"""Load a prepared local catalogue into the same review workspace as web uploads."""

import hashlib
import json
from pathlib import Path
from uuid import uuid4

from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied
from django.core.files import File
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from catalog.models import (
    PhotoImportBatch,
    PhotoImportItem,
    PhotoImportImage,
    ProductCategory,
    Brand,
)
from catalog.photo_import import require_permissions
from catalog.validators import validate_product_image


class Command(BaseCommand):
    help = "Stage photos and research for website review. Does not publish or change stock."

    def add_arguments(self, parser):
        parser.add_argument("--catalogue", required=True)
        parser.add_argument("--photo-root", required=True)
        parser.add_argument("--actor", type=int, required=True)
        parser.add_argument("--name", default="ZuuVi local photo catalogue")
        parser.add_argument("--batch", type=int)
        parser.add_argument("--apply", action="store_true")
        parser.add_argument("--create-taxonomy", action="store_true")

    def handle(self, *args, **options):
        actor = get_user_model().objects.get(pk=options["actor"])
        require_permissions(actor, "catalog.add_product")
        root = Path(options["photo_root"]).resolve()
        rows = json.loads(Path(options["catalogue"]).read_text())["items"]
        batch = None
        if options["batch"]:
            batch = PhotoImportBatch.objects.get(pk=options["batch"])
            if batch.created_by_id != actor.pk and not actor.is_superuser:
                raise PermissionDenied("Batch belongs to another administrator.")
        elif options["apply"]:
            batch, _ = PhotoImportBatch.objects.get_or_create(
                name=options["name"], created_by=actor
            )
        for row in rows:
            if len(row["photos"]) > 30:
                raise CommandError(
                    f"Split {row['source_key']}: maximum 30 staging photos per group."
                )
            paths = []
            for entry in row["photos"]:
                path = (root / entry["path"]).resolve()
                if not path.is_relative_to(root) or not path.is_file():
                    raise CommandError("Photo path must be a file inside --photo-root.")
                with path.open("rb") as source:
                    validate_product_image(File(source, name=path.name))
                paths.append((entry, path))
            if not options["apply"]:
                self.stdout.write(
                    json.dumps(
                        {
                            "source_key": row["source_key"],
                            "state": "ready_to_stage",
                            "photos": len(paths),
                        }
                    )
                )
                continue
            with transaction.atomic():
                PhotoImportBatch.objects.select_for_update().get(pk=batch.pk)
                item, created = PhotoImportItem.objects.get_or_create(
                    batch=batch,
                    source_key=row["source_key"],
                    defaults={
                        "source_hash": row["source_hash"],
                        "details": row["details"],
                    },
                )
                if item.source_hash != row["source_hash"]:
                    raise CommandError(
                        "Source fingerprint changed; create a separate batch."
                    )
                if item.product_id:
                    continue
                if created:
                    details = dict(row["details"])
                    for field, model, permission in [
                        ("category", ProductCategory, "catalog.add_productcategory"),
                        ("brand", Brand, "catalog.add_brand"),
                    ]:
                        name = row.get(field + "_name")
                        if name:
                            obj = model.objects.filter(
                                name=name, is_active=True
                            ).first()
                            if obj is None and options["create_taxonomy"]:
                                require_permissions(actor, permission)
                                obj = model(name=name)
                                obj.full_clean()
                                obj.save()
                            details[field] = obj.pk if obj else ""
                    item.details = details
                    item.save(update_fields=["details", "updated_at"])
                for entry, path in paths:
                    digest = hashlib.sha256(path.read_bytes()).hexdigest()
                    if item.photos.filter(sha256=digest).exists():
                        continue
                    with path.open("rb") as source:
                        photo = PhotoImportImage(
                            item=item,
                            image=File(source, name=uuid4().hex + path.suffix.lower()),
                            sha256=digest,
                            original_name=path.name,
                            selected=entry.get("selected", False),
                        )
                        photo.full_clean()
                        photo.save()
                self.stdout.write(
                    json.dumps(
                        {
                            "source_key": row["source_key"],
                            "item_id": item.pk,
                            "state": "staged",
                            "photos": item.photos.count(),
                        }
                    )
                )
        if batch:
            self.stdout.write(
                json.dumps(
                    {
                        "batch_id": batch.pk,
                        "review_url": "/management/products/photo-import/",
                    }
                )
            )
