import base64
import json
import logging
import os
import re
import threading
import traceback
import uuid
from datetime import datetime, timedelta, timezone

import bcrypt
from bson import ObjectId
from dotenv import load_dotenv
from flask import Flask, jsonify, request, send_from_directory
from flask_cors import CORS
from flask_jwt_extended import (
    JWTManager,
    create_access_token,
    create_refresh_token,
    get_jwt_identity,
    jwt_required as flask_jwt_required,
)
from mistralai.client import Mistral

from agents.evaluator import evaluate_mapped_results
from agents.extractor import extract_question_paper
from agents.mapper import map_answers
from agents.rubrics import generate_rubrics_from_json
from agents.segmenter import segment_answer_script
from agents.batch_manager import BatchManager
from tasks import process_exam_task, process_script_task, process_batch_task
from db import get_collection, using_mock_db
from prompts import get_pixtral_fallback_prompt
from security import get_current_institution_id, get_current_user_id, jwt_required

load_dotenv()

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")
FRONTEND_DIST_DIR = os.path.join(os.path.dirname(BASE_DIR), "frontend", "dist")
os.makedirs(DATA_DIR, exist_ok=True)

app = Flask(__name__, template_folder="templates", static_folder="static")
logging.getLogger("werkzeug").setLevel(logging.ERROR)
app.config["JWT_SECRET_KEY"] = (
    os.getenv("JWT_SECRET_KEY")
    or os.getenv("SECRET_KEY")
    or "dev-secret-key-change-me-12345678901234567890"
)
app.config["JWT_ACCESS_TOKEN_EXPIRES"] = timedelta(minutes=int(os.getenv("JWT_ACCESS_TOKEN_EXPIRES_MINUTES", "15")))
app.config["JWT_REFRESH_TOKEN_EXPIRES"] = timedelta(days=int(os.getenv("JWT_REFRESH_TOKEN_EXPIRES_DAYS", "7")))

CORS(app, resources={r"/api/*": {"origins": "*"}, r"/*": {"origins": "*"}})
jwt = JWTManager(app)

client = Mistral(api_key=os.getenv("MISTRAL_API_KEY"))


def _now():
    return datetime.now(timezone.utc)


def _ensure_utc(dt):
    if not dt:
        return dt
    if not isinstance(dt, datetime):
        return dt
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _iso(value):
    if isinstance(value, datetime):
        return value.isoformat()
    return value


def _serialize_doc(doc):
    if not doc:
        return None
    result = {}
    for key, value in doc.items():
        if key == "_id":
            result["id"] = str(value)
        elif isinstance(value, ObjectId):
            result[key] = str(value)
        elif isinstance(value, datetime):
            result[key] = value.isoformat()
        elif isinstance(value, list):
            result[key] = [_serialize_doc(item) if isinstance(item, dict) else _iso(item) for item in value]
        elif isinstance(value, dict):
            result[key] = _serialize_doc(value)
        else:
            result[key] = value
    return result


def _data_path(filename):
    return os.path.join(DATA_DIR, filename)


def _write_json(filename, payload):
    with open(_data_path(filename), "w", encoding="utf-8") as handle:
        if isinstance(payload, str):
            handle.write(payload)
        else:
            json.dump(payload, handle, ensure_ascii=False, indent=2)


def _load_json(filename, default=None):
    path = _data_path(filename)
    if not os.path.exists(path):
        return default
    with open(path, "r", encoding="utf-8") as handle:
        return json.load(handle)


def _activity_state():
    return _load_json("activity_state.json", {"dismissed": [], "clear_before": None})


def _save_activity_state(state):
    _write_json("activity_state.json", state)


def _extract_file_to_json(file_storage, doc_type):
    file_content = file_storage.read()
    return _extract_bytes_to_json(file_content, file_storage.content_type, file_storage.filename, doc_type)


def _extract_bytes_to_json(file_content, mime_type, filename, doc_type):
    base64_content = base64.b64encode(file_content).decode("utf-8")
    fallback_prompt = get_pixtral_fallback_prompt()

    if doc_type == "question":
        structured_json = extract_question_paper(
            file_content,
            mime_type,
            filename,
            base64_content,
            client,
            fallback_prompt,
        )
    else:
        structured_json = segment_answer_script(
            file_content,
            mime_type,
            filename,
            base64_content,
            client,
            fallback_prompt,
        )
    return structured_json


def _question_to_frontend(question, rubric_lookup):
    question_id = str(question.get("id", "")).strip()
    rubric_text = rubric_lookup.get(question_id, "")
    inferred_marks = _infer_question_max_marks(question, rubric_lookup)
    rubric_items = [{
        "description": rubric_text or f"Evaluate answer for question {question_id}",
        "maxMarks": inferred_marks,
    }]
    return {
        "questionId": question_id,
        "questionLabel": question.get("id"),
        "questionText": question.get("text") or question.get("question") or "",
        "context": question.get("context"),
        "maxMarks": inferred_marks,
        "section": question.get("section"),
        "rubric": rubric_items,
    }


def _normalize_id(id_str):
    if not id_str:
        return ""
    # Remove Q, Question, Ans, Answer prefixes, dots, spaces, parens
    s = str(id_str).lower().strip()
    s = re.sub(r"^(q|question|ans|answer)\s*[.\-:]*", "", s, flags=re.IGNORECASE)
    s = re.sub(r"[.\s()\-]", "", s)
    return s


def _to_number(value):
    if isinstance(value, (int, float)):
        number = float(value)
        return int(number) if number.is_integer() else number

    text = str(value or "").strip()
    if not text:
        return 0

    cleaned = text.lower().replace("marks", "").replace("mark", "").strip()
    cleaned = cleaned.strip("[](){}: ")

    if "+" in cleaned:
        parts = [part.strip() for part in cleaned.split("+") if part.strip()]
        try:
            total = sum(float(part) for part in parts)
            return int(total) if total.is_integer() else total
        except (TypeError, ValueError):
            pass

    try:
        number = float(cleaned)
    except (TypeError, ValueError):
        matches = re.findall(r"\d+(?:\.\d+)?", cleaned)
        if not matches:
            return 0
        number = float(matches[0])
    return int(number) if number.is_integer() else number


def _extract_marks_from_text(text):
    text = str(text or "")
    if not text:
        return 0

    combined_match = re.search(
        r"[\[(]\s*(\d+(?:\.\d+)?\s*\+\s*\d+(?:\.\d+)?(?:\s*\+\s*\d+(?:\.\d+)?)*)\s*marks?\s*[\])]",
        text,
        flags=re.IGNORECASE,
    )
    if combined_match:
        return _to_number(combined_match.group(1))

    direct_match = re.search(
        r"(\d+(?:\.\d+)?(?:\s*\+\s*\d+(?:\.\d+)?)*)\s*marks?\b",
        text,
        flags=re.IGNORECASE,
    )
    if direct_match and "+" in direct_match.group(1):
        return _to_number(direct_match.group(1))

    individual_matches = re.findall(r"(\d+(?:\.\d+)?)\s*marks?\b", text, flags=re.IGNORECASE)
    if individual_matches:
        if len(individual_matches) == 1:
            total = float(individual_matches[0])
        else:
            total = sum(float(match) for match in individual_matches)
        return int(total) if total.is_integer() else total
    return 0


def _infer_question_max_marks(question, rubric_lookup):
    explicit_marks = _to_number(question.get("marks"))
    if explicit_marks > 0:
        return explicit_marks

    text_marks = _extract_marks_from_text(question.get("text") or question.get("question"))
    if text_marks > 0:
        return text_marks

    return 0


def _extract_declared_total_marks(question_paper_json):
    if not isinstance(question_paper_json, dict):
        return 0

    total_marks = _to_number(question_paper_json.get("paperTotalMarks"))
    if total_marks > 0:
        return total_marks

    total_marks = _to_number(question_paper_json.get("totalMarks"))
    if total_marks > 0:
        return total_marks

    raw_text = str(question_paper_json.get("raw") or "")
    if raw_text:
        match = re.search(r"\bmaximum\s+marks?\s*[:\-]\s*(\d+(?:\.\d+)?)\b", raw_text, flags=re.IGNORECASE)
        if match:
            return _to_number(match.group(1))
    return 0


