import uuid
from pathlib import PurePosixPath

from django.core.exceptions import ValidationError
from django.core.files.images import get_image_dimensions

ALLOWED_IMAGE_EXTENSIONS = frozenset({".jpg", ".jpeg", ".png", ".webp"})
ALLOWED_IMAGE_FORMATS = frozenset({"JPEG", "PNG", "WEBP"})
MAX_PRODUCT_IMAGE_SIZE_BYTES = 5 * 1024 * 1024  # 5 MB
MAX_IMAGES_PER_PRODUCT = 5


def product_image_upload_to(instance, filename):
    """
    Build a collision-safe, path-traversal-safe media path for product images.

    User-supplied path segments are discarded; only a sanitized extension is kept.
    """
    extension = PurePosixPath(filename or "").suffix.lower()
    if extension not in ALLOWED_IMAGE_EXTENSIONS:
        extension = ".jpg"
    return f"products/images/{uuid.uuid4().hex}{extension}"


def _detect_image_format(file_obj):
    """Return the Pillow format name using file contents, not the filename."""
    try:
        from PIL import Image, UnidentifiedImageError
    except ImportError as exc:  # pragma: no cover - Pillow is a project dependency
        raise ValidationError("Image validation is unavailable.") from exc

    position = file_obj.tell() if hasattr(file_obj, "tell") else None
    try:
        file_obj.seek(0)
        with Image.open(file_obj) as image:
            image.verify()
        file_obj.seek(0)
        with Image.open(file_obj) as image:
            return (image.format or "").upper()
    except (OSError, SyntaxError, UnidentifiedImageError, ValueError):
        return None
    finally:
        if position is not None and hasattr(file_obj, "seek"):
            file_obj.seek(position)


def validate_product_image(value):
    """
    Validate product images by size, declared extension, and actual file contents.

    Browser-provided content types and extensions alone are not trusted.
    """
    if not value:
        return

    size = getattr(value, "size", None)
    if size is not None and size > MAX_PRODUCT_IMAGE_SIZE_BYTES:
        raise ValidationError("Product image must be 5 MB or smaller.")

    name = getattr(value, "name", "") or ""
    extension = PurePosixPath(name).suffix.lower()
    if extension not in ALLOWED_IMAGE_EXTENSIONS:
        raise ValidationError(
            "Product image must use a .jpg, .jpeg, .png, or .webp extension."
        )

    file_obj = getattr(value, "file", value)
    detected_format = _detect_image_format(file_obj)
    if detected_format not in ALLOWED_IMAGE_FORMATS:
        raise ValidationError(
            "Product image content must be a valid JPEG, PNG, or WebP file."
        )

    expected_extensions = {
        "JPEG": {".jpg", ".jpeg"},
        "PNG": {".png"},
        "WEBP": {".webp"},
    }
    if extension not in expected_extensions[detected_format]:
        raise ValidationError(
            "Product image extension does not match the actual image format."
        )

    try:
        get_image_dimensions(value)
    except Exception as exc:
        raise ValidationError(
            "Product image content must be a valid JPEG, PNG, or WebP file."
        ) from exc
