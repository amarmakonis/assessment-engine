"""
Storage provider port — all object storage implementations conform to this protocol.
"""

from __future__ import annotations

from typing import BinaryIO, Protocol, runtime_checkable


@runtime_checkable
class StorageProvider(Protocol):
    def upload(self, file_obj: BinaryIO, key: str, metadata: dict | None = None) -> str:
        """Upload a file and return the storage key."""
        ...

    def generate_signed_url(self, key: str, expires_in: int = 900) -> str:
        """Generate a time-limited signed URL for asset access."""
        ...

    def delete(self, key: str) -> None:
        """Delete an object by key."""
        ...

    def exists(self, key: str) -> bool:
        """Check whether an object exists at the given key."""
        ...

    def download(self, key: str, dest_path: str) -> str:
        """Download an object to a local path. Returns the destination path."""
        ...
