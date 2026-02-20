"""
Authentication & user management endpoints.
JWT access + refresh tokens, RBAC role assignment.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

import bcrypt
from flask import request
from flask.views import MethodView
from flask_jwt_extended import (
    create_access_token,
    create_refresh_token,
    get_jwt_identity,
    jwt_required as flask_jwt_required,
)
from flask_smorest import Blueprint
from pydantic import BaseModel, EmailStr, Field

from app.api.middleware.auth import jwt_required
from app.common.exceptions import AuthError, DuplicateError, ValidationError
from app.domain.models.common import UserRole
from app.infrastructure.db.repositories import UserRepository

logger = logging.getLogger(__name__)
auth_bp = Blueprint("auth", __name__, url_prefix="/auth", description="Authentication")


class RegisterRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8)
    full_name: str = Field(min_length=1, alias="fullName")
    institution_id: str = Field(alias="institutionId")
    role: UserRole = UserRole.EXAMINER

    model_config = {"populate_by_name": True}


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


@auth_bp.route("/register")
class RegisterView(MethodView):
    def post(self):
        data = RegisterRequest.model_validate(request.get_json())
        repo = UserRepository()

        existing = repo.find_by_email(data.email)
        if existing:
            raise DuplicateError(f"User with email {data.email} already exists")

        hashed = bcrypt.hashpw(data.password.encode(), bcrypt.gensalt()).decode()

        user_doc = {
            "email": data.email,
            "passwordHash": hashed,
            "fullName": data.full_name,
            "institutionId": data.institution_id,
            "role": data.role.value,
            "isActive": True,
            "createdAt": datetime.now(timezone.utc),
            "updatedAt": datetime.now(timezone.utc),
        }
        user_id = repo.insert_one(user_doc)

        return {
            "message": "User registered successfully",
            "userId": user_id,
        }, 201


@auth_bp.route("/login")
class LoginView(MethodView):
    def post(self):
        data = LoginRequest.model_validate(request.get_json())
        repo = UserRepository()

        user = repo.find_by_email(data.email)
        if not user:
            raise AuthError("Invalid email or password")

        if not bcrypt.checkpw(data.password.encode(), user["passwordHash"].encode()):
            raise AuthError("Invalid email or password")

        if not user.get("isActive", True):
            raise AuthError("Account is deactivated")

        identity = str(user["_id"])
        additional_claims = {
            "institution_id": user["institutionId"],
            "role": user["role"],
            "email": user["email"],
        }

        access_token = create_access_token(
            identity=identity, additional_claims=additional_claims
        )
        refresh_token = create_refresh_token(
            identity=identity, additional_claims=additional_claims
        )

        return {
            "accessToken": access_token,
            "refreshToken": refresh_token,
            "user": {
                "id": identity,
                "email": user["email"],
                "fullName": user["fullName"],
                "role": user["role"],
                "institutionId": user["institutionId"],
            },
        }


@auth_bp.route("/refresh")
class RefreshView(MethodView):
    @flask_jwt_required(refresh=True)
    def post(self):
        identity = get_jwt_identity()
        repo = UserRepository()
        user = repo.find_by_id(identity)
        if not user:
            raise AuthError("User not found")

        additional_claims = {
            "institution_id": user["institutionId"],
            "role": user["role"],
            "email": user["email"],
        }
        access_token = create_access_token(
            identity=identity, additional_claims=additional_claims
        )
        return {"accessToken": access_token}


@auth_bp.route("/me")
class MeView(MethodView):
    @jwt_required
    def get(self):
        from app.api.middleware.auth import get_current_user_id
        repo = UserRepository()
        user = repo.find_by_id(get_current_user_id())
        if not user:
            raise AuthError("User not found")
        return {
            "id": str(user["_id"]),
            "email": user["email"],
            "fullName": user["fullName"],
            "role": user["role"],
            "institutionId": user["institutionId"],
        }
