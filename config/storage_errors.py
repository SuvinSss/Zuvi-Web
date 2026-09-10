"""Expected storage failures at request boundaries; never delete failed uploads."""

import logging
from functools import wraps

from boto3.exceptions import RetriesExceededError, S3UploadFailedError
from botocore.exceptions import BotoCoreError, ClientError
from django.contrib import messages
from django.core.exceptions import ValidationError
from django.db import transaction
from django.http import HttpResponse
from django.shortcuts import redirect

STORAGE_ERRORS = (OSError, BotoCoreError, ClientError, S3UploadFailedError, RetriesExceededError)
STORAGE_ERROR_MESSAGE = "Could not save the image. Please try again."
logger = logging.getLogger(__name__)


def image_request_errors(view):
    """Keep storage details in server logs, after the service has rolled back."""
    @wraps(view)
    def wrapped(request, *args, **kwargs):
        try:
            return view(request, *args, **kwargs)
        except STORAGE_ERRORS:
            logger.exception("Image storage operation failed")
            if request.method != "POST":
                return HttpResponse(STORAGE_ERROR_MESSAGE, status=503, content_type="text/plain")
            messages.error(request, STORAGE_ERROR_MESSAGE)
            return redirect(request.path)
        except ValidationError as exc:
            if request.method != "POST":
                raise
            messages.error(request, "; ".join(exc.messages))
            return redirect(request.path)
    return wrapped


class ImageAdminErrorMixin:
    """Roll back admin saves AND admin logging before reporting a failed POST."""

    def _image_admin_call(self, request, callback, *args, **kwargs):
        if request.method != "POST":
            return callback(request, *args, **kwargs)
        try:
            with transaction.atomic():
                return callback(request, *args, **kwargs)
        except STORAGE_ERRORS:
            logger.exception("Admin image storage operation failed")
            messages.error(request, STORAGE_ERROR_MESSAGE)
        except ValidationError as exc:
            messages.error(request, "; ".join(exc.messages))
        return redirect(request.path)

    def changeform_view(self, request, *args, **kwargs):
        return self._image_admin_call(request, super().changeform_view, *args, **kwargs)

    def delete_view(self, request, *args, **kwargs):
        return self._image_admin_call(request, super().delete_view, *args, **kwargs)

    def changelist_view(self, request, *args, **kwargs):
        return self._image_admin_call(request, super().changelist_view, *args, **kwargs)
