"""
MongoDB GridFS storage provider — files stored directly in the database.
No filesystem, no S3, no MinIO needed.
"""

from __future__ import annotations

import hashlib
import hmac
import shutil
import time
from typing import BinaryIO

import gridfs
from bson import ObjectId

from app.common.exceptions import StorageError
from app.config import get_settings
from app.extensions import get_mongo


class GridFSStorageProvider:
    def __init__(self):
        settings = get_settings()
        db = get_mongo()[settings.MONGO_DB_NAME]
        self._fs = gridfs.GridFS(db)
        self._secret = settings.SECRET_KEY

    def upload(self, file_obj: BinaryIO, key: str, metadata: dict | None = None) -> str:
        try:
            existing = self._fs.find_one({"filename": key})
            if existing:
                self._fs.delete(existing._id)

            self._fs.put(
                file_obj,
                filename=key,
                metadata=metadata or {},
            )
        except Exception as exc:
            raise StorageError(f"GridFS upload failed: {exc}") from exc
        return key

    def download(self, key: str, dest_path: str) -> str:
        grid_out = self._fs.find_one({"filename": key})
        if not grid_out:
            raise StorageError(f"File not found in GridFS: {key}")
        try:
            with open(dest_path, "wb") as f:
                f.write(grid_out.read())
        except OSError as exc:
            raise StorageError(f"Failed to write downloaded file: {exc}") from exc
        return dest_path

    def generate_signed_url(self, key: str, expires_in: int = 900) -> str:
        expiry = int(time.time()) + expires_in
        signature = hmac.new(
            self._secret.encode(),
            f"{key}:{expiry}".encode(),
            hashlib.sha256,
        ).hexdigest()[:32]
        return f"/api/v1/files/{key}?expires={expiry}&sig={signature}"

    def delete(self, key: str) -> None:
        grid_out = self._fs.find_one({"filename": key})
        if grid_out:
            self._fs.delete(grid_out._id)

    def exists(self, key: str) -> bool:
        return self._fs.exists({"filename": key})
