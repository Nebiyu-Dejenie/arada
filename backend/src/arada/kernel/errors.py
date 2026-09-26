"""Domain errors, rendered by the HTTP layer as RFC 9457 problem details.

Errors carry a stable ``code`` for clients and never include stack traces,
SQL, internal hostnames or secret values (Permanent Command §44).
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence


class AppError(Exception):
    status: int = 500
    code: str = "internal-error"
    title: str = "Internal error"

    def __init__(
        self,
        detail: str | None = None,
        *,
        errors: Mapping[str, Sequence[str]] | None = None,
    ) -> None:
        super().__init__(detail or self.title)
        self.detail = detail
        self.errors = dict(errors) if errors else None


class BadRequest(AppError):
    status = 400
    code = "bad-request"
    title = "Bad request"


class Unauthenticated(AppError):
    status = 401
    code = "unauthenticated"
    title = "Authentication required"


class MfaRequired(AppError):
    """Credentials were valid but a second factor is required."""

    status = 401
    code = "mfa-required"
    title = "Second factor required"


class Forbidden(AppError):
    status = 403
    code = "forbidden"
    title = "Not permitted"


class NotFound(AppError):
    status = 404
    code = "not-found"
    title = "Not found"


class Conflict(AppError):
    status = 409
    code = "conflict"
    title = "Conflict"


class PreconditionFailed(AppError):
    status = 412
    code = "precondition-failed"
    title = "Resource version does not match"


class ValidationFailed(AppError):
    status = 422
    code = "validation-failed"
    title = "Validation failed"


class PreconditionRequired(AppError):
    status = 428
    code = "precondition-required"
    title = "If-Match header required"
