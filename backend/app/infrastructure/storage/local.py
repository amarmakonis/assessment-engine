"""
Local filesystem storage provider — development use.
"""

from __future__ import annotations

import hashlib
import hmac
import os
import shutil
import time
from pathlib import Path
from typing import BinaryIO

from app.common.exceptions import StorageError
from app.config import get_settings


class LocalStorageProvider:
    def __init__(self, base_path: str | None = None):
        settings = get_settings()
        self._base = Path(base_path or settings.LOCAL_STORAGE_PATH)
        self._base.mkdir(parents=True, exist_ok=True)
        self._secret = settings.SECRET_KEY

    def upload(self, file_obj: BinaryIO, key: str, metadata: dict | None = None) -> str:
        dest = self._base / key
        dest.parent.mkdir(parents=True, exist_ok=True)
        try:
            with open(dest, "wb") as f:
                shutil.copyfileobj(file_obj, f)
        except OSError as exc:
            raise StorageError(f"Failed to write file: {exc}") from exc
        return key

    def generate_signed_url(self, key: str, expires_in: int = 900) -> str:
        expiry = int(time.time()) + expires_in
        signature = hmac.new(
            self._secret.encode(),
            f"{key}:{expiry}".encode(),
            hashlib.sha256,
        ).hexdigest()[:32]
        return f"/api/v1/files/{key}?expires={expiry}&sig={signature}"

    def delete(self, key: str) -> None:
        path = self._base / key
        if path.exists():
            path.unlink()

    def exists(self, key: str) -> bool:
        return (self._base / key).exists()

    def download(self, key: str, dest_path: str) -> str:
        src = self._base / key
        if not src.exists():
            raise StorageError(f"Object not found: {key}")
        shutil.copy2(str(src), dest_path)
        return dest_path

    def resolve_path(self, key: str) -> Path:
        return self._base / key
