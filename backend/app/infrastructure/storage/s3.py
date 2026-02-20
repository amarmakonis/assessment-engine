"""
S3-compatible storage provider — production use (AWS S3 / MinIO).
"""

from __future__ import annotations

import shutil
from typing import BinaryIO

import boto3
from botocore.config import Config as BotoConfig
from botocore.exceptions import ClientError

from app.common.exceptions import StorageError
from app.config import get_settings


class S3StorageProvider:
    def __init__(self):
        settings = get_settings()
        client_kwargs: dict = {
            "region_name": settings.S3_REGION,
            "config": BotoConfig(
                signature_version="s3v4",
                retries={"max_attempts": 3, "mode": "adaptive"},
            ),
        }
        if settings.S3_ENDPOINT_URL:
            client_kwargs["endpoint_url"] = settings.S3_ENDPOINT_URL
        if settings.S3_ACCESS_KEY:
            client_kwargs["aws_access_key_id"] = settings.S3_ACCESS_KEY
            client_kwargs["aws_secret_access_key"] = settings.S3_SECRET_KEY

        self._client = boto3.client("s3", **client_kwargs)
        self._bucket = settings.S3_BUCKET_NAME
        self._expiry = settings.SIGNED_URL_EXPIRY_SECONDS

    def upload(self, file_obj: BinaryIO, key: str, metadata: dict | None = None) -> str:
        extra_args = {"ServerSideEncryption": "AES256"}
        if metadata:
            extra_args["Metadata"] = {k: str(v) for k, v in metadata.items()}
        try:
            self._client.upload_fileobj(file_obj, self._bucket, key, ExtraArgs=extra_args)
        except ClientError as exc:
            raise StorageError(f"S3 upload failed: {exc}") from exc
        return key

    def generate_signed_url(self, key: str, expires_in: int | None = None) -> str:
        try:
            return self._client.generate_presigned_url(
                "get_object",
                Params={"Bucket": self._bucket, "Key": key},
                ExpiresIn=expires_in or self._expiry,
            )
        except ClientError as exc:
            raise StorageError(f"Failed to generate signed URL: {exc}") from exc

    def delete(self, key: str) -> None:
        try:
            self._client.delete_object(Bucket=self._bucket, Key=key)
        except ClientError as exc:
            raise StorageError(f"S3 delete failed: {exc}") from exc

    def exists(self, key: str) -> bool:
        try:
            self._client.head_object(Bucket=self._bucket, Key=key)
            return True
        except ClientError:
            return False

    def download(self, key: str, dest_path: str) -> str:
        try:
            self._client.download_file(self._bucket, key, dest_path)
            return dest_path
        except ClientError as exc:
            raise StorageError(f"S3 download failed: {exc}") from exc
