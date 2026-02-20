"""
Database repository singletons.
"""

from app.infrastructure.db.repositories import (
    EvaluationResultRepository,
    ExamRepository,
    OCRPageResultRepository,
    ScriptRepository,
    UploadedScriptRepository,
    UserRepository,
)

__all__ = [
    "UploadedScriptRepository",
    "OCRPageResultRepository",
    "ScriptRepository",
    "ExamRepository",
    "EvaluationResultRepository",
    "UserRepository",
]
