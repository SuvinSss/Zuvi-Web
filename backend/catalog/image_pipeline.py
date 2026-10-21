"""One image pipeline for every way a product image enters Zuvi.

Manual uploads (Django forms and the REST API), Excel/ZIP imports and URL
imports all go through ``prepare_upload``; ``ProductImage.save`` then derives the
display image and the WebP thumbnail. Keeping the rules here means limits,
metadata stripping and cropping behave identically everywhere.

Design decisions
* Content is verified with Pillow, never by filename or MIME type.
* The stored "original" is re-encoded: EXIF orientation applied, all metadata
  (including GPS) dropped, longest side capped. We do not keep the raw upload.
* Thumbnails *contain* the product on a neutral square canvas. They never crop,
  so labels and edges of packaging are not cut off, and never upscale.
* Output is deterministic, so the SHA-256 of the processed bytes is a safe key
  for de-duplicating storage.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass
from io import BytesIO

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.files.base import ContentFile
from PIL import Image, ImageOps, UnidentifiedImageError

DEFAULTS = {
    "MAX_BYTES": 5 * 1024 * 1024,
    "MAX_PIXELS": 25_000_000,
    "MAX_DIMENSION": 2400,  # longest side of the stored original
    "THUMBNAIL_SIZE": 400,
    "THUMBNAIL_QUALITY": 80,
    "JPEG_QUALITY": 88,
    "WEBP_QUALITY": 88,
    "BACKGROUND": "#F8FAFC",
}
# AVIF is deliberately not accepted: Pillow only reads it with an optional plugin.
ALLOWED_FORMATS = ("JPEG", "PNG", "WEBP")
_EXTENSIONS = {"JPEG": ".jpg", "PNG": ".png", "WEBP": ".webp"}


def setting(name):
    return getattr(settings, f"PRODUCT_IMAGE_{name}", DEFAULTS[name])


@dataclass(frozen=True)
class ProcessedUpload:
    file: ContentFile
    format: str
    width: int
    height: int
    size: int
    sha256: str


def is_fresh_upload(value) -> bool:
    """True for a file that has not been stored yet (an upload, not a FieldFile)."""
    return bool(value) and not getattr(value, "_committed", False) and hasattr(value, "read")


def _read_limited(source) -> bytes:
    limit = setting("MAX_BYTES")
    size = getattr(source, "size", None)
    if size is not None and size > limit:
        raise ValidationError(f"Product image must be {limit // (1024 * 1024)} MB or smaller.")
    source.seek(0)
    data = source.read(limit + 1)
    source.seek(0)
    if len(data) > limit:
        raise ValidationError(f"Product image must be {limit // (1024 * 1024)} MB or smaller.")
    if not data:
        raise ValidationError("The image file is empty.")
    return data


def prepare_upload(source) -> ProcessedUpload:
    """Validate and normalise one uploaded image; raises ``ValidationError``."""
    data = _read_limited(source)
    try:
        with Image.open(BytesIO(data), formats=ALLOWED_FORMATS) as probe:
            fmt = probe.format
            # Header-only check first: refuse decompression bombs before decoding.
            if probe.width * probe.height > setting("MAX_PIXELS"):
                raise ValidationError(
                    f"Product images must contain at most {setting('MAX_PIXELS') // 1_000_000} megapixels."
                )
            probe.verify()
        with Image.open(BytesIO(data), formats=ALLOWED_FORMATS) as image:
            image.load()
            image = ImageOps.exif_transpose(image)
            image = _normalise_mode(image, fmt)
            image.thumbnail((setting("MAX_DIMENSION"),) * 2, Image.Resampling.LANCZOS)
            out = BytesIO()
            # Saving without exif/icc/info drops location and camera metadata.
            if fmt == "JPEG":
                image.save(out, "JPEG", quality=setting("JPEG_QUALITY"), optimize=True, progressive=True)
            elif fmt == "PNG":
                image.save(out, "PNG", optimize=True)
            else:
                image.save(out, "WEBP", quality=setting("WEBP_QUALITY"), method=4)
            width, height = image.size
    except ValidationError:
        raise
    except (UnidentifiedImageError, OSError, SyntaxError, ValueError, Image.DecompressionBombError):
        raise ValidationError("Product image content must be a valid JPEG, PNG, or WebP file.") from None
    payload = out.getvalue()
    digest = hashlib.sha256(payload)
    processed = ContentFile(payload, name=f"upload{_EXTENSIONS[fmt]}")
    # Forms flag "remove plain white background" on the upload object.
    if getattr(source, "remove_plain_background", False) or getattr(
        getattr(source, "file", None), "remove_plain_background", False
    ):
        processed.file.remove_plain_background = True
        digest.update(b"|remove-background")
    return ProcessedUpload(processed, fmt, width, height, len(payload), digest.hexdigest())


def _normalise_mode(image: Image.Image, fmt: str) -> Image.Image:
    has_alpha = image.mode in ("RGBA", "LA") or (image.mode == "P" and "transparency" in image.info)
    if fmt == "JPEG" or not has_alpha:
        return image.convert("RGB")
    return image.convert("RGBA")


def make_thumbnail(source) -> ContentFile:
    """Square WebP thumbnail: product contained (never cropped or upscaled)."""
    size = setting("THUMBNAIL_SIZE")
    source.seek(0)
    try:
        with Image.open(source) as original:
            image = ImageOps.exif_transpose(original).convert("RGBA")
    finally:
        source.seek(0)
    image.thumbnail((size, size), Image.Resampling.LANCZOS)  # shrink only
    canvas = Image.new("RGBA", (size, size), setting("BACKGROUND"))
    canvas.alpha_composite(image, ((size - image.width) // 2, (size - image.height) // 2))
    out = BytesIO()
    canvas.convert("RGB").save(out, "WEBP", quality=setting("THUMBNAIL_QUALITY"), method=4)
    return ContentFile(out.getvalue(), name="thumbnail.webp")


def describe_upload(source):
    """(sha256, width, height, size) for an image that skipped ``prepare_upload``."""
    source.seek(0)
    try:
        data = source.read()
        with Image.open(BytesIO(data)) as image:
            width, height = image.size
    finally:
        source.seek(0)
    return hashlib.sha256(data).hexdigest(), width, height, len(data)
