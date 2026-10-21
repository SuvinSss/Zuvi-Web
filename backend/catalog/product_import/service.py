"""Preview and commit for bulk product import.

Policy (documented in docs/product-images-and-imports.md)
* Preview never writes products. It stages the uploaded files and reports.
* Commit re-parses the staged files and re-validates against current data.
* Default is all-or-nothing: if any row is invalid, nothing is imported. With
  ``all_or_nothing=False`` valid rows are imported, each in its own savepoint,
  and failed rows are reported; the batch is then labelled "partial".
* The same file content can be committed once; committing a batch twice returns
  the stored result instead of creating duplicates.
"""
import hashlib
import logging

from django.core.exceptions import ValidationError
from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import IntegrityError, transaction
from django.utils import timezone

from catalog.models import Product, ProductImportBatch, ProductStatus
from stores.models import Store
from catalog.services import (
    add_product_image,
    catalogue_field_changed,
    create_product,
    update_product,
)
from catalog.validators import MAX_IMAGES_PER_PRODUCT

from .images import ZipImages, fetch_image_url
from .parser import parse_workbook
from .validator import analyse

logger = logging.getLogger(__name__)


class ImportBlocked(Exception):
    """Commit refused (invalid rows, repeat file, ...). ``code`` maps to the API."""

    def __init__(self, message, code="blocked"):
        super().__init__(message)
        self.code = code


def _stage(batch_id, name, data):
    return default_storage.save(f"imports/{batch_id}/{name}", ContentFile(data))


def _read(path):
    with default_storage.open(path, "rb") as handle:
        return handle.read()


def _discard_staged(batch):
    for path in (batch.workbook_path, batch.images_zip_path):
        if path:
            try:
                default_storage.delete(path)
            except Exception:  # pragma: no cover - cleanup is best effort
                logger.warning("Could not delete staged import file %s", path)
    batch.workbook_path = batch.images_zip_path = ""


def _analyse_batch(batch, workbook_bytes, zip_bytes):
    raw_rows, ignored = parse_workbook(workbook_bytes, batch.source_name)
    return analyse(
        raw_rows, ignored, mode=batch.mode, allow_image_urls=batch.allow_image_urls,
        zip_images=ZipImages(zip_bytes),
    )


def create_preview(*, user, workbook, images_zip=None, mode, all_or_nothing=True,
                   initial_status=ProductStatus.DRAFT, allow_image_urls=False):
    """Stage the files, analyse them and return ``(batch, analysis)``. Writes no products."""
    if mode not in ProductImportBatch.Mode.values:
        raise ValidationError("Unknown import mode.")
    if initial_status not in (ProductStatus.DRAFT, ProductStatus.PENDING):
        raise ValidationError("Imported products can start as Draft or Pending only.")
    workbook_bytes = workbook.read()
    zip_bytes = images_zip.read() if images_zip else b""
    digest = hashlib.sha256(workbook_bytes + b"|" + zip_bytes).hexdigest()
    batch = ProductImportBatch(
        created_by=user, mode=mode, all_or_nothing=all_or_nothing, initial_status=initial_status,
        allow_image_urls=allow_image_urls, source_name=(workbook.name or "")[:255], source_hash=digest,
    )
    analysis = _analyse_batch(batch, workbook_bytes, zip_bytes)  # raises ValidationError for bad files
    batch.workbook_path = _stage(batch.pk, "workbook", workbook_bytes)
    if zip_bytes:
        batch.images_zip_path = _stage(batch.pk, "images.zip", zip_bytes)
    _record_counts(batch, analysis)
    batch.save()
    return batch, analysis


def _record_counts(batch, analysis):
    counts = analysis.counts
    batch.total_rows, batch.valid_rows = counts["total"], counts["valid"]
    batch.invalid_rows, batch.duplicate_rows = counts["invalid"], counts["duplicates"]
    batch.errors = analysis.error_list()


def already_imported(batch):
    return (
        ProductImportBatch.objects.filter(source_hash=batch.source_hash, status=ProductImportBatch.Status.COMMITTED)
        .exclude(pk=batch.pk).exists()
    )


def reanalyse(batch):
    if not batch.workbook_path:
        raise ImportBlocked("The staged files for this import are no longer available. Upload the file again.", "expired")
    zip_bytes = _read(batch.images_zip_path) if batch.images_zip_path else b""
    return _analyse_batch(batch, _read(batch.workbook_path), zip_bytes)


def commit(batch_id, *, user, request=None):
    """Apply a previewed import. Returns the committed batch.

    Raises ``ImportBlocked`` when nothing was (or could be) imported.
    """
    try:
        return _commit(batch_id, user=user, request=request)
    except _RolledBack as exc:
        mark_failed(batch_id, exc.failure)
        raise ImportBlocked(
            f"Import rolled back, nothing was saved. Row {exc.failure['row']}: {exc.failure['message']}", "rolled_back"
        ) from exc


class _RolledBack(Exception):
    def __init__(self, failure):
        super().__init__(failure["message"])
        self.failure = failure


