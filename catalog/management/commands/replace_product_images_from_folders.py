"""Swap imported product photos for prepared replacements kept beside the originals.

Each subfolder of --root holds the original photos of one photo-imported product
plus its replacement images. The originals identify the product by the sha256
recorded at staging; the replacements become the product's complete image set.
"""

import hashlib
import json
from io import BytesIO
from pathlib import Path

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.core.files.base import ContentFile
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from PIL import Image

from accounts.models import AdminAuditLog
from catalog.models import PhotoImportImage, PhotoImportItem, Product, ProductStatus
from catalog.photo_import import require_permissions
from catalog.services import (
    log_product_audit,
    mutate_product_images,
    record_product_status_change,
)
from catalog.validators import (
    ALLOWED_IMAGE_EXTENSIONS,
    MAX_IMAGES_PER_PRODUCT,
    MAX_PRODUCT_IMAGE_SIZE_BYTES,
    validate_product_image,
)

NEW_IMAGE_PREFIX = "Gemini_Generated_Image_"
JPEG_QUALITY = 90
DOWNSCALE_STEPS = (None, 2048, 1600, 1280)


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def fit_size_limit(data, name):
    """Return (bytes, name) within the upload limit; re-encode as JPEG when too large."""
    if len(data) <= MAX_PRODUCT_IMAGE_SIZE_BYTES:
        return data, name
    with Image.open(BytesIO(data)) as source:
        image = source.convert("RGBA") if source.mode in ("RGBA", "LA", "P") else source.convert("RGB")
        if image.mode == "RGBA":
            flat = Image.new("RGB", image.size, "white")
            flat.paste(image, mask=image.getchannel("A"))
            image = flat
        for longest in DOWNSCALE_STEPS:
            candidate = image
            if longest and max(image.size) > longest:
                candidate = image.copy()
                candidate.thumbnail((longest, longest), Image.LANCZOS)
            buffer = BytesIO()
            candidate.save(buffer, "JPEG", quality=JPEG_QUALITY, optimize=True)
            if buffer.tell() <= MAX_PRODUCT_IMAGE_SIZE_BYTES:
                return buffer.getvalue(), Path(name).stem + ".jpg"
    raise CommandError(f"{name}: cannot reduce below the product image size limit.")


def split_folder(folder):
    originals, replacements = [], []
    for path in sorted(folder.iterdir()):
        if not path.is_file() or path.suffix.lower() not in ALLOWED_IMAGE_EXTENSIONS:
            continue
        (replacements if path.name.startswith(NEW_IMAGE_PREFIX) else originals).append(path)
    return originals, replacements


def identify_product(folder, originals):
    hashes = {sha256(path.read_bytes()) for path in originals}
    product_ids = set(
        PhotoImportImage.objects.filter(sha256__in=hashes, item__product__isnull=False)
        .values_list("item__product_id", flat=True)
    )
    method = "photo_hash"
    if not product_ids:
        product_ids = set(
            PhotoImportItem.objects.filter(source_key=folder.name, product__isnull=False)
            .values_list("product_id", flat=True)
        )
        method = "source_key"
    return product_ids, method


def prepare_replacements(paths):
    """Drop identical copies, keep the oldest files first, cap at the image limit."""
    seen, unique = set(), []
    for path in sorted(paths, key=lambda p: (p.stat().st_mtime, p.name)):
        data = path.read_bytes()
        digest = sha256(data)
        if digest in seen:
            continue
        seen.add(digest)
        unique.append((path, data))
    prepared = []
    for path, data in unique[:MAX_IMAGES_PER_PRODUCT]:
        data, name = fit_size_limit(data, path.name)
        upload = ContentFile(data, name=name)
        validate_product_image(upload)
        prepared.append({"source": path.name, "name": name, "data": data, "sha256": sha256(data)})
    return prepared, len(unique)


def current_image_hashes(product):
    hashes = []
    for obj in product.images.order_by("sort_order", "pk"):
        with obj.image.open("rb") as stored:
            hashes.append(sha256(stored.read()))
    return hashes


