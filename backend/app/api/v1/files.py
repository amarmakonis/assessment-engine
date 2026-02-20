"""
File serving endpoint — streams files from GridFS with signed URL verification.
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import time

from flask import Response, abort, request
from flask.views import MethodView
from flask_smorest import Blueprint

from app.config import get_settings
from app.extensions import get_mongo

import gridfs

logger = logging.getLogger(__name__)
files_bp = Blueprint("files", __name__, url_prefix="/files", description="File Serving")


@files_bp.route("/<path:file_key>")
class FileServeView(MethodView):
    def get(self, file_key: str):
        """Serve a file from GridFS after verifying the signed URL."""
        expires = request.args.get("expires")
        sig = request.args.get("sig")

        if not expires or not sig:
            abort(403, description="Missing signature parameters")

        try:
            expiry = int(expires)
        except ValueError:
            abort(403, description="Invalid expiry")

        if time.time() > expiry:
            abort(403, description="Signed URL has expired")

        settings = get_settings()
        expected_sig = hmac.new(
            settings.SECRET_KEY.encode(),
            f"{file_key}:{expiry}".encode(),
            hashlib.sha256,
        ).hexdigest()[:32]

        if not hmac.compare_digest(sig, expected_sig):
            abort(403, description="Invalid signature")

        db = get_mongo()[settings.MONGO_DB_NAME]
        fs = gridfs.GridFS(db)
        grid_out = fs.find_one({"filename": file_key})

        if not grid_out:
            abort(404, description="File not found")

        mime_map = {
            ".jpg": "image/jpeg",
            ".jpeg": "image/jpeg",
            ".png": "image/png",
            ".pdf": "application/pdf",
            ".gif": "image/gif",
        }
        ext = ""
        for e in mime_map:
            if file_key.lower().endswith(e):
                ext = e
                break

        content_type = mime_map.get(ext, "application/octet-stream")
        metadata = grid_out.metadata or {}
        orig_filename = metadata.get("originalFilename", "")
        if orig_filename:
            for e, mime in mime_map.items():
                if orig_filename.lower().endswith(e):
                    content_type = mime
                    break

        data = grid_out.read()

        return Response(
            data,
            mimetype=content_type,
            headers={
                "Cache-Control": "private, max-age=900",
                "Content-Length": str(len(data)),
            },
        )
