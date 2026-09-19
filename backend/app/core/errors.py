"""Application-wide error types and FastAPI exception handlers.

Design doc §30 (Failure Handling) and ARCHITECTURE_CONTRACTS.md §11:
errors must be visible, never silent, and degrade gracefully rather than
hard-fail a demo/run.
"""
from __future__ import annotations

from fastapi import FastAPI, Request, status
from fastapi.responses import JSONResponse
from pydantic import ValidationError


class EduPathError(Exception):
    """Base class for domain errors that should map to a clean HTTP response."""

    status_code: int = status.HTTP_400_BAD_REQUEST
    error_code: str = "edupath_error"

    def __init__(self, message: str, *, error_code: str | None = None):
        super().__init__(message)
        self.message = message
        if error_code:
            self.error_code = error_code


class NotFoundError(EduPathError):
    status_code = status.HTTP_404_NOT_FOUND
    error_code = "not_found"


class ValidationFailedError(EduPathError):
    """Raised when an LLM or client payload fails schema/rule validation.

    Per ARCHITECTURE_CONTRACTS.md §11: schema validation failure should trigger
    a bounded retry upstream, then a deterministic fallback. This error type is
    surfaced to the API boundary only after that policy has already been applied.
    """

    status_code = status.HTTP_422_UNPROCESSABLE_ENTITY
    error_code = "validation_failed"


class UnsupportedRoleError(EduPathError):
    """Role not present in the curated skill graph (design §30: never fabricate)."""

    status_code = status.HTTP_404_NOT_FOUND
    error_code = "role_not_supported"


def _error_body(error_code: str, message: str, *, details: object | None = None) -> dict:
    body: dict = {"error": {"code": error_code, "message": message}}
    if details is not None:
        body["error"]["details"] = details
    return body


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(EduPathError)
    async def handle_edupath_error(_: Request, exc: EduPathError) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content=_error_body(exc.error_code, exc.message),
        )

    @app.exception_handler(ValidationError)
    async def handle_pydantic_validation_error(_: Request, exc: ValidationError) -> JSONResponse:
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            content=_error_body("validation_failed", "Request failed schema validation.", details=exc.errors()),
        )

    @app.exception_handler(Exception)
    async def handle_unexpected_error(_: Request, exc: Exception) -> JSONResponse:
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content=_error_body("internal_error", "An unexpected error occurred."),
        )