def _build_exam_payload(title, subject, question_paper_json, rubrics):
    question_segments = question_paper_json.get("segments", []) if isinstance(question_paper_json, dict) else []
    rubric_lookup = {str(item.get("id")): item.get("rubric", "") for item in rubrics}
    questions = [_question_to_frontend(question, rubric_lookup) for question in question_segments]
    stats = _calculate_exam_display_stats(questions)
    declared_total_marks = _extract_declared_total_marks(question_paper_json)
    return {
        "title": title,
        "subject": subject,
        "questions": questions,
        "totalMarks": declared_total_marks if declared_total_marks > 0 else stats["totalMarks"],
        "extractedTotalMarks": declared_total_marks if declared_total_marks > 0 else stats["totalMarks"],
        "displayQuestionCount": stats["displayQuestionCount"],
        "rubrics": rubrics,
        "questionPaperJson": question_paper_json if isinstance(question_paper_json, dict) else {"segments": question_segments},
    }


def _normalized_question_group(question_id):
    question_id = str(question_id or "").strip()
    lower_id = question_id.lower()
    if not question_id or "visually_impaired" in lower_id:
        return None

    base = question_id.split("_", 1)[0]
    digits = []
    for char in base:
        if char.isdigit():
            digits.append(char)
        else:
            break
    return "".join(digits) or base


def _calculate_exam_display_stats(questions):
    grouped = {}

    for question in questions:
        group_key = _normalized_question_group(question.get("questionId") or question.get("id"))
        if not group_key:
            continue

        question_id = str(question.get("questionId") or question.get("id") or "")
        max_marks = _to_number(question.get("maxMarks") if question.get("maxMarks") is not None else question.get("marks"))

        group = grouped.setdefault(group_key, {"totalMarks": 0, "variantMarks": [], "variantIds": []})

        if "." in question_id:
            group["totalMarks"] += max_marks
        elif question_id and question_id[-1:].lower() in {"a", "b", "c", "d"} and question_id[:-1].isdigit():
            group["variantMarks"].append(max_marks)
            group["variantIds"].append(question_id)
        else:
            suffix = question_id[-1:].lower()
            if suffix.isalpha() and question_id[:-1].isdigit():
                group["variantMarks"].append(max_marks)
                group["variantIds"].append(question_id)
            else:
                group["totalMarks"] += max_marks

    for group in grouped.values():
        if group["variantMarks"]:
            if len(group["variantMarks"]) == 2:
                group["totalMarks"] += max(group["variantMarks"])
            else:
                group["totalMarks"] += sum(group["variantMarks"])

    return {
        "displayQuestionCount": len(grouped),
        "totalMarks": sum(group["totalMarks"] for group in grouped.values()),
    }


def _find_exam_or_404(exam_id, institution_id):
    exam = get_collection("exams").find_one({"_id": ObjectId(exam_id), "institutionId": institution_id})
    if not exam:
        return None, (jsonify({"message": "Exam not found"}), 404)
    return exam, None


def _is_attempted_answer(answer_text):
    text = str(answer_text or "").strip()
    return bool(text) and "not found" not in text.lower()


def _sum_question_marks(questions):
    return round(sum(_to_number(question.get("maxMarks", 0)) for question in questions), 2)


def _count_attempted_results(items):
    return sum(1 for item in items if _is_attempted_answer(item.get("answer")))


def _resolve_total_marks(source, questions=None):
    total_marks = _to_number((source or {}).get("totalMarks"))
    if total_marks > 0:
        return total_marks
    total_marks = _to_number((source or {}).get("extractedTotalMarks"))
    if total_marks > 0:
        return total_marks
    total_marks = _extract_declared_total_marks((source or {}).get("questionPaperJson"))
    if total_marks > 0:
        return total_marks
    return _sum_question_marks(questions or [])


def _recalculate_exam_total_marks(source, questions=None):
    total_marks = _to_number((source or {}).get("extractedTotalMarks"))
    if total_marks > 0:
        return total_marks

    total_marks = _extract_declared_total_marks((source or {}).get("questionPaperJson"))
    if total_marks > 0:
        return total_marks

    return _sum_question_marks(questions or [])


def _resolve_script_exam_total_marks(script):
    exam_id = script.get("examId")
    if exam_id:
        try:
            exam = get_collection("exams").find_one({"_id": ObjectId(exam_id)})
        except Exception:
            exam = None
        total_marks = _resolve_total_marks(exam, (exam or {}).get("questions", []))
        if total_marks > 0:
            return total_marks

    total_marks = _to_number(script.get("examTotalMarks"))
    if total_marks > 0:
        return total_marks
    return _sum_question_marks(script.get("questionsSnapshot", []))


def _exam_list_item(exam):
    return {
        "id": str(exam["_id"]),
        "title": exam.get("title"),
        "subject": exam.get("subject"),
        "status": exam.get("status", "COMPLETED"),
        "totalMarks": _resolve_total_marks(exam, exam.get("questions", [])),
        "displayQuestionCount": exam.get("displayQuestionCount", _calculate_exam_display_stats(exam.get("questions", []))["displayQuestionCount"]),
        "questions": exam.get("questions", []),
        "createdAt": _iso(exam.get("createdAt")),
    }


def _evaluate_answers_for_exam(exam, answer_json_text):
    exam_questions = exam.get("questions", [])
    ids = [question["questionId"] for question in exam_questions]
    answers_list = map_answers(answer_json_text, ids, client)

    mapped_results = []
    for question in exam_questions:
        question_id = _normalize_id(question["questionId"])
        match = next(
            (
                answer
                for answer in answers_list
                if _normalize_id(answer.get("id", "")) == question_id
            ),
            None,
        )
        mapped_results.append(
            {
                "id": question["questionId"],
                "section": question.get("section"),
                "question": question["questionText"],
                "maxMarks": question.get("maxMarks", 0),
                "answer": match.get("answer") if match else "Not found in student script",
            }
        )

    evaluation_input = {"rubrics": exam.get("rubrics", [])}
    evaluated = evaluate_mapped_results(mapped_results, evaluation_input)

    result_items = []
    total_score = 0
    evaluated_count = 0
    review_items = []
    for item in evaluated:
        question_doc = next(
            (question for question in exam_questions if question["questionId"] == str(item.get("id"))),
            None,
        )
        max_marks = question_doc.get("maxMarks", 0) if question_doc else 0
        score = _to_number(item.get("score"))
        total_score += score

        not_found = "not found" in str(item.get("answer", "")).lower()
        if not not_found:
            evaluated_count += 1

        review_recommendation = "NEEDS_REVIEW" if not_found else "AUTO_APPROVED"
        review_reason = "Answer was not confidently mapped to a question." if not_found else "Auto-evaluated from extracted mapping."
        if review_recommendation != "AUTO_APPROVED":
            review_items.append(
                {
                    "questionId": str(item.get("id")),
                    "totalScore": score,
                    "maxScore": max_marks,
                    "reviewRecommendation": review_recommendation,
                    "reviewReason": review_reason,
                    "createdAt": _now(),
                }
            )

        result_items.append(
            {
                "id": str(ObjectId()),
                "runId": str(uuid.uuid4()),
                "scriptId": None,
                "questionId": str(item.get("id")),
                "totalScore": score,
                "maxPossibleScore": max_marks,
                "percentageScore": round((score / max_marks) * 100, 2) if max_marks else 0,
                "reviewRecommendation": review_recommendation,
                "status": "COMPLETE",
                "feedback": item.get("feedback", ""),
                "answer": item.get("answer", ""),
                "questionText": item.get("question", ""),
                "createdAt": _now(),
            }
        )

    exam_total_marks = _resolve_total_marks(exam, exam_questions)
    return {
        "mappedResults": mapped_results,
        "evaluations": result_items,
        "answersList": answers_list,
        "totalScore": total_score,
        "maxPossibleScore": exam_total_marks,
        "examTotalMarks": exam_total_marks,
        "percentageScore": round((total_score / exam_total_marks) * 100, 2) if exam_total_marks else 0,
        "evaluatedCount": evaluated_count,
        "reviewItems": review_items,
    }


