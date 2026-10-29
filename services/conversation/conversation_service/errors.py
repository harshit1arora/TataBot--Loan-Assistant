"""Error types and handlers for the conversation service."""
from __future__ import annotations


class AppError(Exception):
    status_code = 500
    code = "internal_error"
    message = "An unexpected error occurred."

    def __init__(self, message: str | None = None, *, details=None) -> None:
        self.message = message or self.message
        self.details = details
        super().__init__(self.message)


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


class ValidationAppError(AppError):
    status_code = 422
    code = "validation_failed"


class ConflictError(AppError):
    status_code = 409
    code = "conflict"
