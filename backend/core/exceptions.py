"""One error shape for every API response.

Clients always get either ``{"detail": "message"}`` or ``{"field": ["message"]}``
(HTTP 400). Django validation / permission / 404 exceptions raised by the shared
services are translated here so views do not need try/except boilerplate.
"""
import logging

from django.core.exceptions import PermissionDenied as DjangoPermissionDenied
from django.core.exceptions import ValidationError as DjangoValidationError
from django.http import Http404
from rest_framework import exceptions
from rest_framework.response import Response
from rest_framework.views import exception_handler as drf_exception_handler

logger = logging.getLogger(__name__)


def validation_payload(exc: DjangoValidationError):
    if hasattr(exc, "error_dict"):
        return {field: [str(m) for m in messages] for field, messages in exc.message_dict.items()}
    return {"detail": " ".join(str(m) for m in exc.messages)}


def api_exception_handler(exc, context):
    if isinstance(exc, DjangoValidationError):
        return Response(validation_payload(exc), status=400)
    if isinstance(exc, DjangoPermissionDenied):
        return Response({"detail": str(exc) or "You do not have permission to perform this action."}, status=403)
    if isinstance(exc, Http404):
        return Response({"detail": "Not found."}, status=404)
    response = drf_exception_handler(exc, context)
    if response is None:
        logger.exception("Unhandled API error", exc_info=exc)
        return Response({"detail": "The server had a problem. Please try again."}, status=500)
    if isinstance(exc, exceptions.Throttled):
        response.data = {"detail": "Too many requests. Please slow down and try again shortly."}
    return response
