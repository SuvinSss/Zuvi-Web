"""Create thumbnails and image facts for photos uploaded before the image pipeline existed.

Safe to re-run; originals are never modified or deleted. Dry-run by default.
"""
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from catalog.image_pipeline import describe_upload, make_thumbnail
from catalog.models import Product, ProductImage


class Command(BaseCommand):
    help = "Generate missing WebP thumbnails (and width/height/hash) for existing product photos. Dry-run unless --apply."

    def add_arguments(self, parser):
        parser.add_argument("--apply", action="store_true", help="Write changes (default is a dry run).")
        parser.add_argument("--limit", type=int, default=200, help="Max photos per run (default 200).")

    def handle(self, *args, **options):
        if options["limit"] < 1:
            raise CommandError("--limit must be positive")
        pending = ProductImage.objects.filter(thumbnail="").order_by("pk")
        total = pending.count()
        rows = list(pending.values_list("pk", "product_id")[: options["limit"]])
        if not options["apply"]:
            self.stdout.write(f"Dry run: {total} photo(s) lack a thumbnail; would process {len(rows)}. Use --apply.")
            return
        done = failed = 0
        for image_id, product_id in rows:
            try:
                with transaction.atomic():
                    # Same parent lock the image services use, so we never race a replace/delete.
                    Product.objects.select_for_update().get(pk=product_id)
                    image = ProductImage.objects.filter(pk=image_id, thumbnail="").first()
                    if image is None or not image.image:
                        continue
                    image.image.open("rb")
                    try:
                        image.thumbnail.save("thumbnail.webp", make_thumbnail(image.image), save=False)
                        fields = ["thumbnail"]
                        if not image.content_hash:
                            image.content_hash, image.width, image.height, image.file_size = describe_upload(image.image)
                            fields += ["content_hash", "width", "height", "file_size"]
                        image.save(update_fields=fields)
                        done += 1
                    finally:
                        image.image.close()
            except Exception as exc:  # one bad/missing file must not stop the run
                failed += 1
                self.stderr.write(f"image {image_id}: {type(exc).__name__}: {exc}")
        self.stdout.write(f"Created {done} thumbnail(s); {failed} failed; {max(total - done, 0)} remaining. Originals preserved.")
