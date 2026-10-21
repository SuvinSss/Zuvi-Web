"""Streaming of private files after an authorization check by the caller."""
import mimetypes
import os

from django.http import FileResponse, Http404

from .uploads import CONTENT_TYPES


def private_file_response(field_file):
    if not field_file:
        raise Http404
    try:
        handle = field_file.storage.open(field_file.name, "rb")
    except (FileNotFoundError, OSError):
        raise Http404 from None
    ext = os.path.splitext(field_file.name)[1].lower()
    content_type = CONTENT_TYPES.get(ext) or mimetypes.guess_type(field_file.name)[0] or "application/octet-stream"
    response = FileResponse(handle, content_type=content_type)
    response["Cache-Control"] = "private, no-store"
    response["X-Content-Type-Options"] = "nosniff"
    response["Content-Disposition"] = "inline"
    return response