def _list_scripts_for_institution(institution_id):
    return list(
        get_collection("uploaded_scripts")
        .find({"institutionId": institution_id})
        .sort("createdAt", -1)
    )


def _dashboard_kpis(institution_id):
    scripts = _list_scripts_for_institution(institution_id)
    today = datetime.now(timezone.utc).date()
    total_today = sum(1 for script in scripts if script.get("createdAt") and script["createdAt"].date() == today)
    complete_scripts = [script for script in scripts if script.get("percentageScore") is not None]
    average_score = (
        round(sum(script.get("percentageScore", 0) for script in complete_scripts) / len(complete_scripts), 2)
        if complete_scripts else 0
    )
    review_size = sum(len(script.get("reviewItems", [])) for script in scripts)
    failed_scripts = sum(1 for script in scripts if script.get("uploadStatus") == "FAILED")
    processing_now = sum(1 for script in scripts if script.get("uploadStatus") in {"UPLOADED", "PROCESSING", "OCR_COMPLETE", "SEGMENTED", "EVALUATING"})
    return {
        "totalUploadsToday": total_today,
        "totalScripts": len(scripts),
        "averageScore": average_score,
        "reviewQueueSize": review_size,
        "failedScripts": failed_scripts,
        "processingNow": processing_now,
    }


def _recent_activity(institution_id):
    state = _activity_state()
    dismissed = set(state.get("dismissed", []))
    clear_before = state.get("clear_before")
    clear_before_dt = _ensure_utc(datetime.fromisoformat(clear_before)) if clear_before else None
    activity = []

    for script in _list_scripts_for_institution(institution_id):
        created_at = _ensure_utc(script.get("createdAt", _now()))
        script_id = str(script["_id"])
        upload_key = f"upload:{script_id}"
        if upload_key not in dismissed and (clear_before_dt is None or created_at > clear_before_dt):
            activity.append(
                {
                    "type": "upload",
                    "id": script_id,
                    "scriptId": script_id,
                    "filename": script.get("originalFilename"),
                    "status": script.get("uploadStatus"),
                    "createdAt": created_at,
                }
            )

        for evaluation in script.get("evaluations", []):
            eval_key = f"evaluation:{evaluation['id']}"
            eval_created = evaluation.get("createdAt", created_at)
            if eval_key in dismissed or (clear_before_dt is not None and eval_created <= clear_before_dt):
                continue
            activity.append(
                {
                    "type": "evaluation",
                    "id": evaluation["id"],
                    "scriptId": script_id,
                    "questionId": evaluation["questionId"],
                    "status": evaluation.get("status", "COMPLETE"),
                    "totalScore": evaluation.get("totalScore", 0),
                    "maxScore": evaluation.get("maxPossibleScore", 0),
                    "createdAt": eval_created,
                }
            )

    activity.sort(key=lambda item: item["createdAt"], reverse=True)
    return [_serialize_doc(item) for item in activity[:20]]


@app.route("/")
def index():
    if os.path.exists(os.path.join(FRONTEND_DIST_DIR, "index.html")):
        return send_from_directory(FRONTEND_DIST_DIR, "index.html")
    return jsonify(
        {
            "message": "Assessment Engine API",
            "frontend": "Run the React app from /frontend with npm run dev",
            "mockDatabase": using_mock_db(),
        }
    )


@app.route("/api/v1/auth/register", methods=["POST"])
def register():
    data = request.get_json(force=True)
    required = ["email", "password", "fullName", "institutionId"]
    missing = [field for field in required if not data.get(field)]
    if missing:
        return jsonify({"message": f"Missing fields: {', '.join(missing)}"}), 400

    users = get_collection("users")
    if users.find_one({"email": data["email"]}):
        return jsonify({"message": "User already exists"}), 409

    now = _now()
    password_hash = bcrypt.hashpw(data["password"].encode(), bcrypt.gensalt()).decode()
    user_doc = {
        "email": data["email"],
        "passwordHash": password_hash,
        "fullName": data["fullName"],
        "institutionId": data["institutionId"],
        "role": data.get("role", "INSTITUTION_ADMIN"),
        "isActive": True,
        "createdAt": now,
        "updatedAt": now,
    }
    inserted = users.insert_one(user_doc)
    return jsonify({"message": "User registered successfully", "userId": str(inserted.inserted_id)}), 201


