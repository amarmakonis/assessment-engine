"""
Unit tests for the local filesystem storage provider.
"""

from __future__ import annotations

import os
import tempfile
from io import BytesIO
from unittest.mock import patch

import pytest

from app.infrastructure.storage.local import LocalStorageProvider


@pytest.fixture
def storage(tmp_path):
    with patch("app.infrastructure.storage.local.get_settings") as mock_settings:
        settings = mock_settings.return_value
        settings.LOCAL_STORAGE_PATH = str(tmp_path)
        settings.SECRET_KEY = "test-secret-key-for-signing-urls-32chars"
        yield LocalStorageProvider(base_path=str(tmp_path))


class TestLocalStorageProvider:
    def test_upload_creates_file(self, storage, tmp_path):
        content = b"Hello, this is a test file"
        key = "test/file.pdf"
        result = storage.upload(BytesIO(content), key)

        assert result == key
        assert (tmp_path / key).exists()
        assert (tmp_path / key).read_bytes() == content

    def test_exists_returns_true_for_existing(self, storage, tmp_path):
        key = "existing.txt"
        (tmp_path / key).write_bytes(b"data")
        assert storage.exists(key) is True

    def test_exists_returns_false_for_missing(self, storage):
        assert storage.exists("nonexistent.pdf") is False

    def test_delete_removes_file(self, storage, tmp_path):
        key = "to_delete.txt"
        (tmp_path / key).write_bytes(b"delete me")
        assert storage.exists(key) is True

        storage.delete(key)
        assert storage.exists(key) is False

    def test_download_copies_file(self, storage, tmp_path):
        key = "source.txt"
        (tmp_path / key).write_bytes(b"source content")

        with tempfile.NamedTemporaryFile(delete=False, suffix=".txt") as dest:
            dest_path = dest.name

        try:
            result = storage.download(key, dest_path)
            assert result == dest_path
            with open(dest_path, "rb") as f:
                assert f.read() == b"source content"
        finally:
            os.unlink(dest_path)

    def test_generate_signed_url_contains_signature(self, storage, tmp_path):
        key = "signed/file.pdf"
        url = storage.generate_signed_url(key, expires_in=300)
        assert "sig=" in url
        assert "expires=" in url
        assert key in url

    def test_upload_nested_key_creates_directories(self, storage, tmp_path):
        key = "a/b/c/deep.pdf"
        storage.upload(BytesIO(b"nested"), key)
        assert (tmp_path / key).exists()

    def test_download_nonexistent_raises(self, storage):
        from app.common.exceptions import StorageError
        with pytest.raises(StorageError, match="not found"):
            storage.download("does_not_exist.pdf", "/tmp/out.pdf")
