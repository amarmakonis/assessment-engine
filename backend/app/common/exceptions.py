"""
Domain and application exception hierarchy.
"""

from __future__ import annotations


class AAEError(Exception):
    """Base for all application exceptions."""

    def __init__(self, message: str, code: str = "INTERNAL_ERROR", status_code: int = 500):
        super().__init__(message)
        self.message = message
        self.code = code
        self.status_code = status_code


class ValidationError(AAEError):
    def __init__(self, message: str, code: str = "VALIDATION_ERROR"):
        super().__init__(message, code=code, status_code=422)


class NotFoundError(AAEError):
    def __init__(self, resource: str, identifier: str):
        super().__init__(
            f"{resource} with id '{identifier}' not found",
            code="NOT_FOUND",
            status_code=404,
        )


class DuplicateError(AAEError):
    def __init__(self, message: str):
        super().__init__(message, code="DUPLICATE", status_code=409)


class AuthError(AAEError):
    def __init__(self, message: str = "Authentication required"):
        super().__init__(message, code="AUTH_ERROR", status_code=401)


class ForbiddenError(AAEError):
    def __init__(self, message: str = "Insufficient permissions"):
        super().__init__(message, code="FORBIDDEN", status_code=403)


class RateLimitError(AAEError):
    def __init__(self, retry_after: int = 60):
        super().__init__(
            "Rate limit exceeded",
            code="RATE_LIMITED",
            status_code=429,
        )
        self.retry_after = retry_after


class StorageError(AAEError):
    def __init__(self, message: str):
        super().__init__(message, code="STORAGE_ERROR", status_code=502)


class OCRError(AAEError):
    def __init__(self, message: str):
        super().__init__(message, code="OCR_ERROR", status_code=502)


class LLMError(AAEError):
    def __init__(self, message: str):
        super().__init__(message, code="LLM_ERROR", status_code=502)


class SegmentationError(AAEError):
    def __init__(self, message: str):
        super().__init__(message, code="SEGMENTATION_ERROR", status_code=502)
