"""Image sources for bulk import: a ZIP held in memory, or SSRF-guarded URLs.

The ZIP is never extracted to disk, so path traversal has nothing to act on;
entries are still validated by name, type and size, and totals are capped.
"""
import ipaddress
import socket
import zipfile
from io import BytesIO
from pathlib import PurePosixPath
from urllib.parse import urlsplit

import requests
from django.core.exceptions import ValidationError

from catalog.image_pipeline import setting as image_setting
from catalog.validators import ALLOWED_IMAGE_EXTENSIONS

from .limits import limit

IGNORED = {".ds_store", "thumbs.db"}


class ZipImages:
    """Validated, in-memory index of the images in an uploaded ZIP."""

    def __init__(self, data: bytes | None):
        self._entries = {}
        self._archive = None
        if not data:
            return
        if len(data) > limit("ZIP_MAX_BYTES"):
            raise ValidationError(f"The images ZIP must be {limit('ZIP_MAX_BYTES') // (1024 * 1024)} MB or smaller.")
        try:
            self._archive = zipfile.ZipFile(BytesIO(data))
        except zipfile.BadZipFile:
            raise ValidationError("The images file is not a valid ZIP archive.") from None
        files, total = 0, 0
        for info in self._archive.infolist():
            if info.is_dir() or info.filename.startswith("__MACOSX/"):
                continue
            path = PurePosixPath(info.filename.replace("\\", "/"))
            if path.name.lower() in IGNORED:
                continue
            if path.is_absolute() or ".." in path.parts or info.filename.startswith(("/", "\\")):
                raise ValidationError(f"Unsafe path in ZIP: {info.filename!r}.")
            if (info.external_attr >> 16) & 0o170000 == 0o120000:
                raise ValidationError(f"Symbolic links are not allowed in the ZIP: {info.filename!r}.")
            if info.flag_bits & 0x1:
                raise ValidationError("Encrypted ZIP files are not supported.")
            if path.suffix.lower() not in ALLOWED_IMAGE_EXTENSIONS:
                raise ValidationError(f"Unsupported file in ZIP: {info.filename!r}. Only JPEG, PNG and WebP images are allowed.")
            if info.file_size > image_setting("MAX_BYTES"):
                raise ValidationError(f"{info.filename!r} is larger than {image_setting('MAX_BYTES') // (1024 * 1024)} MB.")
            files += 1
            total += info.file_size
            if files > limit("ZIP_MAX_FILES") or total > limit("ZIP_MAX_UNCOMPRESSED_BYTES"):
                raise ValidationError("The images ZIP contains too many files or is too large when unpacked.")
            key = path.name.lower()
            if key in self._entries:
                raise ValidationError(f"Duplicate image file name in ZIP: {path.name!r}.")
            self._entries[key] = info

    def __contains__(self, name):
        return (name or "").strip().lower() in self._entries

    def read(self, name) -> bytes:
        info = self._entries[(name or "").strip().lower()]
        # Re-check against the real stream, not only the declared size.
        with self._archive.open(info) as handle:
            data = handle.read(image_setting("MAX_BYTES") + 1)
        if len(data) > image_setting("MAX_BYTES"):
            raise ValidationError("Image is too large.")
        return data


def _is_public_ip(value: str) -> bool:
    address = ipaddress.ip_address(value)
    return address.is_global and not address.is_multicast


def validate_image_url(url: str) -> str:
    """Syntax and DNS check; used at preview time and again before fetching."""
    parts = urlsplit((url or "").strip())
    if parts.scheme not in {"http", "https"} or not parts.hostname:
        raise ValidationError("Image URL must start with http:// or https://.")
    if parts.username or parts.password:
        raise ValidationError("Image URL must not contain credentials.")
    try:
        infos = socket.getaddrinfo(parts.hostname, parts.port or (443 if parts.scheme == "https" else 80), type=socket.SOCK_STREAM)
    except OSError:
        raise ValidationError("Image URL host could not be resolved.") from None
    if not infos or not all(_is_public_ip(info[4][0]) for info in infos):
        raise ValidationError("Image URL must point to a public internet address.")
    return parts.geturl()


def fetch_image_url(url: str) -> bytes:
    """Download an image: no redirects, short timeout, size cap, public peers only."""
    url = validate_image_url(url)
    limit_bytes = image_setting("MAX_BYTES")
    try:
        with requests.get(url, stream=True, timeout=limit("URL_TIMEOUT"), allow_redirects=False,
                          headers={"User-Agent": "ZuviImporter/1.0"}) as response:
            if response.status_code != 200:
                raise ValidationError(f"Image URL returned HTTP {response.status_code}.")
            # DNS may have changed since validation: verify who we actually connected to.
            peer = _peer_address(response)
            if peer is None or not _is_public_ip(peer):
                raise ValidationError("Image URL must point to a public internet address.")
            declared = response.headers.get("Content-Length")
            if declared and declared.isdigit() and int(declared) > limit_bytes:
                raise ValidationError("Image URL file is too large.")
            data = b""
            for chunk in response.iter_content(64 * 1024):
                data += chunk
                if len(data) > limit_bytes:
                    raise ValidationError("Image URL file is too large.")
    except requests.RequestException:
        raise ValidationError("Image URL could not be downloaded.") from None
    return data


def _peer_address(response):
    try:
        sock = response.raw._connection.sock
        return sock.getpeername()[0]
    except Exception:
        return None  # fail closed
