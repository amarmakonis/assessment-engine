"""
MongoDB repository layer — all database operations are scoped by institutionId.
Uses PyMongo (synchronous) for Flask and Celery compatibility.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from bson import ObjectId

from app.config import get_settings
from app.extensions import get_mongo

logger = logging.getLogger(__name__)


def _get_db():
    client = get_mongo()
    return client[get_settings().MONGO_DB_NAME]


class BaseRepository:
    collection_name: str = ""

    @property
    def collection(self):
        return _get_db()[self.collection_name]

    def insert_one(self, document: dict) -> str:
        result = self.collection.insert_one(document)
        return str(result.inserted_id)

    def find_by_id(self, doc_id: str, institution_id: str | None = None) -> dict | None:
        query: dict[str, Any] = {"_id": ObjectId(doc_id)}
        if institution_id:
            query["institutionId"] = institution_id
        return self.collection.find_one(query)

    def find_many(
        self,
        query: dict,
        sort: list[tuple[str, int]] | None = None,
        skip: int = 0,
        limit: int = 100,
    ) -> list[dict]:
        cursor = self.collection.find(query)
        if sort:
            cursor = cursor.sort(sort)
        cursor = cursor.skip(skip).limit(limit)
        return list(cursor)

    def update_one(self, doc_id: str, update: dict, institution_id: str | None = None) -> bool:
        query: dict[str, Any] = {"_id": ObjectId(doc_id)}
        if institution_id:
            query["institutionId"] = institution_id
        update["$set"] = {**update.get("$set", {}), "updatedAt": datetime.now(timezone.utc)}
        result = self.collection.update_one(query, update)
        return result.modified_count > 0

    def count(self, query: dict) -> int:
        return self.collection.count_documents(query)

    def find_one(self, query: dict) -> dict | None:
        return self.collection.find_one(query)


class UploadedScriptRepository(BaseRepository):
    collection_name = "uploaded_scripts"


class OCRPageResultRepository(BaseRepository):
    collection_name = "ocr_page_results"

    def find_by_script(self, uploaded_script_id: str) -> list[dict]:
        return self.find_many(
            {"uploadedScriptId": uploaded_script_id},
            sort=[("pageNumber", 1)],
            limit=200,
        )


class ScriptRepository(BaseRepository):
    collection_name = "scripts"


class ExamRepository(BaseRepository):
    collection_name = "exams"


class EvaluationResultRepository(BaseRepository):
    collection_name = "evaluation_results"

    def find_by_idempotency_key(self, key: str) -> dict | None:
        return self.find_one({"idempotencyKey": key})

    def find_by_script(self, script_id: str) -> list[dict]:
        return self.find_many(
            {"scriptId": script_id},
            sort=[("questionId", 1)],
            limit=200,
        )


class UserRepository(BaseRepository):
    collection_name = "users"

    def find_by_email(self, email: str) -> dict | None:
        return self.find_one({"email": email})