@app.route("/api/v1/auth/login", methods=["POST"])
def login():
    data = request.get_json(force=True)
    users = get_collection("users")
    user = users.find_one({"email": data.get("email")})
    if not user:
        return jsonify({"message": "Invalid credentials"}), 401
    if not bcrypt.checkpw(data.get("password", "").encode(), user["passwordHash"].encode()):
        return jsonify({"message": "Invalid credentials"}), 401
    if not user.get("isActive", True):
        return jsonify({"message": "Account is deactivated"}), 401

    identity = str(user["_id"])
    claims = {
        "institution_id": user["institutionId"],
        "role": user["role"],
        "email": user["email"],
    }
    access_token = create_access_token(identity=identity, additional_claims=claims)
    refresh_token = create_refresh_token(identity=identity, additional_claims=claims)
    return jsonify(
        {
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
    )


@app.route("/api/v1/auth/refresh", methods=["POST"])
@flask_jwt_required(refresh=True)
def refresh():
    identity = get_jwt_identity()
    user = get_collection("users").find_one({"_id": ObjectId(identity)})
    if not user:
        return jsonify({"message": "User not found"}), 404
    claims = {
        "institution_id": user["institutionId"],
        "role": user["role"],
        "email": user["email"],
    }
    return jsonify({"accessToken": create_access_token(identity=identity, additional_claims=claims)})


@app.route("/api/v1/auth/me", methods=["GET"])
@jwt_required
def me():
    user = get_collection("users").find_one({"_id": ObjectId(get_current_user_id())})
    if not user:
        return jsonify({"message": "User not found"}), 404
    return jsonify(
        {
            "id": str(user["_id"]),
            "email": user["email"],
            "fullName": user["fullName"],
            "role": user["role"],
            "institutionId": user["institutionId"],
        }
    )


@app.route("/api/v1/dashboard/kpis", methods=["GET"])
@jwt_required
def dashboard_kpis():
    return jsonify(_dashboard_kpis(get_current_institution_id()))


@app.route("/api/v1/dashboard/recent-activity", methods=["GET", "POST"])
@jwt_required
def dashboard_recent_activity():
    if request.method == "GET":
        return jsonify({"activity": _recent_activity(get_current_institution_id())})

    state = _activity_state()
    data = request.get_json(force=True)
    state["dismissed"].append(f"{data.get('type')}:{data.get('id')}")
    _save_activity_state(state)
    return jsonify({"message": "Dismissed"})


@app.route("/api/v1/dashboard/recent-activity/clear", methods=["POST"])
@jwt_required
def dashboard_clear_activity():
    state = _activity_state()
    state["clear_before"] = _now().isoformat()
    _save_activity_state(state)
    return jsonify({"message": "Cleared"})


@app.route("/api/v1/dashboard/review-queue", methods=["GET"])
@jwt_required
def dashboard_review_queue():
    institution_id = get_current_institution_id()
    items = []
    for script in _list_scripts_for_institution(institution_id):
        for review_item in script.get("reviewItems", []):
            items.append(
                {
                    "id": f"{script['_id']}:{review_item['questionId']}",
                    "scriptId": str(script["_id"]),
                    "questionId": review_item["questionId"],
                    "totalScore": review_item["totalScore"],
                    "maxScore": review_item["maxScore"],
                    "reviewRecommendation": review_item["reviewRecommendation"],
                    "reviewReason": review_item["reviewReason"],
                    "createdAt": review_item["createdAt"],
                }
            )
    items.sort(key=lambda item: item["createdAt"], reverse=True)
    return jsonify({"items": [_serialize_doc(item) for item in items], "total": len(items)})


@app.route("/api/v1/exams/", methods=["GET"])
@jwt_required
def list_exams():
    exams = list(
        get_collection("exams")
        .find({"institutionId": get_current_institution_id()})
        .sort("createdAt", -1)
    )
    items = [_exam_list_item(exam) for exam in exams]
    return jsonify({"items": items, "total": len(items)})


@app.route("/api/v1/exams/<exam_id>", methods=["GET", "DELETE"])
@jwt_required
def exam_detail(exam_id):
    institution_id = get_current_institution_id()
    exam, error = _find_exam_or_404(exam_id, institution_id)
    if error:
        return error
    if request.method == "GET":
        payload = _serialize_doc(exam)
        stats = _calculate_exam_display_stats(exam.get("questions", []))
        payload["totalMarks"] = stats["totalMarks"]
        payload["displayQuestionCount"] = stats["displayQuestionCount"]
        return jsonify(payload)

    get_collection("exams").delete_one({"_id": exam["_id"]})
    get_collection("uploaded_scripts").delete_many({"examId": exam_id, "institutionId": institution_id})
    return jsonify({"message": "Exam deleted"})


@app.route("/api/v1/exams/", methods=["POST"])
@jwt_required
def create_exam_manual():
    data = request.get_json(force=True)
    now = _now()
    questions = data.get("questions", [])
    normalized_questions = []
    rubrics = []
    for idx, question in enumerate(questions, start=1):
        question_id = question.get("questionLabel") or f"Q{idx}"
        max_marks = _to_number(question.get("maxMarks"))
        normalized_questions.append(
            {
                "questionId": question_id,
                "questionLabel": question_id,
                "questionText": question.get("questionText", ""),
                "maxMarks": max_marks,
                "section": question.get("section"),
                "rubric": question.get("rubric", []),
            }
        )
        rubric_text = " ".join(
            f"{item.get('description', '')} ({item.get('maxMarks', 0)} marks)."
            for item in question.get("rubric", [])
        )
        rubrics.append({"id": question_id, "rubric": rubric_text})

    stats = _calculate_exam_display_stats(normalized_questions)

    exam_doc = {
        "institutionId": get_current_institution_id(),
        "createdBy": get_current_user_id(),
        "title": data.get("title", "Untitled Exam"),
        "subject": data.get("subject", "General"),
        "questions": normalized_questions,
        "rubrics": rubrics,
        "totalMarks": stats["totalMarks"],
        "displayQuestionCount": stats["displayQuestionCount"],
        "createdAt": now,
        "updatedAt": now,
    }
    inserted = get_collection("exams").insert_one(exam_doc)
    exam_doc["_id"] = inserted.inserted_id
    return jsonify(
        {
            "examId": str(inserted.inserted_id),
            "totalMarks": stats["totalMarks"],
            "exam": _exam_list_item(exam_doc),
        }
    ), 201


def _run_single_exam_processing(file_content, filename, institution_id, created_by, title=None, subject=None, exam_id=None):
    with app.app_context():
        mime_type = "application/pdf" if filename.lower().endswith(".pdf") else "image/png"
        question_json_text = _extract_bytes_to_json(file_content, mime_type, filename, "question")
        question_json = json.loads(question_json_text)
        rubrics_json_text = generate_rubrics_from_json(question_json_text)
        rubrics_json = json.loads(rubrics_json_text)

        if not title:
            title = filename.rsplit(".", 1)[0]
        if not subject:
            subject = (question_json.get("segments", [{}])[0].get("section") or "General")
        exam_payload = _build_exam_payload(title, subject, question_json, rubrics_json.get("rubrics", []))
        
        now = _now()
        data_to_set = {
            "institutionId": institution_id,
            "createdBy": created_by,
            **exam_payload,
            "status": "COMPLETED",
            "updatedAt": now,
        }
        
        if exam_id:
            get_collection("exams").update_one(
                {"_id": ObjectId(exam_id)},
                {"$set": data_to_set}
            )
            final_id = exam_id
        else:
            data_to_set["createdAt"] = now
            inserted = get_collection("exams").insert_one(data_to_set)
            final_id = str(inserted.inserted_id)

        # Re-fetch for return (None if DB split: API on real MongoDB, worker on mongomock)
        exam_doc = get_collection("exams").find_one({"_id": ObjectId(final_id)})
        if not exam_doc:
            return {
                "status": "FAILED",
                "entityId": final_id,
                "error": (
                    "Exam record not found after save. Celery must use the same MongoDB as the API "
                    "(fix Atlas connectivity; set ALLOW_MOCK_DB_FALLBACK=false to surface connection errors)."
                ),
            }
        return {
            "status": "SUCCESS",
            "entityId": final_id,
            "exam": _exam_list_item(exam_doc)
        }

@app.route("/api/v1/exams/upload", methods=["POST"])
@jwt_required
def upload_exam():
    question_paper = request.files.get("questionPaper") or request.files.get("file")
    if not question_paper:
        return jsonify({"error": {"message": "questionPaper (or 'file') is required"}}), 400

    try:
        title = request.form.get("title") or question_paper.filename.rsplit(".", 1)[0]
        subject = request.form.get("subject") or "General"
        institution_id = get_current_institution_id()
        created_by = get_current_user_id()
        
        # Create a "PROCESSING" record immediately so it shows up on the Exams page
        now = _now()
        exam_placeholder = {
            "institutionId": institution_id,
            "createdBy": created_by,
            "title": title,
            "subject": subject,
            "status": "PROCESSING",
            "questions": [],
            "rubrics": [],
            "totalMarks": 0,
            "createdAt": now,
            "updatedAt": now
        }
        inserted = get_collection("exams").insert_one(exam_placeholder)
        exam_id = str(inserted.inserted_id)

        job_id = BatchManager.create_job("EXAM_BATCH", institution_id, created_by)
        
        process_exam_task.delay(
            job_id, 
            question_paper.read(), 
            institution_id, 
            created_by, 
            title=title, 
            subject=subject,
            exam_id=exam_id
        )

        return jsonify({
            "jobId": job_id, 
            "examId": exam_id,
            "status": "PENDING", 
            "message": "Exam processing started in background"
        })
    except Exception as exc:
        traceback.print_exc()
        return jsonify({"error": {"message": str(exc)}}), 500


@app.route("/api/v1/exams/<exam_id>/questions", methods=["POST"])
@jwt_required
def add_exam_question(exam_id):
    institution_id = get_current_institution_id()
    exam, error = _find_exam_or_404(exam_id, institution_id)
    if error:
        return error
    data = request.get_json(force=True)
    question_id = data.get("questionLabel") or f"Q{len(exam.get('questions', [])) + 1}"
    question = {
        "questionId": question_id,
        "questionLabel": question_id,
        "questionText": data.get("questionText", ""),
        "maxMarks": _to_number(data.get("maxMarks")),
        "rubric": data.get("rubric", []),
    }
    exam["questions"].append(question)
    stats = _calculate_exam_display_stats(exam["questions"])
    exam["totalMarks"] = _recalculate_exam_total_marks(exam, exam["questions"])
    exam["displayQuestionCount"] = stats["displayQuestionCount"]
    exam["rubrics"].append(
        {
            "id": question_id,
            "rubric": " ".join(
                f"{item.get('description', '')} ({item.get('maxMarks', 0)} marks)."
                for item in question["rubric"]
            ),
        }
    )
    get_collection("exams").update_one(
        {"_id": exam["_id"]},
        {"$set": {"questions": exam["questions"], "rubrics": exam["rubrics"], "totalMarks": exam["totalMarks"], "displayQuestionCount": exam["displayQuestionCount"], "updatedAt": _now()}},
    )
    return jsonify({"message": "Question added", "examId": exam_id, "questionId": question_id, "question": question})


@app.route("/api/v1/exams/<exam_id>/questions/<question_id>", methods=["PATCH"])
@jwt_required
def update_exam_question(exam_id, question_id):
    institution_id = get_current_institution_id()
    exam, error = _find_exam_or_404(exam_id, institution_id)
    if error:
        return error
    data = request.get_json(force=True)
    for question in exam.get("questions", []):
        if str(question.get("questionId")) == question_id:
            if data.get("questionText") is not None:
                question["questionText"] = data["questionText"]
            if data.get("maxMarks") is not None:
                question["maxMarks"] = _to_number(data["maxMarks"])
            if data.get("rubric") is not None:
                question["rubric"] = data["rubric"]
    for rubric in exam.get("rubrics", []):
        if str(rubric.get("id")) == question_id and data.get("rubric") is not None:
            rubric["rubric"] = " ".join(
                f"{item.get('description', '')} ({item.get('maxMarks', 0)} marks)."
                for item in data["rubric"]
            )
    stats = _calculate_exam_display_stats(exam["questions"])
    exam["totalMarks"] = _recalculate_exam_total_marks(exam, exam["questions"])
    exam["displayQuestionCount"] = stats["displayQuestionCount"]
    get_collection("exams").update_one(
        {"_id": exam["_id"]},
        {"$set": {"questions": exam["questions"], "rubrics": exam["rubrics"], "totalMarks": exam["totalMarks"], "displayQuestionCount": exam["displayQuestionCount"], "updatedAt": _now()}},
    )
    return jsonify({"message": "Question updated"})


@app.route("/api/v1/uploads/", methods=["GET"])
@jwt_required
def list_uploads():
    institution_id = get_current_institution_id()
    exam_id = request.args.get("examId")
    page = int(request.args.get("page", 1))
    per_page = int(request.args.get("perPage", 20))
    query = {"institutionId": institution_id}
    if exam_id:
        query["examId"] = exam_id
    collection = get_collection("uploaded_scripts")
    total = collection.count_documents(query)
    items = list(
        collection.find(query).sort("createdAt", -1).skip((page - 1) * per_page).limit(per_page)
    )
    return jsonify({"items": [_serialize_doc(item) for item in items], "total": total, "page": page, "perPage": per_page})


@app.route("/api/v1/uploads/<uploaded_script_id>", methods=["GET", "DELETE"])
@jwt_required
def upload_detail(uploaded_script_id):
    institution_id = get_current_institution_id()
    collection = get_collection("uploaded_scripts")
    script = collection.find_one({"_id": ObjectId(uploaded_script_id), "institutionId": institution_id})
    if not script:
        return jsonify({"message": "Uploaded script not found"}), 404
    if request.method == "GET":
        return jsonify(_serialize_doc(script))
    collection.delete_one({"_id": script["_id"]})
    return jsonify({"message": "Deleted"})


def _store_uploaded_script(exam, filename, mime_type, file_size, student_name, student_roll, answer_json_text, institution_id=None, created_by=None):
    evaluation_bundle = _evaluate_answers_for_exam(exam, answer_json_text)
    now = _now()
    upload_status = "IN_REVIEW" if evaluation_bundle["reviewItems"] else "EVALUATED"

    # Use provided IDs or fall back to globals (for request-context calls)
    inst_id = institution_id or get_current_institution_id()
    user_id = created_by or get_current_user_id()

    script_doc = {
        "institutionId": inst_id,
        "createdBy": user_id,
        "examId": str(exam["_id"]),
        "uploadBatchId": str(uuid.uuid4()),
        "studentMeta": {"name": student_name or "Unknown Student", "rollNo": student_roll or ""},
        "originalFilename": filename,
        "mimeType": mime_type,
        "fileSizeBytes": file_size,
        "pageCount": None,
        "uploadStatus": upload_status,
        "failureReason": None,
        "scriptId": None,
        "createdAt": now,
        "updatedAt": now,
        "answerScriptJson": answer_json_text,
        "mappedResults": evaluation_bundle["mappedResults"],
        "evaluations": evaluation_bundle["evaluations"],
        "reviewItems": evaluation_bundle["reviewItems"],
        "totalScore": evaluation_bundle["totalScore"],
        "maxPossibleScore": evaluation_bundle["maxPossibleScore"],
        "examTotalMarks": evaluation_bundle["examTotalMarks"],
        "percentageScore": evaluation_bundle["percentageScore"],
        "evaluatedCount": evaluation_bundle["evaluatedCount"],
        "questionsSnapshot": [
            {
                "questionId": question["questionId"],
                "questionText": question["questionText"],
                "maxMarks": question["maxMarks"],
            }
            for question in exam.get("questions", [])
        ],
    }
    inserted = get_collection("uploaded_scripts").insert_one(script_doc)
    get_collection("uploaded_scripts").update_one({"_id": inserted.inserted_id}, {"$set": {"scriptId": str(inserted.inserted_id)}})
    script_doc["_id"] = inserted.inserted_id
    script_doc["scriptId"] = str(inserted.inserted_id)
    return script_doc


def _create_pending_uploaded_script(exam, filename, mime_type, file_size, student_name, student_roll, institution_id=None, created_by=None):
    now = _now()
    
    # Use provided IDs or fall back to globals (for request-context calls)
    inst_id = institution_id or get_current_institution_id()
    user_id = created_by or get_current_user_id()

    script_doc = {
        "institutionId": inst_id,
        "createdBy": user_id,
        "examId": str(exam["_id"]),
        "uploadBatchId": str(uuid.uuid4()),
        "studentMeta": {"name": student_name or "Unknown Student", "rollNo": student_roll or ""},
        "originalFilename": filename,
        "mimeType": mime_type,
        "fileSizeBytes": file_size,
        "pageCount": None,
        "uploadStatus": "UPLOADED",
        "failureReason": None,
        "scriptId": None,
        "createdAt": now,
        "updatedAt": now,
        "answerScriptJson": json.dumps({"segments": []}),
        "mappedResults": [],
        "evaluations": [],
        "reviewItems": [],
        "totalScore": None,
        "maxPossibleScore": None,
        "percentageScore": None,
        "questionsSnapshot": [
            {
                "questionId": question["questionId"],
                "questionText": question["questionText"],
                "maxMarks": question["maxMarks"],
            }
            for question in exam.get("questions", [])
        ],
    }
    inserted = get_collection("uploaded_scripts").insert_one(script_doc)
    get_collection("uploaded_scripts").update_one(
        {"_id": inserted.inserted_id},
        {"$set": {"scriptId": str(inserted.inserted_id)}},
    )
    script_doc["_id"] = inserted.inserted_id
    script_doc["scriptId"] = str(inserted.inserted_id)
    return script_doc


def _process_uploaded_script(uploaded_script_id, exam, raw_bytes, mime_type, filename, institution_id=None, created_by=None):
    with app.app_context():
        scripts = get_collection("uploaded_scripts")
        script_object_id = ObjectId(uploaded_script_id)
        try:
            scripts.update_one(
                {"_id": script_object_id},
                {"$set": {"uploadStatus": "PROCESSING", "updatedAt": _now(), "failureReason": None}},
            )

            answer_json_text = _extract_bytes_to_json(raw_bytes, mime_type, filename, "answer")
            answer_json = json.loads(answer_json_text)
            _write_json("answer_script.json", answer_json)

            scripts.update_one(
                {"_id": script_object_id},
                {
                    "$set": {
                        "answerScriptJson": answer_json_text,
                        "uploadStatus": "OCR_COMPLETE",
                        "updatedAt": _now(),
                    }
                },
            )

            scripts.update_one(
                {"_id": script_object_id},
                {"$set": {"uploadStatus": "SEGMENTED", "updatedAt": _now()}},
            )

            scripts.update_one(
                {"_id": script_object_id},
                {"$set": {"uploadStatus": "EVALUATING", "updatedAt": _now()}},
            )
            evaluation_bundle = _evaluate_answers_for_exam(exam, answer_json_text)
            upload_status = "IN_REVIEW" if evaluation_bundle["reviewItems"] else "EVALUATED"

            for item in evaluation_bundle["evaluations"]:
                item["scriptId"] = uploaded_script_id

            scripts.update_one(
                {"_id": script_object_id},
                {
                    "$set": {
                        "mappedResults": evaluation_bundle["mappedResults"],
                        "evaluations": evaluation_bundle["evaluations"],
                        "reviewItems": evaluation_bundle["reviewItems"],
                        "totalScore": evaluation_bundle["totalScore"],
                        "maxPossibleScore": evaluation_bundle["maxPossibleScore"],
                        "examTotalMarks": evaluation_bundle["examTotalMarks"],
                        "percentageScore": evaluation_bundle["percentageScore"],
                        "evaluatedCount": evaluation_bundle["evaluatedCount"],
                        "uploadStatus": upload_status,
                        "updatedAt": _now(),
                    }
                },
            )
        except Exception as exc:
            traceback.print_exc()
            scripts.update_one(
                {"_id": script_object_id},
                {
                    "$set": {
                        "uploadStatus": "FAILED",
                        "failureReason": str(exc),
                        "updatedAt": _now(),
                    }
                },
            )


def _run_single_script_processing(raw_bytes, filename, exam_id, institution_id, created_by, student_name=None, student_roll=None):
    with app.app_context():
        # Fetch exam first to ensure it exists
        exam = get_collection("exams").find_one({"_id": ObjectId(exam_id)})
        if not exam:
            return {"filename": filename, "status": "FAILED", "error": f"Exam {exam_id} not found"}
        now = _now()
        mime_type = "application/pdf" if filename.lower().endswith(".pdf") else "image/png"
        script_doc = _create_pending_uploaded_script(
            exam,
            filename,
            mime_type,
            len(raw_bytes),
            student_name,
            student_roll,
            institution_id=institution_id,
            created_by=created_by
        )
        # Background processing equivalent to _process_uploaded_script but synchronous here (BatchManager handles threading)
        _process_uploaded_script(str(script_doc["_id"]), exam, raw_bytes, mime_type, filename, institution_id=institution_id, created_by=created_by)
        
        return {
            "status": "SUCCESS",
            "entityId": str(script_doc["_id"]),
            "script": _serialize_doc(script_doc)
        }

@app.route("/api/v1/uploads/", methods=["POST"])
@jwt_required
def upload_scripts():
    exam_id = request.form.get("examId")
    if not exam_id:
        return jsonify({"error": {"message": "examId is required"}}), 400
    
    institution_id = get_current_institution_id()
    created_by = get_current_user_id()
    
    _find_exam_or_404(exam_id, institution_id) # validation

    files = request.files.getlist("files")
    if not files:
        return jsonify({"error": {"message": "At least one file is required"}}), 400

    try:
        job_id = BatchManager.create_job("SCRIPT_BATCH", institution_id, created_by, total_files=len(files))
        
        for file_storage in files:
            process_script_task.delay(
                job_id, 
                file_storage.read(), 
                file_storage.filename, 
                exam_id, 
                institution_id, 
                created_by
            )

        return jsonify({
            "jobId": job_id, 
            "status": "PENDING", 
            "message": "Script processing started in background"
        })
    except Exception as exc:
        traceback.print_exc()
        return jsonify({"error": {"message": str(exc)}}), 500


@app.route("/api/v1/uploads/typed", methods=["POST"])
@jwt_required
def upload_typed_answers():
    data = request.get_json(force=True)
    exam, error = _find_exam_or_404(data.get("examId"), get_current_institution_id())
    if error:
        return error

    segments = []
    for answer in data.get("answers", []):
        if answer.get("answerText", "").strip():
            segments.append({"id": answer.get("questionId"), "section": "", "text": answer.get("answerText")})
    answer_json_text = json.dumps({"segments": segments}, ensure_ascii=False)
    script_doc = _store_uploaded_script(
        exam,
        "typed-answer.txt",
        "text/plain",
        len(answer_json_text.encode()),
        data.get("studentName"),
        data.get("studentRollNo"),
        answer_json_text,
    )
    return jsonify(
        {
            "message": "Typed answer submitted",
            "uploadedScriptId": str(script_doc["_id"]),
            "scriptId": str(script_doc["_id"]),
            "questionCount": len(exam.get("questions", [])),
            "evaluatingCount": len(segments),
        }
    )


@app.route("/api/v1/evaluation/list", methods=["GET"])
@jwt_required
def evaluation_list():
    institution_id = get_current_institution_id()
    scripts = _list_scripts_for_institution(institution_id)
    items = []
    for script in scripts:
        exam_total_marks = _resolve_script_exam_total_marks(script)
        items.append(
            {
                "scriptId": str(script["_id"]),
                "examId": script.get("examId"),
                "studentMeta": script.get("studentMeta", {}),
                "status": script.get("uploadStatus"),
                "totalScore": script.get("totalScore", 0),
                "maxPossibleScore": exam_total_marks,
                "examTotalMarks": exam_total_marks,
                "percentageScore": script.get("percentageScore", 0),
                "questionCount": len(script.get("questionsSnapshot", [])),
                "evaluatedCount": script.get("evaluatedCount", _count_attempted_results(script.get("mappedResults", []))),
                "needsReview": bool(script.get("reviewItems")),
                "createdAt": _iso(script.get("createdAt")),
            }
        )
    return jsonify({"items": items, "total": len(items), "page": 1, "perPage": len(items) or 1})


@app.route("/api/v1/evaluation/scripts/<script_id>", methods=["GET"])
@jwt_required
def evaluation_script(script_id):
    institution_id = get_current_institution_id()
    script = get_collection("uploaded_scripts").find_one({"_id": ObjectId(script_id), "institutionId": institution_id})
    if not script:
        return jsonify({"message": "Script not found"}), 404
    exam_total_marks = _resolve_script_exam_total_marks(script)
    payload = {
        "scriptId": str(script["_id"]),
        "studentMeta": script.get("studentMeta", {}),
        "status": script.get("uploadStatus"),
        "totalScore": script.get("totalScore", 0),
        "maxPossibleScore": exam_total_marks,
        "examTotalMarks": exam_total_marks,
        "percentageScore": script.get("percentageScore", 0),
        "questionCount": len(script.get("questionsSnapshot", [])),
        "evaluatedCount": script.get("evaluatedCount", _count_attempted_results(script.get("mappedResults", []))),
        "answers": [
            {"questionId": item.get("id"), "text": item.get("answer")}
            for item in script.get("mappedResults", [])
        ],
        "questions": script.get("questionsSnapshot", []),
        "evaluations": script.get("evaluations", []),
    }
    return jsonify(_serialize_doc(payload))


@app.route("/api/v1/evaluation/scripts/<script_id>", methods=["DELETE"])
@jwt_required
def delete_evaluation_script(script_id):
    institution_id = get_current_institution_id()
    collection = get_collection("uploaded_scripts")
    script = collection.find_one({"_id": ObjectId(script_id), "institutionId": institution_id})
    if not script:
        return jsonify({"message": "Script not found"}), 404
    collection.delete_one({"_id": script["_id"]})
    return jsonify({"message": "Deleted", "scriptId": script_id})


@app.route("/api/v1/evaluation/scripts/<script_id>/re-evaluate", methods=["POST"])
@jwt_required
def re_evaluate(script_id):
    institution_id = get_current_institution_id()
    scripts = get_collection("uploaded_scripts")
    script = scripts.find_one({"_id": ObjectId(script_id), "institutionId": institution_id})
    if not script:
        return jsonify({"message": "Script not found"}), 404
    exam, error = _find_exam_or_404(script.get("examId"), institution_id)
    if error:
        return error
    evaluation_bundle = _evaluate_answers_for_exam(exam, script.get("answerScriptJson", json.dumps({"segments": []})))
    upload_status = "IN_REVIEW" if evaluation_bundle["reviewItems"] else "EVALUATED"
    scripts.update_one(
        {"_id": script["_id"]},
        {
            "$set": {
                "mappedResults": evaluation_bundle["mappedResults"],
                "evaluations": evaluation_bundle["evaluations"],
                "reviewItems": evaluation_bundle["reviewItems"],
                "totalScore": evaluation_bundle["totalScore"],
                "maxPossibleScore": evaluation_bundle["maxPossibleScore"],
                "examTotalMarks": evaluation_bundle["examTotalMarks"],
                "percentageScore": evaluation_bundle["percentageScore"],
                "evaluatedCount": evaluation_bundle["evaluatedCount"],
                "uploadStatus": upload_status,
                "updatedAt": _now(),
            }
        },
    )
    return jsonify({"message": "Re-evaluation started", "scriptId": script_id})


@app.route("/api/v1/evaluation/results/<result_id>/override", methods=["DELETE"])
@jwt_required
def delete_evaluation_result(result_id):
    institution_id = get_current_institution_id()
    scripts = get_collection("uploaded_scripts")

    script = None
    evaluation_id = None
    question_id = None

    if ":" in result_id:
        script_id, question_id = result_id.split(":", 1)
        script = scripts.find_one({"_id": ObjectId(script_id), "institutionId": institution_id})
    else:
        script = scripts.find_one(
            {
                "institutionId": institution_id,
                "evaluations.id": result_id,
            }
        )
        evaluation_id = result_id

    if not script:
        return jsonify({"message": "Evaluation not found"}), 404

    evaluations = list(script.get("evaluations", []))
    review_items = list(script.get("reviewItems", []))

    if evaluation_id:
        matched_evaluation = next((item for item in evaluations if str(item.get("id")) == evaluation_id), None)
        if not matched_evaluation:
            return jsonify({"message": "Evaluation not found"}), 404
        question_id = str(matched_evaluation.get("questionId"))
        evaluations = [item for item in evaluations if str(item.get("id")) != evaluation_id]
    else:
        matched_evaluation = next((item for item in evaluations if str(item.get("questionId")) == str(question_id)), None)
        if not matched_evaluation and not any(str(item.get("questionId")) == str(question_id) for item in review_items):
            return jsonify({"message": "Evaluation not found"}), 404
        evaluations = [item for item in evaluations if str(item.get("questionId")) != str(question_id)]

    review_items = [item for item in review_items if str(item.get("questionId")) != str(question_id)]

    total_score = round(sum(_to_number(item.get("totalScore")) for item in evaluations), 2)
    exam_total_marks = _resolve_script_exam_total_marks(script)
    max_possible_score = exam_total_marks
    percentage_score = round((total_score / exam_total_marks) * 100, 2) if exam_total_marks else 0
    upload_status = "IN_REVIEW" if review_items else "EVALUATED"
    evaluated_count = _count_attempted_results(evaluations)

    scripts.update_one(
        {"_id": script["_id"]},
        {
            "$set": {
                "evaluations": evaluations,
                "reviewItems": review_items,
                "totalScore": total_score,
                "maxPossibleScore": max_possible_score,
                "percentageScore": percentage_score,
                "evaluatedCount": evaluated_count,
                "uploadStatus": upload_status,
                "updatedAt": _now(),
            }
        },
    )

    return jsonify({"message": "Evaluation deleted", "scriptId": str(script["_id"]), "questionId": question_id})


@app.route("/api/v1/ocr/scripts/<script_id>/pages", methods=["GET"])
@jwt_required
def ocr_pages(script_id):
    script = get_collection("uploaded_scripts").find_one({"_id": ObjectId(script_id), "institutionId": get_current_institution_id()})
    if not script:
        return jsonify({"message": "Script not found"}), 404
    answer_json = json.loads(script.get("answerScriptJson", "{\"segments\": []}"))
    combined_text = "\n\n".join(segment.get("text", "") for segment in answer_json.get("segments", []))
    return jsonify(
        {
            "scriptId": script_id,
            "pageCount": 1,
            "pages": [
                {
                    "id": f"{script_id}:1",
                    "uploadedScriptId": script_id,
                    "pageNumber": 1,
                    "extractedText": combined_text,
                    "confidenceScore": 0.85,
                    "qualityFlags": [],
                    "provider": "mistral",
                    "processingMs": 0,
                }
            ],
        }
    )


@app.route("/api/v1/ocr/scripts/<script_id>/re-segment", methods=["POST"])
@jwt_required
def re_segment_script(script_id):
    institution_id = get_current_institution_id()
    scripts = get_collection("uploaded_scripts")
    script = scripts.find_one({"_id": ObjectId(script_id), "institutionId": institution_id})
    if not script:
        return jsonify({"message": "Script not found"}), 404
    
    exam, error = _find_exam_or_404(script.get("examId"), institution_id)
    if error:
        return error
    
    # We trigger the full evaluation pipeline again which includes segmentation matching
    evaluation_bundle = _evaluate_answers_for_exam(exam, script.get("answerScriptJson", json.dumps({"segments": []})))
    upload_status = "IN_REVIEW" if evaluation_bundle["reviewItems"] else "EVALUATED"
    
    scripts.update_one(
        {"_id": script["_id"]},
        {
            "$set": {
                "mappedResults": evaluation_bundle["mappedResults"],
                "evaluations": evaluation_bundle["evaluations"],
                "reviewItems": evaluation_bundle["reviewItems"],
                "totalScore": evaluation_bundle["totalScore"],
                "maxPossibleScore": evaluation_bundle["maxPossibleScore"],
                "examTotalMarks": evaluation_bundle["examTotalMarks"],
                "percentageScore": evaluation_bundle["percentageScore"],
                "evaluatedCount": evaluation_bundle["evaluatedCount"],
                "uploadStatus": upload_status,
                "updatedAt": _now(),
            }
        },
    )
    return jsonify({"message": "Re-segmentation and evaluation completed", "scriptId": script_id})


@app.route("/api/v1/ocr/scripts/<script_id>/re-run-ocr", methods=["POST"])
@jwt_required
def re_run_ocr(script_id):
    institution_id = get_current_institution_id()
    scripts = get_collection("uploaded_scripts")
    script = scripts.find_one({"_id": ObjectId(script_id), "institutionId": institution_id})
    if not script:
        return jsonify({"message": "Script not found"}), 404
    
    # In a real scenario, this would trigger OCR again. 
    # For now, we reuse the current answerScriptJson but re-run everything from that point.
    return re_evaluate(script_id)


@app.route("/api/v1/evaluation/scripts/<script_id>/stop", methods=["POST"])
@jwt_required
def stop_evaluation(script_id):
    return jsonify({"message": "Stopped"})


@app.route("/api/v1/ocr/scripts/<script_id>/signed-url", methods=["GET"])
@jwt_required
def get_script_signed_url(script_id):
    # Mocking signed URL for now
    return jsonify({"signedUrl": f"http://localhost:5001/api/v1/ocr/scripts/{script_id}/pages", "expiresIn": 3600})


@app.route("/api/v1/ocr/scripts/<script_id>/pages/<int:page_number>", methods=["PUT"])
@jwt_required
def update_ocr_page(script_id, page_number):
    data = request.get_json(force=True)
    # logic to update page text for correction would go here
    return jsonify({"message": "Page updated"})


@app.route("/api/v1/evaluation/scripts/<script_id>/answers/<question_id>", methods=["PUT"])
@jwt_required
def add_missed_answer(script_id, question_id):
    data = request.get_json(force=True)
    scripts = get_collection("uploaded_scripts")
    script = scripts.find_one({"_id": ObjectId(script_id)})
    if not script:
        return jsonify({"message": "Script not found"}), 404
    
    # Logic to manually add/update an answer would go here
    return jsonify({"message": "Answer updated", "scriptId": script_id, "questionId": question_id, "runId": str(uuid.uuid4())})


@app.route("/api/v1/evaluation/export", methods=["GET"])
@jwt_required
def export_evaluation_results():
    # Mocking CSV export for now
    import io
    import csv
    from flask import Response
    
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["Student Name", "Roll No", "Total Score", "Max Marks", "Percentage"])
    
    scripts = list(get_collection("uploaded_scripts").find({"institutionId": get_current_institution_id()}))
    for script in scripts:
        meta = script.get("studentMeta", {})
        writer.writerow([
            meta.get("name", ""),
            meta.get("rollNo", ""),
            script.get("totalScore", 0),
            script.get("maxPossibleScore", 0),
            script.get("percentageScore", 0)
        ])
    
    return Response(
        output.getvalue(),
        mimetype="text/csv",
        headers={"Content-disposition": "attachment; filename=results.csv"}
    )


