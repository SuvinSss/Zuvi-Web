"""Uniform JSON errors: {"error": {"code", "message", "retryable", ...}}.

Nothing from Google (URLs, keys, raw bodies) is ever placed in a response.
"""

from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework import exceptions
from rest_framework.response import Response
from rest_framework.views import exception_handler as drf_exception_handler

from geo.errors import MapsError


def _flatten(value):
    if isinstance(value, dict):
        return {str(k): _flatten(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_flatten(v) for v in value]
    return str(value)


def api_exception_handler(exc, context):
    if isinstance(exc, MapsError):
        body = {"code": exc.code, "message": exc.public_message, "retryable": exc.retryable}
        reasons = getattr(exc, "reasons", None)
        if reasons is not None:
            body["reasons"] = reasons
        return Response({"error": body}, status=exc.http_status)

    if isinstance(exc, DjangoValidationError):
        data = exc.message_dict if hasattr(exc, "error_dict") else {"non_field_errors": exc.messages}
        return Response(
            {"error": {"code": "VALIDATION_ERROR", "message": "Please check the highlighted fields.",
                       "fields": _flatten(data)}},
            status=400,
        )

    response = drf_exception_handler(exc, context)
    if response is None:
        return None

    if isinstance(exc, exceptions.Throttled):
        code, message = "RATE_LIMITED", "Too many requests. Please wait a moment and try again."
    elif isinstance(exc, exceptions.ValidationError):
        code, message = "VALIDATION_ERROR", "Please check the highlighted fields."
    elif isinstance(exc, (exceptions.NotAuthenticated, exceptions.AuthenticationFailed)):
        code, message = "NOT_AUTHENTICATED", "Please sign in to continue."
        response.status_code = 401
    elif isinstance(exc, exceptions.PermissionDenied):
        code, message = "FORBIDDEN", "You do not have permission to do this."
    elif isinstance(exc, exceptions.NotFound):
        code, message = "NOT_FOUND", "We could not find what you were looking for."
    elif isinstance(exc, exceptions.MethodNotAllowed):
        code, message = "METHOD_NOT_ALLOWED", "This action is not allowed."
    else:
        code, message = "REQUEST_ERROR", "The request could not be completed."

    body = {"code": code, "message": message, "retryable": code == "RATE_LIMITED"}
    if isinstance(exc, exceptions.ValidationError):
        body["fields"] = _flatten(response.data)
    response.data = {"error": body}
    return response
