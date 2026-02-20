"""
Storage provider factory — uses MongoDB GridFS by default.
"""

from __future__ import annotations

from functools import lru_cache

from app.config import get_settings


@lru_cache(maxsize=1)
def get_storage_provider():
    settings = get_settings()
    if settings.STORAGE_PROVIDER == "s3":
        from app.infrastructure.storage.s3 import S3StorageProvider
        return S3StorageProvider()
    from app.infrastructure.storage.gridfs_storage import GridFSStorageProvider
    return GridFSStorageProvider()