@app.route("/api/v1/ocr/test", methods=["POST"])
@jwt_required
def ocr_test():
    file_storage = request.files.get("file")
    if not file_storage:
        return jsonify({"message": "file is required"}), 400
    try:
        answer_json_text = _extract_file_to_json(file_storage, "answer")
        answer_json = json.loads(answer_json_text)
        extracted_text = "\n\n".join(segment.get("text", "") for segment in answer_json.get("segments", []))
        return jsonify({"text": extracted_text})
    except Exception as exc:
        return jsonify({"message": str(exc)}), 500


@app.route("/exam-status", methods=["GET"])
def exam_status():
    question_json = _load_json("question_paper.json", {"segments": []})
    rubrics_json = _load_json("rubrics.json", {"rubrics": []})
    answer_json = _load_json("answer_script.json", {"segments": []})
    question_segments = question_json.get("segments", [])
    stats = _calculate_exam_display_stats(question_segments)
    return jsonify(
        {
            "has_question_paper": bool(question_segments),
            "has_answer_script": bool(answer_json.get("segments", [])),
            "has_rubrics": bool(rubrics_json.get("rubrics", [])),
            "question_segments": question_segments,
            "exam": {
                "title": question_segments[0].get("section", "Current") + " Section Exam" if question_segments else "No exam created",
                "subject": question_segments[0].get("subject") if question_segments else None,
                "question_count": stats["displayQuestionCount"],
                "total_marks": stats["totalMarks"],
            },
            "summary": {
                "rubric_count": len(rubrics_json.get("rubrics", [])),
                "mapped_answer_count": len(answer_json.get("segments", [])),
            },
        }
    )


