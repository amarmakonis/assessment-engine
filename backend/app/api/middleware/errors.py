"""
Centralized error handlers for the Flask application.
"""

from __future__ import annotations

import logging

from flask import Flask, jsonify
from pydantic import ValidationError as PydanticValidationError
from werkzeug.exceptions import HTTPException

from app.common.exceptions import AAEError, RateLimitError

logger = logging.getLogger(__name__)


def register_error_handlers(app: Flask) -> None:
    @app.errorhandler(AAEError)
    def handle_aae_error(exc: AAEError):
        payload = {"error": {"code": exc.code, "message": exc.message}}
        response = jsonify(payload)
        response.status_code = exc.status_code
        if isinstance(exc, RateLimitError):
            response.headers["Retry-After"] = str(exc.retry_after)
        return response

    @app.errorhandler(PydanticValidationError)
    def handle_pydantic_error(exc: PydanticValidationError):
        return jsonify({
            "error": {
                "code": "VALIDATION_ERROR",
                "message": "Request validation failed",
                "details": exc.errors(),
            }
        }), 422

    @app.errorhandler(HTTPException)
    def handle_http_error(exc: HTTPException):
        return jsonify({
            "error": {
                "code": exc.name.upper().replace(" ", "_"),
                "message": exc.description,
            }
        }), exc.code

    @app.errorhandler(Exception)
    def handle_unexpected_error(exc: Exception):
        logger.exception("Unhandled exception", exc_info=exc)
        return jsonify({
            "error": {
                "code": "INTERNAL_ERROR",
                "message": "An unexpected error occurred",
            }
        }), 500
