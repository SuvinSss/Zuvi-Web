"""Find (and optionally delete) stored product image files that no database row references.

Deleting a product or photo never deletes files (so rollbacks and duplicates stay safe); this is the
deliberate, separate clean-up. Dry-run by default, and only files older than --older-than-hours are
considered so an in-flight upload is never touched.
"""
import time

from django.core.files.storage import default_storage
from django.core.management.base import BaseCommand, CommandError

from catalog.models import ProductImage

ROOT = "products/images"


def walk(storage, path):
    try:
        dirs, files = storage.listdir(path)
    except (FileNotFoundError, NotImplementedError):
        return
    for name in files:
        yield f"{path}/{name}"
    for name in dirs:
        yield from walk(storage, f"{path}/{name}")


class Command(BaseCommand):
    help = "List unreferenced product image files. Add --delete to remove them (never run without a backup)."

    def add_arguments(self, parser):
        parser.add_argument("--delete", action="store_true", help="Actually delete (default is a dry run).")
        parser.add_argument("--older-than-hours", type=float, default=24.0)

    def handle(self, *args, **options):
        if options["older_than_hours"] < 1:
            raise CommandError("--older-than-hours must be at least 1")
        referenced = set()
        for fields in ProductImage.objects.values_list("image", "display_image", "thumbnail"):
            referenced.update(name for name in fields if name)
        cutoff = time.time() - options["older_than_hours"] * 3600
        orphans = []
        for name in walk(default_storage, ROOT):
            if name in referenced:
                continue
            try:
                modified = default_storage.get_modified_time(name).timestamp()
            except (NotImplementedError, OSError):
                continue  # cannot prove it is old: leave it
            if modified < cutoff:
                orphans.append(name)
        for name in orphans:
            self.stdout.write(("DELETE " if options["delete"] else "orphan ") + name)
            if options["delete"]:
                default_storage.delete(name)
        verb = "Deleted" if options["delete"] else "Found (dry run, nothing deleted)"
        self.stdout.write(f"{verb}: {len(orphans)} unreferenced file(s); {len(referenced)} referenced.")