@app.route("/process-document", methods=["POST"])
def process_document():
    if "file" not in request.files:
        return jsonify({"error": "No file part"}), 400
    file_storage = request.files["file"]
    if file_storage.filename == "":
        return jsonify({"error": "No selected file"}), 400
    doc_type = request.form.get("type", "question")
    try:
        structured_json = _extract_file_to_json(file_storage, doc_type)
        filename_out = "question_paper.json" if doc_type == "question" else "answer_script.json"
        _write_json(filename_out, json.loads(structured_json))
        return jsonify({"text": structured_json})
    except Exception as exc:
        traceback.print_exc()
        return jsonify({"error": str(exc)}), 500


@app.route("/generate-rubrics", methods=["POST"])
def generate_rubrics():
    try:
        question_json = _load_json("question_paper.json")
        if not question_json:
            return jsonify({"error": "Question paper not found. Please extract it first."}), 400
        rubrics_json_text = generate_rubrics_from_json(json.dumps(question_json))
        rubrics_json = json.loads(rubrics_json_text)
        _write_json("rubrics.json", rubrics_json)
        return jsonify({"rubrics": rubrics_json.get("rubrics", [])})
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500


@app.route("/extract-answers", methods=["POST"])
def extract_answers():
    data = request.get_json(force=True)
    try:
        results = map_answers(data.get("text", ""), data.get("ids", []), client)
        return jsonify(results)
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500