def _commit(batch_id, *, user, request):
    with transaction.atomic():
        batch = ProductImportBatch.objects.select_for_update().get(pk=batch_id)
        if batch.status == ProductImportBatch.Status.COMMITTED:
            return batch  # idempotent: a double submit must not import twice
        if already_imported(batch):
            raise ImportBlocked("This file has already been imported. Change the data before importing it again.", "already_imported")
        analysis = reanalyse(batch)
        counts = analysis.counts
        if counts["total"] == 0:
            raise ImportBlocked("The file contains no product rows.", "empty")
        if batch.all_or_nothing and counts["invalid"]:
            raise ImportBlocked(
                f"{counts['invalid']} row(s) have errors. Fix them, or choose to import valid rows only.", "invalid_rows"
            )
        zip_images = ZipImages(_read(batch.images_zip_path) if batch.images_zip_path else b"")
        summary = {"created": 0, "updated": 0, "skipped": 0, "images_processed": 0, "fallback_images": 0}
        failures = []
        stores = {}
        for row in analysis.rows:
            if not row.valid:
                continue
            try:
                delta = dict.fromkeys(summary, 0)  # counted only if the whole row commits
                with transaction.atomic():  # row savepoint: one bad row never taints another
                    _apply_row(row, batch, user, zip_images, delta, request, stores)
                for key, value in delta.items():
                    summary[key] += value
            except Exception as exc:  # reported per row; never swallowed into "success"
                if not isinstance(exc, (ValidationError, IntegrityError)):
                    logger.exception("Product import row %s failed", row.number)
                failure = {"row": row.number, "column": "", "sku": row.sku, "message": _message(exc)}
                if batch.all_or_nothing:
                    raise _RolledBack(failure) from exc
                failures.append(failure)
        invalid = counts["invalid"]
        summary["failed"] = invalid + len(failures)
        summary["outcome"] = "complete" if not summary["failed"] else "partial"
        _record_counts(batch, analysis)
        batch.errors = analysis.error_list() + failures
        batch.summary = summary
        did_something = summary["created"] + summary["updated"] + summary["skipped"]
        batch.status = (
            ProductImportBatch.Status.FAILED if summary["failed"] and not did_something
            else ProductImportBatch.Status.COMMITTED
        )
        batch.committed_at = timezone.now()
        _discard_staged(batch)  # do not keep uploaded spreadsheets around
        batch.save()
        return batch


def mark_failed(batch_id, failure):
    ProductImportBatch.objects.filter(pk=batch_id).update(
        status=ProductImportBatch.Status.FAILED,
        errors=[failure],
        summary={"outcome": "rolled_back", "created": 0, "updated": 0, "skipped": 0, "failed": 1,
                 "images_processed": 0, "fallback_images": 0},
    )


def _message(exc):
    if isinstance(exc, ValidationError):
        return "; ".join(exc.messages)
    if isinstance(exc, IntegrityError):
        return "A product with the same unique values already exists."
    return "The row could not be saved (see the server log)."


def _image_upload(row, zip_images):
    if row.image == "zip":
        data, name = zip_images.read(row.image_ref), row.image_ref
    else:
        data, name = fetch_image_url(row.image_ref), "download"
    return SimpleUploadedFile(name, data)


def _apply_row(row, batch, user, zip_images, summary, request, stores):
    if row.action == "skip":
        summary["skipped"] += 1
        return
    product_data = _product_data(row.data)
    if row.action == "create":
        store = stores.get(row.store_id) or stores.setdefault(row.store_id, Store.objects.get(pk=row.store_id))
        product = create_product(
            store=store, product_data=product_data, created_by=user, tag_ids=row.tag_ids,
            initial_status=batch.initial_status, request=request,
        )
        summary["created"] += 1
    else:
        product = Product.objects.get(pk=row.existing_id)
        changed = any(catalogue_field_changed(product, k, v) for k, v in product_data.items()) or (
            bool(row.tag_ids) and set(product.tags.values_list("pk", flat=True)) != set(row.tag_ids)
        )
        if changed:
            update_product(product=product, product_data=product_data, updated_by=user,
                           tag_ids=row.tag_ids or None, request=request)
            summary["updated"] += 1
        else:
            summary["skipped"] += 1
    if row.image == "none":
        if not product.images.exists():
            summary["fallback_images"] += 1
        return
    if product.images.count() >= MAX_IMAGES_PER_PRODUCT:
        raise ValidationError(f"Product already has {MAX_IMAGES_PER_PRODUCT} images.")
    add_product_image(product=product, image=_image_upload(row, zip_images), alt_text=row.image_alt,
                      changed_by=user, request=request)
    summary["images_processed"] += 1


def _product_data(data):
    keep = {"sku", "name", "description", "category", "brand", "store_price", "unit", "unit_value",
            "low_stock_threshold", "manufacturing_date", "expiry_date"}
    return {k: v for k, v in data.items() if k in keep and v is not None}
