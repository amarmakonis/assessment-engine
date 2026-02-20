"""
Unit tests for evaluation task idempotency and helper logic.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from app.tasks.evaluation import _check_script_completion


class TestCheckScriptCompletion:
    @patch("app.tasks.evaluation.ScriptRepository")
    @patch("app.tasks.evaluation.EvaluationResultRepository")
    def test_marks_complete_when_all_evaluated(self, mock_eval_repo_cls, mock_script_repo_cls):
        mock_script_repo = MagicMock()
        mock_script_repo.find_by_id.return_value = {
            "_id": "script_001",
            "answers": [
                {"questionId": "q1", "text": "Answer 1", "isFlagged": False},
                {"questionId": "q2", "text": "Answer 2", "isFlagged": False},
            ],
        }
        mock_script_repo_cls.return_value = mock_script_repo

        mock_eval_repo = MagicMock()
        mock_eval_repo.find_by_script.return_value = [
            {"questionId": "q1", "status": "COMPLETE"},
            {"questionId": "q2", "status": "COMPLETE"},
        ]
        mock_eval_repo_cls.return_value = mock_eval_repo

        _check_script_completion("script_001")

        mock_script_repo.update_one.assert_called_once()
        update_call = mock_script_repo.update_one.call_args
        assert update_call[0][1]["$set"]["status"] == "COMPLETE"

    @patch("app.tasks.evaluation.ScriptRepository")
    @patch("app.tasks.evaluation.EvaluationResultRepository")
    def test_marks_flagged_when_has_flagged_answers(self, mock_eval_repo_cls, mock_script_repo_cls):
        mock_script_repo = MagicMock()
        mock_script_repo.find_by_id.return_value = {
            "_id": "script_002",
            "answers": [
                {"questionId": "q1", "text": "Answer 1", "isFlagged": False},
                {"questionId": "q2", "text": "", "isFlagged": True},
            ],
        }
        mock_script_repo_cls.return_value = mock_script_repo

        mock_eval_repo = MagicMock()
        mock_eval_repo.find_by_script.return_value = [
            {"questionId": "q1", "status": "COMPLETE"},
        ]
        mock_eval_repo_cls.return_value = mock_eval_repo

        _check_script_completion("script_002")

        mock_script_repo.update_one.assert_called_once()
        update_call = mock_script_repo.update_one.call_args
        assert update_call[0][1]["$set"]["status"] == "FLAGGED"

    @patch("app.tasks.evaluation.ScriptRepository")
    @patch("app.tasks.evaluation.EvaluationResultRepository")
    def test_no_update_when_incomplete(self, mock_eval_repo_cls, mock_script_repo_cls):
        mock_script_repo = MagicMock()
        mock_script_repo.find_by_id.return_value = {
            "_id": "script_003",
            "answers": [
                {"questionId": "q1", "text": "Answer 1", "isFlagged": False},
                {"questionId": "q2", "text": "Answer 2", "isFlagged": False},
            ],
        }
        mock_script_repo_cls.return_value = mock_script_repo

        mock_eval_repo = MagicMock()
        mock_eval_repo.find_by_script.return_value = [
            {"questionId": "q1", "status": "COMPLETE"},
        ]
        mock_eval_repo_cls.return_value = mock_eval_repo

        _check_script_completion("script_003")

        mock_script_repo.update_one.assert_not_called()

    @patch("app.tasks.evaluation.ScriptRepository")
    def test_handles_missing_script(self, mock_script_repo_cls):
        mock_script_repo = MagicMock()
        mock_script_repo.find_by_id.return_value = None
        mock_script_repo_cls.return_value = mock_script_repo

        _check_script_completion("nonexistent")
        mock_script_repo.update_one.assert_not_called()
