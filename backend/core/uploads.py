"""Validation for sensitive uploads: delivery evidence, ticket/complaint attachments.

Content is checked by decoding (images) or by magic bytes (PDF), never by file
name or the client-supplied content type. Images are normalised by the shared
image pipeline (EXIF orientation applied, metadata including GPS removed,
re-encoded); coordinates for evidence are recorded explicitly in the database.
"""
import hashlib
import uuid
from dataclasses import dataclass

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.files.base import ContentFile

from catalog.image_pipeline import prepare_upload

PDF_MAGIC = b"%PDF-"
CONTENT_TYPES = {".jpg": "image/jpeg", ".png": "image/png", ".webp": "image/webp", ".pdf": "application/pdf"}


def max_bytes() -> int:
    return getattr(settings, "EVIDENCE_MAX_BYTES", 5 * 1024 * 1024)


@dataclass(frozen=True)
class CleanUpload:
    file: ContentFile
    content_type: str
    size: int
    sha256: str
    width: int | None = None
    height: int | None = None


def clean_image(upload) -> CleanUpload:
    try:
        processed = prepare_upload(upload)
    except ValidationError as exc:
        messages = [str(m).replace("Product images", "Images").replace("Product image", "Image") for m in exc.messages]
        raise ValidationError(messages) from None
    ext = {"JPEG": ".jpg", "PNG": ".png", "WEBP": ".webp"}[processed.format]
    named = ContentFile(processed.file.read(), name=f"{uuid.uuid4().hex}{ext}")
    return CleanUpload(named, CONTENT_TYPES[ext], processed.size, processed.sha256, processed.width, processed.height)


def clean_document(upload) -> CleanUpload:
    """Accept an image or a PDF."""
    size = getattr(upload, "size", None)
    if size is not None and size > max_bytes():
        raise ValidationError(f"File must be {max_bytes() // (1024 * 1024)} MB or smaller.")
    upload.seek(0)
    head = upload.read(8)
    upload.seek(0)
    if head.startswith(PDF_MAGIC):
        data = upload.read(max_bytes() + 1)
        if len(data) > max_bytes():
            raise ValidationError(f"File must be {max_bytes() // (1024 * 1024)} MB or smaller.")
        return CleanUpload(ContentFile(data, name=f"{uuid.uuid4().hex}.pdf"), "application/pdf", len(data),
                           hashlib.sha256(data).hexdigest())
    try:
        return clean_image(upload)
    except ValidationError:
        raise ValidationError("Upload a JPEG, PNG, WebP image or a PDF document.") from None
