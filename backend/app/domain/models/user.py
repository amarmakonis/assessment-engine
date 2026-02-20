"""
User domain model — multi-tenant, RBAC-enabled.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, EmailStr, Field

from app.domain.models.common import UserRole, utcnow


class User(BaseModel):
    id: str = Field(default="", alias="_id")
    institution_id: str = Field(alias="institutionId")
    email: EmailStr
    password_hash: str = Field(alias="passwordHash")
    full_name: str = Field(alias="fullName")
    role: UserRole
    is_active: bool = Field(default=True, alias="isActive")
    created_at: datetime = Field(default_factory=utcnow, alias="createdAt")
    updated_at: datetime = Field(default_factory=utcnow, alias="updatedAt")

    model_config = {"populate_by_name": True}

    def to_mongo(self) -> dict:
        data = self.model_dump(by_alias=True, exclude={"id"})
        if self.id:
            data["_id"] = self.id
        return data