@app.route("/evaluate-answers", methods=["POST"])
def evaluate_answers():
    try:
        data = request.get_json(force=True)
        rubrics_json = _load_json("rubrics.json")
        if not rubrics_json:
            return jsonify({"error": "Rubrics not found. Please generate them first."}), 400
        evaluated = evaluate_mapped_results(data.get("mapped_results", []), rubrics_json)
        return jsonify(evaluated)
    except Exception as exc:
        traceback.print_exc()
        return jsonify({"error": str(exc)}), 500


@app.route("/<path:path>")
def serve_frontend(path):
    if path.startswith("api/"):
        return jsonify({"message": "Not found"}), 404
    asset_path = os.path.join(FRONTEND_DIST_DIR, path)
    if os.path.exists(asset_path) and os.path.isfile(asset_path):
        return send_from_directory(FRONTEND_DIST_DIR, path)
    if os.path.exists(os.path.join(FRONTEND_DIST_DIR, "index.html")):
        return send_from_directory(FRONTEND_DIST_DIR, "index.html")
    return jsonify({"message": "Not found"}), 404


@app.route("/api/v1/batch/exams", methods=["POST"])
@jwt_required
def batch_upload_exams():
    zip_file = request.files.get("file")
    if not zip_file:
        return jsonify({"message": "ZIP file is required"}), 400
    
    zip_bytes = zip_file.read()
    institution_id = get_current_institution_id()
    created_by = get_current_user_id()
    
    job_id = BatchManager.create_job("EXAM_BATCH", institution_id, created_by)
    process_batch_task.delay(job_id, zip_bytes, institution_id, created_by, type="EXAM")
    
    return jsonify({"jobId": job_id, "status": "PENDING"})

