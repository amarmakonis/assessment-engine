"""
Flask application factory — single point of assembly.
"""

from __future__ import annotations

import logging
import sys
from datetime import timedelta

from flask import Flask

from app.config import AppSettings, get_settings


def create_app(settings: AppSettings | None = None) -> Flask:
    settings = settings or get_settings()

    app = Flask(__name__)
    _apply_flask_config(app, settings)
    _init_logging(settings)
    _init_extensions(app, settings)
    _register_blueprints(app)
    _register_error_handlers(app)
    _register_health_check(app)

    return app


def _apply_flask_config(app: Flask, s: AppSettings) -> None:
    app.config.update(
        SECRET_KEY=s.SECRET_KEY,
        DEBUG=s.DEBUG,
        JWT_SECRET_KEY=s.JWT_SECRET_KEY,
        JWT_ACCESS_TOKEN_EXPIRES=timedelta(minutes=s.JWT_ACCESS_TOKEN_EXPIRES_MINUTES),
        JWT_REFRESH_TOKEN_EXPIRES=timedelta(days=s.JWT_REFRESH_TOKEN_EXPIRES_DAYS),
        JWT_ALGORITHM=s.JWT_ALGORITHM,
        API_TITLE=s.APP_NAME,
        API_VERSION=s.API_VERSION,
        OPENAPI_VERSION="3.0.3",
        OPENAPI_URL_PREFIX="/api/docs",
        OPENAPI_SWAGGER_UI_PATH="/swagger",
        OPENAPI_SWAGGER_UI_URL="https://cdn.jsdelivr.net/npm/swagger-ui-dist/",
        MAX_CONTENT_LENGTH=s.max_upload_bytes,
    )


def _init_logging(s: AppSettings) -> None:
    import json_log_formatter

    formatter = json_log_formatter.JSONFormatter()
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(formatter)

    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(getattr(logging, s.LOG_LEVEL.upper(), logging.INFO))


def _init_extensions(app: Flask, s: AppSettings) -> None:
    from app.extensions import cors, init_mongo, init_redis, jwt, smorest_api

    cors.init_app(app, resources={r"/api/*": {"origins": "*"}})
    jwt.init_app(app)
    smorest_api.init_app(app)

    init_mongo(
        s.MONGO_URI,
        maxPoolSize=s.MONGO_MAX_POOL_SIZE,
        minPoolSize=s.MONGO_MIN_POOL_SIZE,
    )
    init_redis(s.REDIS_URL)


def _register_blueprints(app: Flask) -> None:
    from app.api.v1.auth import auth_bp
    from app.api.v1.dashboard import dashboard_bp
    from app.api.v1.evaluation import evaluation_bp
    from app.api.v1.exam import exam_bp
    from app.api.v1.files import files_bp
    from app.api.v1.ocr import ocr_bp
    from app.api.v1.upload import upload_bp

    prefix = "/api/v1"
    for bp in (auth_bp, upload_bp, ocr_bp, evaluation_bp, dashboard_bp, exam_bp, files_bp):
        app.register_blueprint(bp, url_prefix=f"{prefix}{bp.url_prefix or ''}")


def _register_error_handlers(app: Flask) -> None:
    from app.api.middleware.errors import register_error_handlers

    register_error_handlers(app)


def _register_health_check(app: Flask) -> None:
    @app.route("/health")
    def health():
        return {"status": "ok", "service": "aae-backend"}
