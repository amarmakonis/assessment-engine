"""
Database repository singletons.
"""

from app.infrastructure.db.repositories import (
    EvaluationResultRepository,
    ExamJobRepository,
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
    "ExamJobRepository",
    "EvaluationResultRepository",
    "UserRepository",
]