@app.route("/api/v1/batch/scripts", methods=["POST"])
@jwt_required
def batch_upload_scripts():
    zip_file = request.files.get("file")
    exam_id = request.form.get("examId")
    if not zip_file or not exam_id:
        return jsonify({"message": "ZIP file and examId are required"}), 400
    
    institution_id = get_current_institution_id()
    created_by = get_current_user_id()
    
    _find_exam_or_404(exam_id, institution_id) # validation
    
    job_id = BatchManager.create_job("SCRIPT_BATCH", institution_id, created_by)
    process_batch_task.delay(job_id, zip_file.read(), institution_id, created_by, type="SCRIPT", exam_id=exam_id)
    
    return jsonify({"jobId": job_id, "status": "PENDING"})

@app.route("/api/v1/batch/jobs", methods=["GET"])
@jwt_required
def list_batch_jobs():
    jobs = get_collection("jobs").find({"institutionId": get_current_institution_id()}).sort("createdAt", -1)
    return jsonify({"items": [_serialize_doc(job) for job in jobs]})

@app.route("/api/v1/batch/jobs/<job_id>", methods=["GET", "DELETE"])
@jwt_required
def get_batch_job(job_id):
    institution_id = get_current_institution_id()
    if request.method == "GET":
        job = get_collection("jobs").find_one({"id": job_id, "institutionId": institution_id})
        if not job:
            return jsonify({"message": "Job not found"}), 404
        return jsonify(_serialize_doc(job))
    
    # DELETE
    result = get_collection("jobs").delete_one({"id": job_id, "institutionId": institution_id})
    if result.deleted_count == 0:
        return jsonify({"message": "Job not found"}), 404
    return jsonify({"message": "Job deleted"})

@app.route("/api/v1/notifications", methods=["GET"])
@jwt_required
def get_notifications():
    user_id = get_current_user_id()
    items = list(get_collection("notifications").find({"userId": user_id}).sort("createdAt", -1).limit(20))
    return jsonify({"items": [_serialize_doc(i) for i in items]})

@app.route("/api/v1/notifications/mark-read", methods=["POST"])
@jwt_required
def mark_notifications_read():
    user_id = get_current_user_id()
    get_collection("notifications").update_many({"userId": user_id}, {"$set": {"read": True}})
    return jsonify({"message": "Marked all as read"})

if __name__ == "__main__":
    app.run(debug=True, port=5001)
