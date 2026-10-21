from django.conf import settings

DEFAULTS = {
    "MAX_FILE_BYTES": 5 * 1024 * 1024,
    "MAX_ROWS": 1000,
    "MAX_UNCOMPRESSED_BYTES": 50 * 1024 * 1024,  # xlsx container, decompression-bomb guard
    "ZIP_MAX_BYTES": 50 * 1024 * 1024,
    "ZIP_MAX_FILES": 500,
    "ZIP_MAX_UNCOMPRESSED_BYTES": 200 * 1024 * 1024,
    "URL_TIMEOUT": 5,
}


def limit(name):
    return getattr(settings, f"PRODUCT_IMPORT_{name}", DEFAULTS[name])
