"""Typed application errors.

The client sees a stable error code and a safe message. Internal detail (stack traces,
connection strings, upstream payloads) is logged, never serialised to the response.
"""
from __future__ import annotations

from typing import Any


class AppError(Exception):
    status_code = 500
    code = "internal_error"
    message = "An unexpected error occurred."

    def __init__(self, message: str | None = None, *, details: Any = None) -> None:
        self.message = message or self.message
        self.details = details
        super().__init__(self.message)

    def to_payload(self, request_id: str) -> dict[str, Any]:
        body: dict[str, Any] = {
            "error": {"code": self.code, "message": self.message, "request_id": request_id}
        }
        if self.details is not None:
            body["error"]["details"] = self.details
        return body


class ValidationAppError(AppError):
    status_code = 422
    code = "validation_failed"


class AuthenticationError(AppError):
    status_code = 401
    code = "unauthenticated"
    message = "A valid bearer token is required."


class AuthorisationError(AppError):
    status_code = 403
    code = "forbidden"
    message = "You do not have access to this resource."


class NotFoundError(AppError):
    status_code = 404
    code = "not_found"
    message = "The requested resource does not exist."


class ConflictError(AppError):
    status_code = 409
    code = "conflict"


class PolicyRejection(AppError):
    """A business rule refused the request. Not a system failure."""

    status_code = 409
    code = "policy_rejection"


class PreconditionFailed(AppError):
    status_code = 409
    code = "precondition_failed"


class UpstreamError(AppError):
    status_code = 502
    code = "upstream_unavailable"
    message = "A dependency is currently unavailable. Please retry."


class RateLimited(AppError):
    status_code = 429
    code = "rate_limited"
    message = "Too many requests. Please slow down."
