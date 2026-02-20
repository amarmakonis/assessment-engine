"""
UploadedScript domain model.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

from app.domain.models.common import (
    StudentMeta,
    UploadStatus,
    VirusScanStatus,
    utcnow,
)


class UploadedScript(BaseModel):
    id: str = Field(default="", alias="_id")
    institution_id: str = Field(alias="institutionId")
    exam_id: str = Field(alias="examId")
    upload_batch_id: str = Field(alias="uploadBatchId")
    student_meta: StudentMeta = Field(alias="studentMeta")
    file_key: str = Field(alias="fileKey")
    original_filename: str = Field(alias="originalFilename")
    mime_type: str = Field(alias="mimeType")
    file_size_bytes: int = Field(alias="fileSizeBytes")
    page_count: int | None = Field(default=None, alias="pageCount")
    upload_status: UploadStatus = Field(default=UploadStatus.UPLOADED, alias="uploadStatus")
    failure_reason: str | None = Field(default=None, alias="failureReason")
    virus_scan_status: VirusScanStatus = Field(
        default=VirusScanStatus.PENDING, alias="virusScanStatus"
    )
    created_at: datetime = Field(default_factory=utcnow, alias="createdAt")
    updated_at: datetime = Field(default_factory=utcnow, alias="updatedAt")
    created_by: str = Field(alias="createdBy")

    model_config = {"populate_by_name": True}

    def to_mongo(self) -> dict:
        data = self.model_dump(by_alias=True, exclude={"id"})
        if self.id:
            data["_id"] = self.id
        return data
