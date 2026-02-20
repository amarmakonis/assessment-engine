"""
Unit tests for auth endpoints.
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest


class TestAuthEndpoints:
    @patch("app.api.v1.auth.UserRepository")
    def test_register_success(self, mock_repo_cls, client):
        mock_repo = MagicMock()
        mock_repo.find_by_email.return_value = None
        mock_repo.insert_one.return_value = "user_123"
        mock_repo_cls.return_value = mock_repo

        response = client.post(
            "/api/v1/auth/register",
            data=json.dumps({
                "email": "test@example.com",
                "password": "securepass123",
                "fullName": "Test User",
                "institutionId": "inst_001",
            }),
            content_type="application/json",
        )

        assert response.status_code == 201
        data = response.get_json()
        assert data["userId"] == "user_123"

    @patch("app.api.v1.auth.UserRepository")
    def test_register_duplicate_email(self, mock_repo_cls, client):
        mock_repo = MagicMock()
        mock_repo.find_by_email.return_value = {"_id": "existing", "email": "test@example.com"}
        mock_repo_cls.return_value = mock_repo

        response = client.post(
            "/api/v1/auth/register",
            data=json.dumps({
                "email": "test@example.com",
                "password": "securepass123",
                "fullName": "Test User",
                "institutionId": "inst_001",
            }),
            content_type="application/json",
        )

        assert response.status_code == 409

    @patch("app.api.v1.auth.bcrypt")
    @patch("app.api.v1.auth.UserRepository")
    def test_login_success(self, mock_repo_cls, mock_bcrypt, client):
        mock_repo = MagicMock()
        mock_repo.find_by_email.return_value = {
            "_id": "user_123",
            "email": "test@example.com",
            "passwordHash": "$2b$12$hashedpassword",
            "fullName": "Test User",
            "role": "EXAMINER",
            "institutionId": "inst_001",
            "isActive": True,
        }
        mock_repo_cls.return_value = mock_repo
        mock_bcrypt.checkpw.return_value = True

        response = client.post(
            "/api/v1/auth/login",
            data=json.dumps({
                "email": "test@example.com",
                "password": "securepass123",
            }),
            content_type="application/json",
        )

        assert response.status_code == 200
        data = response.get_json()
        assert "accessToken" in data
        assert "refreshToken" in data
        assert data["user"]["email"] == "test@example.com"
