"""
Shared test fixtures — mocked infrastructure for unit tests.
"""

from __future__ import annotations

import os
import pytest
from unittest.mock import MagicMock, patch

os.environ.setdefault("SECRET_KEY", "test-secret-key-must-be-at-least-32-chars-long")
os.environ.setdefault("ENVIRONMENT", "development")
os.environ.setdefault("MONGO_URI", "mongodb://localhost:27017")
os.environ.setdefault("OPENAI_API_KEY", "sk-test-key")


@pytest.fixture
def app():
    from app.config import get_settings
    get_settings.cache_clear()

    from app.factory import create_app
    app = create_app()
    app.config["TESTING"] = True
    return app


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture
def mock_mongo():
    with patch("app.infrastructure.db.repositories._get_db") as mock_db:
        db = MagicMock()
        mock_db.return_value = db
        yield db


@pytest.fixture
def mock_redis():
    with patch("app.extensions.get_redis") as mock:
        redis_mock = MagicMock()
        mock.return_value = redis_mock
        yield redis_mock


@pytest.fixture
def mock_storage():
    with patch("app.infrastructure.storage.get_storage_provider") as mock:
        storage = MagicMock()
        storage.upload.return_value = "test-key"
        storage.generate_signed_url.return_value = "https://signed.url/test"
        storage.exists.return_value = True
        mock.return_value = storage
        yield storage


@pytest.fixture
def mock_llm_gateway():
    with patch("app.infrastructure.llm.get_llm_gateway") as mock:
        gateway = MagicMock()
        mock.return_value = gateway
        yield gateway


@pytest.fixture
def mock_ocr():
    with patch("app.infrastructure.ocr.extract_page_text") as mock:
        from app.domain.ports.ocr import OCRResult
        mock.return_value = OCRResult(
            text="Sample OCR text for testing purposes.",
            confidence=0.92,
            word_level_data=None,
            page_number=1,
            processing_ms=150,
            provider="openai_vision",
        )
        yield mock


@pytest.fixture
def sample_exam_doc():
    return {
        "_id": "exam_001",
        "institutionId": "inst_001",
        "title": "CS101 Final",
        "subject": "Computer Science",
        "totalMarks": 10.0,
        "questions": [
            {
                "questionId": "q1",
                "questionText": "Explain polymorphism in OOP.",
                "maxMarks": 5.0,
                "rubric": [
                    {"criterionId": "c1", "description": "Definition accuracy", "maxMarks": 2.0},
                    {"criterionId": "c2", "description": "Examples provided", "maxMarks": 3.0},
                ],
            },
            {
                "questionId": "q2",
                "questionText": "What is a binary search tree?",
                "maxMarks": 5.0,
                "rubric": [
                    {"criterionId": "c3", "description": "Definition", "maxMarks": 2.5},
                    {"criterionId": "c4", "description": "Time complexity", "maxMarks": 2.5},
                ],
            },
        ],
    }