class Command(BaseCommand):
    help = (
        "Replace photo-imported product images with prepared images from per-product "
        "folders. Dry run unless --apply is given."
    )

    def add_arguments(self, parser):
        parser.add_argument("--root", required=True)
        parser.add_argument("--actor", type=int, required=True)
        parser.add_argument("--apply", action="store_true")
        parser.add_argument("--only", default="", help="Comma-separated folder names.")
        parser.add_argument("--report", help="Write the full JSON report to this path.")

    def handle(self, *args, **options):
        actor = get_user_model().objects.get(pk=options["actor"])
        require_permissions(actor, "catalog.change_product", "catalog.approve_product")
        root = Path(options["root"]).resolve()
        if not root.is_dir():
            raise CommandError("--root must be a folder.")
        only = {name.strip() for name in options["only"].split(",") if name.strip()}
        folders = [p for p in sorted(root.iterdir()) if p.is_dir() and (not only or p.name in only)]

        report = []
        for folder in folders:
            row = self.process(folder, actor, apply=options["apply"])
            report.append(row)
            self.stdout.write(json.dumps(row))
        summary = {}
        for row in report:
            summary[row["state"]] = summary.get(row["state"], 0) + 1
        self.stdout.write(json.dumps({"summary": summary, "applied": options["apply"]}))
        if options["report"]:
            Path(options["report"]).write_text(json.dumps(report, indent=2))

    def process(self, folder, actor, *, apply):
        row = {"folder": folder.name}
        originals, replacements = split_folder(folder)
        if not replacements:
            return {**row, "state": "skipped_no_new_images"}
        product_ids, method = identify_product(folder, originals)
        if len(product_ids) != 1:
            state = "unmatched" if not product_ids else "ambiguous"
            return {**row, "state": state, "product_ids": sorted(product_ids)}
        product = Product.objects.select_related("store").get(pk=product_ids.pop())
        try:
            prepared, unique_count = prepare_replacements(replacements)
        except (ValidationError, CommandError) as exc:
            return {**row, "state": "invalid_image", "error": str(exc)}
        row.update(
            match=method,
            product_id=product.pk,
            product_code=product.product_code,
            product_name=product.name,
            store=product.store.name,
            status=product.status,
            old_images=product.images.count(),
            new_images=[p["source"] for p in prepared],
            dropped_over_limit=unique_count - len(prepared),
            compressed=[p["source"] for p in prepared if p["name"] != p["source"]],
        )
        if current_image_hashes(product) == [p["sha256"] for p in prepared]:
            return {**row, "state": "already_replaced"}
        if not apply:
            return {**row, "state": "ready"}
        try:
            self.replace(product, prepared, folder.name, actor)
        except ValidationError as exc:
            return {**row, "state": "failed", "error": "; ".join(exc.messages)}
        product.refresh_from_db()
        return {**row, "state": "replaced", "status": product.status}

    @transaction.atomic
    def replace(self, product, prepared, folder_name, actor):
        was_approved = product.status == ProductStatus.APPROVED
        mutate_product_images(
            mutations={
                product.pk: {
                    "delete_all": True,
                    "add": [
                        {
                            "image": ContentFile(p["data"], name=p["name"]),
                            "sort_order": index,
                            "is_primary": index == 0,
                        }
                        for index, p in enumerate(prepared)
                    ],
                }
            },
            changed_by=actor,
        )
        product.refresh_from_db()
        if was_approved and product.status != ProductStatus.APPROVED:
            record_product_status_change(
                product=product,
                new_status=ProductStatus.APPROVED,
                changed_by=actor,
                reason=f"Re-approved after images were replaced from folder {folder_name}.",
            )
        log_product_audit(
            actor=actor,
            action=AdminAuditLog.Action.PRODUCT_UPDATED,
            description=f"Replaced images of product {product.product_code} from folder {folder_name}.",
            metadata={
                "product_id": product.pk,
                "folder": folder_name,
                "images": [p["source"] for p in prepared],
            },
        )
