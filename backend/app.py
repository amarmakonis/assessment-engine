import base64
import json
import logging
from collections import defaultdict
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
from agents.extractor import (
    extract_question_paper,
    expand_question_paper_for_pipeline,
    trim_question_paper_to_minimal,
)
from agents.processor import extract_attempt, extract_section_marks
from agents.mapper import map_answers
from agents.rubrics import (
    generate_criteria_for_questions_batch,
    generate_rubrics_from_json,
    generate_criteria_for_question,
)
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
    ordered_id = str(question.get("orderedId") or "").strip()
    source_id = str(question.get("sourceId") or "").strip()
    display_id = (
        ordered_id.split(".", 1)[0]
        if ordered_id and "." in ordered_id
        else (source_id or question_id)
    )
    rubric_text = rubric_lookup.get(question_id, "")
    inferred_marks = _infer_question_max_marks(question, rubric_lookup)
    rubric_items = [{
        "description": rubric_text or f"Evaluate answer for question {question_id}",
        "maxMarks": inferred_marks,
    }]
    out = {
        "questionId": question_id,
        "questionDisplayId": display_id,
        "questionLabel": source_id or question.get("id"),
        "questionText": question.get("text") or question.get("question") or "",
        "context": question.get("context"),
        "sourceId": source_id or None,
        "maxMarks": inferred_marks,
        "rubric": rubric_items,
    }
    if ordered_id:
        out["orderedId"] = ordered_id
    return out


def _normalize_id(id_str):
    if not id_str:
        return ""
    # Align with agents.mapper._normalize_id: keep dots so Q1.1 → 1.1 (not 11).
    s = str(id_str).lower().strip()
    s = re.sub(r"^(q|question|ans|answer)\s*[.\-:]*", "", s, flags=re.IGNORECASE)
    s = s.replace("(", ".").replace(")", "")
    s = re.sub(r"\s+", "", s)
    s = re.sub(r"\.{2,}", ".", s)
    return s.strip(".")


def _effective_question_paper_json(exam):
    """
    Minimal stored papers have only id/text/marks/section per segment.
    Expand in-memory so mainQuestionId and rubric mapping still work.
    """
    qp = (exam or {}).get("questionPaperJson") if isinstance(exam, dict) else None
    if not isinstance(qp, dict):
        return {}
    segs = qp.get("segments") or []
    first = segs[0] if segs else None
    if (
        segs
        and isinstance(first, dict)
        and "mainQuestionId" not in first
    ):
        extra = expand_question_paper_for_pipeline(qp, None, None)
        return {**qp, **extra}
    return qp


def _question_main_group_id(exam, question_id):
    """Resolve main block id from questionPaperJson segments (no section on exam questions)."""
    qid = str(question_id or "").strip()
    if not qid:
        return ""
    payload = _effective_question_paper_json(exam) or {}
    segments = payload.get("segments") if isinstance(payload, dict) else []
    if not isinstance(segments, list):
        return ""
    for seg in segments:
        if not isinstance(seg, dict):
            continue
        for key in ("id", "sourceId"):
            v = str(seg.get(key) or "").strip()
            if v == qid:
                return str(seg.get("mainQuestionId") or "").strip()
    return ""


def _question_section_id(exam, question_id):
    """Resolve section label for a question from stored segments."""
    qid = str(question_id or "").strip()
    if not qid:
        return ""
    qn = _normalize_id(qid)
    payload = _effective_question_paper_json(exam) or {}
    segments = payload.get("segments") if isinstance(payload, dict) else []
    if not isinstance(segments, list):
        return ""
    for seg in segments:
        if not isinstance(seg, dict):
            continue
        for key in ("id", "sourceId", "questionId"):
            v = str(seg.get(key) or "").strip()
            if v and _normalize_id(v) == qn:
                return str(seg.get("section") or "").strip()
    return ""


def _section_key(value):
    s = str(value or "").strip().upper()
    if not s:
        return ""
    m = re.search(r"(?:SECTION\s*)?([A-Z])$", s)
    return m.group(1) if m else s


def _infer_global_section_policy(exam, unit_marks_by_section):
    """
    Detect papers like:
      - Section A compulsory
      - one each from B/C/D
      - one extra from any of B/C/D
    Returns policy dict or None when not confident.
    """
    qp = _effective_question_paper_json(exam) or {}
    structured = qp.get("structured") if isinstance(qp, dict) else {}
    sections = structured.get("sections") if isinstance(structured, dict) else []
    if not isinstance(sections, list) or not sections:
        return None

    compulsory = []
    optional = []
    section_option_marks = {}

    def _question_option_marks(q):
        if not isinstance(q, dict):
            return 0.0
        subs = q.get("sub_questions")
        if isinstance(subs, list) and subs:
            total = sum(_to_number(sq.get("marks")) for sq in subs if isinstance(sq, dict))
            return float(total) if total > 0 else _to_number(q.get("marks"))
        return _to_number(q.get("marks"))

    for sec in sections:
        if not isinstance(sec, dict):
            continue
        sid = _section_key(sec.get("section_id") or sec.get("section"))
        instr = str(sec.get("instruction") or "").lower()
        if not sid:
            continue
        if ("compulsory" in instr) or ("attempt all" in instr) or ("all questions" in instr):
            compulsory.append(sid)
        else:
            optional.append(sid)
        q_marks = [_question_option_marks(q) for q in (sec.get("questions") or [])]
        q_marks = [m for m in q_marks if m > 0]
        if q_marks:
            q_marks_sorted = sorted(q_marks)
            section_option_marks[sid] = q_marks_sorted[len(q_marks_sorted) // 2]

    if len(compulsory) != 1 or len(optional) < 3:
        return None

    exam_total = _resolve_total_marks(exam, exam.get("questions", []))
    if _to_number(exam_total) <= 0:
        return None

    comp_id = compulsory[0]
    comp_marks = section_option_marks.get(comp_id, 0.0)
    if comp_marks <= 0:
        return None

    # Infer one-pick mark from optional sections based on paper structure (not student score).
    opt_base_marks = []
    for sid in optional:
        m = section_option_marks.get(sid, 0.0)
        if m <= 0:
            return None
        opt_base_marks.append(m)
    if not opt_base_marks:
        return None
    base = sorted(opt_base_marks)[len(opt_base_marks) // 2]
    if base <= 0:
        return None

    # Infer how many extra picks are needed from optional pool to match total marks.
    raw_extra = (_to_number(exam_total) - comp_marks) / base - len(optional)
    extra_pick = int(round(raw_extra))
    if extra_pick < 0 or extra_pick > 3:
        return None
    expected = comp_marks + (len(optional) + extra_pick) * base
    if abs(expected - _to_number(exam_total)) > 2.0:
        return None

    return {
        "compulsory": comp_id,
        "optionals": optional,
        "extra_pick_from_optionals": extra_pick,
        "reason": (
            "Detected compulsory + one-each-from-optionals + "
            f"{extra_pick} extra optional pick(s) pattern"
        ),
    }


def _build_main_question_groups_list(main_questions):
    """One entry per main block; attempt/marks caps keyed by id (matches segment mainQuestionId)."""
    out = []
    for mq in main_questions or []:
        if not isinstance(mq, dict):
            continue
        out.append(
            {
                "id": str(mq.get("id", "")).strip(),
                "mainQuestionAttemptLimit": mq.get("sectionAttemptLimit"),
                "mainQuestionTotalOptions": mq.get("sectionTotalOptions"),
                "mainQuestionMarksConsidered": mq.get("mainQuestionMarksConsidered"),
                "sectionMarksPerQuestion": mq.get("sectionMarksPerQuestion"),
            }
        )
    return out


def _sum_exam_marks_from_groups(exam, questions):
    """Sum exam total using one cap per main group id from mainQuestionGroups."""
    groups = (exam or {}).get("mainQuestionGroups") if isinstance(exam, dict) else None
    if not groups or not questions:
        return _sum_question_marks(questions or [])

    qp = (exam or {}).get("questionPaperJson") or {}
    segs = qp.get("segments") if isinstance(qp, dict) else None
    if not segs:
        return _sum_question_marks(questions)

    policy_ids = {}
    for g in groups:
        if not isinstance(g, dict):
            continue
        gid = str(g.get("id", "")).strip()
        if gid:
            policy_ids[gid] = g

    if not policy_ids:
        return _sum_question_marks(questions)

    total = 0.0
    covered = set()
    for gid, g in policy_ids.items():
        if gid in covered:
            continue
        covered.add(gid)
        cap = _to_number(g.get("mainQuestionMarksConsidered") or 0)
        if cap <= 0:
            att_i = _attempt_limit_as_int(
                g.get("mainQuestionAttemptLimit"),
                g.get("mainQuestionTotalOptions"),
            )
            mx = next(
                (
                    _to_number(q.get("maxMarks"))
                    for q in questions
                    if _question_main_group_id(exam, q.get("questionId")) == gid
                ),
                0,
            )
            if att_i > 0 and mx > 0:
                cap = att_i * mx
        if cap > 0:
            total += cap
        else:
            total += sum(
                _to_number(q.get("maxMarks"))
                for q in questions
                if _question_main_group_id(exam, q.get("questionId")) == gid
            )

    grouped_ids = set(policy_ids.keys())
    for q in questions:
        mg = _question_main_group_id(exam, q.get("questionId"))
        if mg and mg in grouped_ids:
            continue
        if not mg and grouped_ids:
            continue
        total += _to_number(q.get("maxMarks"))

    return round(total, 2)


def _attempt_limit_as_int(raw_limit, total_options=None):
    """Parse numeric/textual attempt limits (e.g. 'One question...', 'All compulsory')."""
    if raw_limit is None:
        return 0
    if isinstance(raw_limit, (int, float)):
        try:
            n = int(raw_limit)
            return n if n > 0 else 0
        except (TypeError, ValueError):
            return 0

    text = str(raw_limit).strip().lower()
    if not text:
        return 0

    if text.isdigit():
        n = int(text)
        return n if n > 0 else 0

    if "all compulsory" in text or "attempt all" in text or "all questions" in text:
        return int(_to_number(total_options)) if _to_number(total_options) > 0 else 0

    word_to_num = {
        "one": 1,
        "two": 2,
        "three": 3,
        "four": 4,
        "five": 5,
        "six": 6,
        "seven": 7,
        "eight": 8,
        "nine": 9,
        "ten": 10,
    }
    for word, number in word_to_num.items():
        if re.search(rf"\b{word}\b", text):
            return number

    m = re.search(r"(\d+)", text)
    if m:
        n = int(m.group(1))
        return n if n > 0 else 0
    return 0


def _apply_section_group_scoring(evaluated, exam_questions, exam):
    """Best-N + cap per main group id; sets countableScore."""
    policy = {}
    for g in exam.get("mainQuestionGroups") or []:
        if not isinstance(g, dict):
            continue
        gid = str(g.get("id", "")).strip()
        if gid:
            policy[gid] = g

    q_by_id = {str(q["questionId"]): q for q in exam_questions}

    for item in evaluated:
        item["countableScore"] = float(_to_number(item.get("score")))

    def _attempt_unit_key(question_id):
        """
        Selection unit for "Any N":
        - Q3.1.a / Q3.1.b -> Q3.1 (count as one chosen question)
        - Q1.2 -> Q1.2 (normal standalone)
        """
        qid = str(question_id or "").strip()
        if not qid:
            return qid
        parts = [p for p in qid.split(".") if p]
        if len(parts) >= 3:
            tail = parts[-1].lower()
            if re.fullmatch(r"[a-z]+|[ivxlcdm]+", tail):
                return ".".join(parts[:-1])
        return qid

    # Build section->unit scores for optional global policies.
    unit_scores = {}
    unit_items = {}
    for item in evaluated:
        qid = str(item.get("id") or "")
        qdoc = q_by_id.get(qid)
        if not qdoc:
            continue
        sid = _section_key(_question_section_id(exam, qdoc.get("questionId")))
        if not sid:
            continue
        unit = _attempt_unit_key(qid)
        key = (sid, unit)
        unit_scores[key] = unit_scores.get(key, 0.0) + _to_number(item.get("countableScore"))
        unit_items.setdefault(key, []).append(item)

    unit_marks_by_section = defaultdict(dict)
    for (sid, unit), score in unit_scores.items():
        unit_marks_by_section[sid][unit] = score

    # IMPORTANT: keep legacy behavior unchanged unless an explicit policy is present
    # or auto-detect is explicitly opted in.
    qp = _effective_question_paper_json(exam) or {}
    raw_policy = qp.get("selectionPolicy") if isinstance(qp, dict) else None
    global_policy = raw_policy if isinstance(raw_policy, dict) else None
    applied_policy_mode = "explicit" if global_policy else None
    scoring_opts = qp.get("scoringOptions") if isinstance(qp, dict) else None
    auto_detect_enabled = False
    if isinstance(scoring_opts, dict):
        auto_detect_enabled = bool(scoring_opts.get("autoDetectIcseSelectionPolicy"))
    if not auto_detect_enabled:
        auto_detect_enabled = bool(qp.get("autoDetectIcseSelectionPolicy"))
    if not global_policy and auto_detect_enabled:
        inferred = _infer_global_section_policy(exam, unit_marks_by_section)
        if isinstance(inferred, dict):
            global_policy = inferred
            applied_policy_mode = "auto_icse"
    if global_policy:
        compulsory_id = _section_key(global_policy.get("compulsory"))
        optional_ids = [_section_key(x) for x in (global_policy.get("optionals") or []) if _section_key(x)]
        extra_n = int(global_policy.get("extra_pick_from_optionals") or 0)
        if not compulsory_id or not optional_ids or extra_n < 0:
            return evaluated

        chosen_units = set()
        # compulsory: include all units
        for unit in unit_marks_by_section.get(compulsory_id, {}).keys():
            chosen_units.add((compulsory_id, unit))
        # one best from each optional
        remainder_pool = []
        for sid in optional_ids:
            ranked = sorted(
                unit_marks_by_section.get(sid, {}).items(),
                key=lambda kv: kv[1],
                reverse=True,
            )
            if ranked:
                chosen_units.add((sid, ranked[0][0]))
                remainder_pool.extend([(sid, u, sc) for u, sc in ranked[1:]])
        # extra pick(s) from optional pool
        if extra_n > 0 and remainder_pool:
            remainder_pool.sort(key=lambda x: x[2], reverse=True)
            for sid, unit, _ in remainder_pool[:extra_n]:
                chosen_units.add((sid, unit))

        for (sid, unit), items in unit_items.items():
            if (sid, unit) in chosen_units:
                for r in items:
                    r["selectionPolicyApplied"] = applied_policy_mode
                continue
            for r in items:
                r["countableScore"] = 0.0
                r["excludedByGroupPolicy"] = True
                r["selectionPolicyApplied"] = applied_policy_mode
                r["exclusionReason"] = (
                    f"Excluded by cross-section attempt policy ({global_policy['reason']})."
                )
        return evaluated

    by_mg = defaultdict(list)
    for item in evaluated:
        qdoc = q_by_id.get(str(item.get("id")))
        if not qdoc:
            continue
        mg = _question_main_group_id(exam, qdoc.get("questionId"))
        if not mg or mg not in policy:
            continue
        g = policy[mg]
        att = g.get("mainQuestionAttemptLimit")
        cap = _to_number(g.get("mainQuestionMarksConsidered") or 0)
        att_i = _attempt_limit_as_int(att, g.get("mainQuestionTotalOptions"))
        has_att = att_i > 0
        if not has_att and cap <= 0:
            continue
        by_mg[mg].append(item)

    for mg, items in by_mg.items():
        g = policy[mg]
        att_i = _attempt_limit_as_int(
            g.get("mainQuestionAttemptLimit"),
            g.get("mainQuestionTotalOptions"),
        )
        n = att_i if att_i > 0 else len(items)
        cap = _to_number(g.get("mainQuestionMarksConsidered") or 0)

        # Group by parent question unit so "Any Two" selects two full questions, not two sub-parts.
        unit_items = defaultdict(list)
        for x in items:
            unit_items[_attempt_unit_key(x.get("id"))].append(x)

        ranked_units = sorted(
            unit_items.items(),
            key=lambda kv: sum(_to_number(i.get("countableScore")) for i in kv[1]),
            reverse=True,
        )

        chosen_units = {uk for uk, _ in ranked_units[: max(0, n)]}
        chosen = []
        for uk, uitems in unit_items.items():
            if uk in chosen_units:
                chosen.extend(uitems)
            else:
                for r in uitems:
                    r["countableScore"] = 0.0
                    r["excludedByGroupPolicy"] = True
                    r["exclusionReason"] = (
                        f"Excluded by section attempt policy: best {n} question(s) considered for group {mg}."
                    )

        s = sum(_to_number(x.get("countableScore")) for x in chosen)
        if cap > 0 and s > cap:
            scale = cap / s if s > 0 else 0
            for x in chosen:
                x["countableScore"] = round(_to_number(x.get("countableScore")) * scale, 4)

    return evaluated


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


def _subject_from_structured_metadata(metadata):
    """Prefer metadata.subject; derive from title (e.g. 'Conflict of Laws Examination')."""
    if not isinstance(metadata, dict):
        return None
    s = str(metadata.get("subject") or "").strip()
    if s:
        return s
    title = str(metadata.get("title") or "").strip()
    if not title:
        return None
    t = re.sub(r"\s*examination\s*$", "", title, flags=re.IGNORECASE).strip()
    t = re.sub(r"\s*exam\s*$", "", t, flags=re.IGNORECASE).strip()
    return t or None


def _default_exam_subject_from_question_json(question_json):
    """Prefer metadata.subject (or title-derived), then section label, else first segment."""
    if not isinstance(question_json, dict):
        return "General"
    structured = question_json.get("structured")
    if isinstance(structured, dict):
        meta = structured.get("metadata")
        subj = _subject_from_structured_metadata(meta) if isinstance(meta, dict) else None
        if subj:
            return subj
        secs = structured.get("sections") or []
        if secs and isinstance(secs[0], dict):
            sec = secs[0].get("section") or secs[0].get("section_id")
            if sec:
                return str(sec).strip() or "General"
    seg0 = (question_json.get("segments") or [{}])[0]
    if isinstance(seg0, dict) and seg0.get("section"):
        return str(seg0["section"]).strip() or "General"
    return "General"


def _infer_section_attempt_mpq_cap(sec):
    """
    Per-section exam design: attempt × marks-per-option (when student picks any N).
    If derived_marks_per_question is missing (e.g. instruction has no '(12 marks)'),
    infer mpq from: (1) instruction total / attempt, (2) first question's marks (short or case parent).
    """
    if not isinstance(sec, dict):
        return None, None, 0
    mpq = sec.get("derived_marks_per_question") or sec.get("marks_per_question")
    if mpq is not None:
        try:
            mpq_f = float(mpq)
        except (TypeError, ValueError):
            mpq_f = None
    else:
        mpq_f = None
    attempt = sec.get("attempt")
    if attempt is None:
        attempt = extract_attempt(sec.get("instruction") or "")
    try:
        a = int(attempt) if attempt is not None else 0
    except (TypeError, ValueError):
        a = 0

    inst = sec.get("instruction") or ""
    total_sec = extract_section_marks(inst)
    if mpq_f is None and total_sec and a > 0:
        mpq_f = float(total_sec) / float(a)

    if mpq_f is None and a > 0:
        questions = sec.get("questions") or []
        if questions:
            q0 = questions[0]
            m = q0.get("marks")
            if m is not None:
                try:
                    mpq_f = float(m)
                except (TypeError, ValueError):
                    pass

    if not a or mpq_f is None:
        return None, None, 0
    cap = a * mpq_f
    cap_out = int(cap) if cap == int(cap) else cap
    return a, mpq_f, cap_out


def _sum_structured_section_caps(structured):
    if not isinstance(structured, dict):
        return 0
    total = 0.0
    for sec in structured.get("sections") or []:
        if not isinstance(sec, dict):
            continue
        _a, _m, cap = _infer_section_attempt_mpq_cap(sec)
        if cap and cap > 0:
            total += cap
    return round(total, 2) if total > 0 else 0


def _sync_main_question_groups_from_structured(groups, structured):
    """Align mainQuestionGroups with structured sections (attempt × mpq caps)."""
    sections = (structured or {}).get("sections") or []
    if not isinstance(groups, list) or not sections:
        return groups
    for i, g in enumerate(groups):
        if i >= len(sections):
            break
        sec = sections[i]
        if not isinstance(sec, dict):
            continue
        a, mpq_f, cap = _infer_section_attempt_mpq_cap(sec)
        if cap and cap > 0:
            g["mainQuestionMarksConsidered"] = cap
            g["sectionMarksPerQuestion"] = int(mpq_f) if mpq_f == int(mpq_f) else mpq_f
        elif a and mpq_f:
            g["mainQuestionMarksConsidered"] = int(a * mpq_f) if (a * mpq_f) == int(a * mpq_f) else round(a * mpq_f, 2)
            g["sectionMarksPerQuestion"] = int(mpq_f) if mpq_f == int(mpq_f) else mpq_f
        if a is not None:
            g["mainQuestionAttemptLimit"] = a
    return groups


def _extract_declared_total_marks(question_paper_json):
    if not isinstance(question_paper_json, dict):
        return 0

    total_marks = _to_number(question_paper_json.get("paperTotalMarks"))
    if total_marks > 0:
        return total_marks

    structured = question_paper_json.get("structured")
    if isinstance(structured, dict):
        total_marks = _to_number(structured.get("total_paper_marks"))
        if total_marks > 0:
            return total_marks
        cap_sum = _sum_structured_section_caps(structured)
        if cap_sum > 0:
            return cap_sum
        meta = structured.get("metadata")
        if isinstance(meta, dict):
            total_marks = _to_number(meta.get("total_marks"))
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


def _question_option_marks(question):
    if not isinstance(question, dict):
        return 0.0
    subs = question.get("sub_questions")
    if isinstance(subs, list) and subs:
        sub_total = sum(_to_number(sq.get("marks")) for sq in subs if isinstance(sq, dict))
        if sub_total > 0:
            return float(sub_total)
    return float(_to_number(question.get("marks")))


def _should_enable_icse_auto_policy(question_paper_json):
    """
    High-confidence detector for ICSE-like pattern:
    - one compulsory section
    - three optional sections (B/C/D style)
    - one pick from each optional + one extra optional pick
    - total matches compulsory + 4 * optional-unit-marks
    """
    if not isinstance(question_paper_json, dict):
        return False
    if question_paper_json.get("autoDetectIcseSelectionPolicy"):
        return True
    scoring_opts = question_paper_json.get("scoringOptions")
    if isinstance(scoring_opts, dict) and scoring_opts.get("autoDetectIcseSelectionPolicy"):
        return True

    structured = question_paper_json.get("structured")
    sections = structured.get("sections") if isinstance(structured, dict) else None
    if not isinstance(sections, list) or len(sections) < 4:
        return False

    compulsory_sections = []
    optional_sections = []
    for sec in sections:
        if not isinstance(sec, dict):
            continue
        instr = str(sec.get("instruction") or "").lower()
        if ("compulsory" in instr) or ("attempt all" in instr) or ("all questions" in instr):
            compulsory_sections.append(sec)
        else:
            optional_sections.append(sec)

    if len(compulsory_sections) != 1 or len(optional_sections) != 3:
        return False

    compulsory_qs = compulsory_sections[0].get("questions") or []
    compulsory_marks = sum(_question_option_marks(q) for q in compulsory_qs if isinstance(q, dict))
    if compulsory_marks <= 0:
        return False

    optional_unit_marks = []
    for sec in optional_sections:
        qs = [q for q in (sec.get("questions") or []) if isinstance(q, dict)]
        if len(qs) < 2:
            return False
        marks = [_question_option_marks(q) for q in qs]
        marks = [m for m in marks if m > 0]
        if len(marks) < 2:
            return False
        marks.sort()
        optional_unit_marks.append(marks[len(marks) // 2])

    if not optional_unit_marks:
        return False
    base_optional = sorted(optional_unit_marks)[len(optional_unit_marks) // 2]
    if base_optional <= 0:
        return False

    declared_total = _extract_declared_total_marks(question_paper_json)
    if declared_total <= 0:
        return False

    # one each from 3 optionals + one extra from optionals => 4 optional picks
    expected = compulsory_marks + (len(optional_sections) + 1) * base_optional
    return abs(expected - declared_total) <= 2.0


def _build_exam_payload(title, subject, question_paper_json, rubrics):
    question_segments = question_paper_json.get("segments", []) if isinstance(question_paper_json, dict) else []
    main_questions = question_paper_json.get("mainQuestions", []) if isinstance(question_paper_json, dict) else []
    rubric_lookup = {str(item.get("id")): item.get("rubric", "") for item in rubrics}
    questions = [_question_to_frontend(question, rubric_lookup) for question in question_segments]
    stats = _calculate_exam_display_stats(questions)
    main_question_groups = _build_main_question_groups_list(main_questions)
    qp = question_paper_json if isinstance(question_paper_json, dict) else {}
    st = qp.get("structured") or {}
    main_question_groups = _sync_main_question_groups_from_structured(main_question_groups, st)
    declared_total_marks = _extract_declared_total_marks(question_paper_json)
    partial_exam = {"mainQuestionGroups": main_question_groups, "questionPaperJson": qp}
    cap_total = _sum_exam_marks_from_groups(partial_exam, questions)
    if declared_total_marks > 0:
        effective_total = declared_total_marks
    elif cap_total > 0:
        effective_total = cap_total
    else:
        effective_total = stats["totalMarks"]
    return {
        "title": title,
        "subject": subject,
        "questions": questions,
        "totalMarks": effective_total,
        "extractedTotalMarks": effective_total,
        # Main paper questions (Q1–Q4); leafSegmentCount = every scorable line (Q1.1, Q3.1.a, …)
        "displayQuestionCount": (
            len(main_question_groups)
            if main_question_groups
            else (
                len(st.get("sections") or [])
                if st.get("sections")
                else (len(question_segments) if question_segments else stats["displayQuestionCount"])
            )
        ),
        "leafSegmentCount": len(question_segments) if question_segments else 0,
        "mainQuestionGroups": main_question_groups,
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
    total_marks = _to_number((source or {}).get("extractedTotalMarks"))
    if total_marks > 0:
        return total_marks
    total_marks = _to_number((source or {}).get("totalMarks"))
    if total_marks > 0:
        return total_marks
    total_marks = _extract_declared_total_marks((source or {}).get("questionPaperJson"))
    if total_marks > 0:
        return total_marks
    if (source or {}).get("mainQuestionGroups") and questions:
        return _sum_exam_marks_from_groups(source, questions)
    return _sum_question_marks(questions or [])


def _recalculate_exam_total_marks(source, questions=None):
    total_marks = _to_number((source or {}).get("extractedTotalMarks"))
    if total_marks > 0:
        return total_marks

    total_marks = _extract_declared_total_marks((source or {}).get("questionPaperJson"))
    if total_marks > 0:
        return total_marks

    if (source or {}).get("mainQuestionGroups") and questions:
        return _sum_exam_marks_from_groups(source, questions)
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
    snap = script.get("questionsSnapshot", [])
    if script.get("examId"):
        try:
            exam = get_collection("exams").find_one({"_id": ObjectId(script.get("examId"))})
        except Exception:
            exam = None
        if exam and exam.get("mainQuestionGroups") and snap:
            return _sum_exam_marks_from_groups(exam, snap)
    return _sum_question_marks(snap)


def _leaf_segment_count_from_exam(exam):
    """How many scorable leaf items (e.g. Q1.1 … Q4.4)."""
    qp = (exam or {}).get("questionPaperJson") or {}
    segs = qp.get("segments")
    if isinstance(segs, list) and len(segs) > 0:
        return len(segs)
    qs = exam.get("questions") or []
    return len(qs) if qs else 0


def _main_section_count_from_exam(exam):
    """How many main paper questions (Q1–Q4)."""
    g = exam.get("mainQuestionGroups")
    if isinstance(g, list) and len(g) > 0:
        return len(g)
    qp = (exam or {}).get("questionPaperJson") or {}
    st = qp.get("structured") or {}
    secs = st.get("sections")
    if isinstance(secs, list) and len(secs) > 0:
        return len(secs)
    return 0


def _exam_list_display_counts(exam):
    """
    displayQuestionCount = main sections (e.g. 4).
    leafSegmentCount = leaf scorable items (e.g. 25).
    Legacy rows stored displayQuestionCount as leaf count — fix when it equals leaf and is large.
    """
    leaf = exam.get("leafSegmentCount")
    if leaf is None:
        leaf = _leaf_segment_count_from_exam(exam)
    main = exam.get("displayQuestionCount")
    main_from_struct = _main_section_count_from_exam(exam)
    if main is None:
        main = main_from_struct
    elif main_from_struct and main == leaf and leaf > 8:
        main = main_from_struct
    if not main:
        main = _calculate_exam_display_stats(exam.get("questions", []))["displayQuestionCount"]
    return main, leaf


def _exam_list_item(exam):
    """Summary row only — use GET /exams/:id for questions, rubrics, and groups."""
    main_n, leaf_n = _exam_list_display_counts(exam)
    return {
        "id": str(exam["_id"]),
        "title": exam.get("title"),
        "subject": exam.get("subject"),
        "status": exam.get("status", "COMPLETED"),
        "totalMarks": _resolve_total_marks(exam, exam.get("questions", [])),
        "displayQuestionCount": main_n,
        "leafSegmentCount": leaf_n,
        "createdAt": _iso(exam.get("createdAt")),
    }


_DEFERRED_RUBRIC_MARKERS = (
    "will be generated when an answer script is evaluated",
    "rubric pending",
)


def _deferred_rubrics_for_new_exam(question_paper_json):
    """Placeholders only — Groq rubric/criteria generation runs on first evaluation per question."""
    segs = question_paper_json.get("segments", []) if isinstance(question_paper_json, dict) else []
    out = []
    for s in segs:
        if not isinstance(s, dict):
            continue
        sid = str(s.get("id", "")).strip()
        if not sid:
            continue
        marks = _to_number(s.get("marks", 0))
        if marks <= 0:
            out.append(
                {
                    "id": sid,
                    "rubric": "Rubric pending: question marks are missing. Set marks and regenerate rubric.",
                    "criteria": [],
                }
            )
        else:
            out.append(
                {
                    "id": sid,
                    "rubric": "Rubric will be generated when an answer script is evaluated.",
                    "criteria": [],
                }
            )
    return out


def _deferred_rubric_wording(rubric_row):
    if not rubric_row or not isinstance(rubric_row, dict):
        return True
    t = str(rubric_row.get("rubric") or "").strip().lower()
    if not t:
        return True
    return any(m in t for m in _DEFERRED_RUBRIC_MARKERS)


def _sync_exam_questions_rubric_display(exam):
    rubric_lookup = {
        str(r.get("id")): str(r.get("rubric") or "").strip() for r in exam.get("rubrics", []) if isinstance(r, dict)
    }
    for q in exam.get("questions", []):
        if not isinstance(q, dict):
            continue
        qid = str(q.get("questionId", ""))
        text = rubric_lookup.get(qid, "")
        if not text:
            continue
        mm = q.get("maxMarks", 0)
        q["rubric"] = [{"description": text, "maxMarks": mm}]


def _persist_exam_rubrics_to_db(exam):
    eid = exam.get("_id")
    if not eid:
        return
    oid = eid if isinstance(eid, ObjectId) else ObjectId(str(eid))
    get_collection("exams").update_one(
        {"_id": oid},
        {"$set": {"rubrics": exam.get("rubrics", []), "questions": exam.get("questions", []), "updatedAt": _now()}},
    )


def _ensure_rubrics_for_mapped_items(exam, mapped_results):
    """
    For each question the student actually attempted, ensure rubric + criteria exist
    (lazy Groq) when the exam was created with deferred placeholders.
    Uses one batched rubric call and one batched criteria call instead of per-question round-trips.
    """
    rubrics = exam.get("rubrics")
    if not isinstance(rubrics, list):
        rubrics = []
        exam["rubrics"] = rubrics
    by_id = {
        str(r.get("id")): i
        for i, r in enumerate(rubrics)
        if isinstance(r, dict) and str(r.get("id", "")).strip()
    }
    q_by_id = {str(q.get("questionId")): q for q in exam.get("questions", []) if isinstance(q, dict)}
    changed = False
    pending_deferred = []
    criteria_only = []

    for item in mapped_results:
        qid = str(item.get("id", ""))
        if not qid:
            continue
        marks = _to_number(item.get("maxMarks", 0))
        ans = str(item.get("answer", "") or "").strip()
        if not ans or "not found" in ans.lower():
            continue
        if marks <= 0:
            continue

        idx = by_id.get(qid)
        if idx is None:
            rubrics.append({"id": qid, "rubric": "", "criteria": []})
            idx = len(rubrics) - 1
            by_id[qid] = idx
            changed = True
        row = rubrics[idx]

        qdoc = q_by_id.get(qid, {})
        qtext = str(qdoc.get("questionText") or item.get("question") or "")

        if _deferred_rubric_wording(row):
            pending_deferred.append({"idx": idx, "qid": qid, "qtext": qtext, "marks": marks})
            continue

        crit = row.get("criteria") if isinstance(row.get("criteria"), list) else []
        if not crit:
            rt = str(row.get("rubric") or "").strip()
            rt_lower = rt.lower()
            if (
                rt
                and marks > 0
                and "rubric pending" not in rt_lower
                and "rubric will be generated" not in rt_lower
            ):
                criteria_only.append(
                    {
                        "idx": idx,
                        "id": qid,
                        "questionText": qtext,
                        "rubricText": rt,
                        "marks": marks,
                    }
                )

    if pending_deferred:
        segments = [
            {
                "id": str(p["qid"]),
                "text": str(p["qtext"] or "").strip(),
                "marks": _to_number(p["marks"]),
                "section": "Q1",
            }
            for p in pending_deferred
        ]
        try:
            generated_json = generate_rubrics_from_json(json.dumps({"segments": segments}, ensure_ascii=False))
            parsed = json.loads(generated_json)
            rows_out = parsed.get("rubrics") if isinstance(parsed, dict) else []
            by_gen_id = {}
            if isinstance(rows_out, list):
                for r in rows_out:
                    if isinstance(r, dict):
                        rid = str(r.get("id", "")).strip()
                        if rid and rid not in by_gen_id:
                            by_gen_id[rid] = r
            for p in pending_deferred:
                rid = str(p["qid"])
                gen_row = by_gen_id.get(rid)
                if not gen_row:
                    for k, v in by_gen_id.items():
                        if _normalize_id(k) == _normalize_id(rid):
                            gen_row = v
                            break
                if gen_row and str(gen_row.get("rubric") or "").strip():
                    rubrics[p["idx"]] = {
                        "id": rid,
                        "rubric": str(gen_row.get("rubric") or "").strip(),
                        "criteria": gen_row.get("criteria") if isinstance(gen_row.get("criteria"), list) else [],
                    }
                    changed = True
        except Exception:
            pass

    crit_after_rubric = list(criteria_only)
    for p in pending_deferred:
        row = rubrics[p["idx"]]
        if not isinstance(row, dict):
            continue
        crit = row.get("criteria") if isinstance(row.get("criteria"), list) else []
        rt = str(row.get("rubric") or "").strip()
        rt_lower = rt.lower()
        mm = _to_number(p["marks"])
        if (
            not crit
            and rt
            and mm > 0
            and "rubric pending" not in rt_lower
            and "rubric will be generated" not in rt_lower
        ):
            crit_after_rubric.append(
                {
                    "idx": p["idx"],
                    "id": p["qid"],
                    "questionText": str(p["qtext"] or "").strip(),
                    "rubricText": rt,
                    "marks": mm,
                }
            )

    seen_crit_idx = set()
    crit_deduped = []
    for c in crit_after_rubric:
        ix = c["idx"]
        if ix in seen_crit_idx:
            continue
        seen_crit_idx.add(ix)
        crit_deduped.append(c)

    if crit_deduped:
        batch_in = [
            {"id": c["id"], "questionText": c["questionText"], "rubricText": c["rubricText"], "marks": c["marks"]}
            for c in crit_deduped
        ]
        crit_map = generate_criteria_for_questions_batch(batch_in)
        for c in crit_deduped:
            sid = str(c["id"])
            rows = crit_map.get(sid)
            if rows is None:
                for k, v in crit_map.items():
                    if _normalize_id(k) == _normalize_id(sid):
                        rows = v
                        break
            if rows:
                idx = c["idx"]
                old = rubrics[idx]
                updated = dict(old) if isinstance(old, dict) else {"id": sid}
                updated["criteria"] = rows
                rubrics[idx] = updated
                changed = True

    if changed:
        _sync_exam_questions_rubric_display(exam)
        _persist_exam_rubrics_to_db(exam)


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
                "question": question["questionText"],
                "maxMarks": question.get("maxMarks", 0),
                "answer": match.get("answer") if match else "Not found in student script",
                "mappingStatus": (match.get("mappingStatus") if match else "missing"),
                "matchStrategy": (match.get("matchStrategy") if match else "missing"),
                "matchedSegmentId": (match.get("matchedSegmentId") if match else None),
                "candidateSegmentIds": (match.get("candidateSegmentIds") if match else []),
            }
        )

    _ensure_rubrics_for_mapped_items(exam, mapped_results)

    evaluation_input = {"rubrics": exam.get("rubrics", [])}
    evaluated = evaluate_mapped_results(mapped_results, evaluation_input)
    evaluated = _apply_section_group_scoring(evaluated, exam_questions, exam)
    selection_policy_applied = next(
        (str(x.get("selectionPolicyApplied")) for x in evaluated if x.get("selectionPolicyApplied")),
        None,
    )

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
        countable = _to_number(item.get("countableScore", item.get("score")))
        total_score += countable

        not_found = "not found" in str(item.get("answer", "")).lower()
        is_ambiguous = str(item.get("mappingStatus", "")).lower() == "ambiguous"
        if not not_found:
            evaluated_count += 1

        review_recommendation = "NEEDS_REVIEW" if (not_found or is_ambiguous) else "AUTO_APPROVED"
        if is_ambiguous:
            review_reason = "Multiple possible answer segments matched this question; manual review required."
        else:
            review_reason = "Answer was not confidently mapped to a question." if not_found else "Auto-evaluated from extracted mapping."
        if review_recommendation != "AUTO_APPROVED":
            review_items.append(
                {
                    "questionId": str(item.get("id")),
                    "totalScore": countable,
                    "maxScore": max_marks,
                    "reviewRecommendation": review_recommendation,
                    "reviewReason": review_reason,
                    "createdAt": _now(),
                }
            )

        fb_structured = item.get("feedbackStructured")
        feedback_field = (
            fb_structured
            if isinstance(fb_structured, dict)
            else item.get("feedback", "")
        )
        result_items.append(
            {
                "id": str(ObjectId()),
                "runId": str(uuid.uuid4()),
                "scriptId": None,
                "questionId": str(item.get("id")),
                "totalScore": countable,
                "rawEvaluatedScore": score,
                "excludedByGroupPolicy": bool(item.get("excludedByGroupPolicy")),
                "maxPossibleScore": max_marks,
                "percentageScore": round((countable / max_marks) * 100, 2) if max_marks else 0,
                "reviewRecommendation": review_recommendation,
                "status": "COMPLETE",
                "feedback": feedback_field,
                "criterionScores": item.get("criterionScores") or [],
                "groundedRubric": item.get("groundedRubric"),
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
        "selectionPolicyApplied": selection_policy_applied,
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
    """
    List exams for the institution.
    Optional query: ids=comma,separated,ObjectIds — return only those rows (same shape as list items).
    Used for a single refresh round-trip while exams are PROCESSING.
    """
    institution_id = get_current_institution_id()
    query = {"institutionId": institution_id}
    ids_param = (request.args.get("ids") or "").strip()
    if ids_param:
        oid_list = []
        for part in ids_param.split(","):
            part = part.strip()
            if not part:
                continue
            try:
                oid_list.append(ObjectId(part))
            except Exception:
                continue
        oid_list = oid_list[:40]
        if not oid_list:
            return jsonify({"items": [], "total": 0})
        query["_id"] = {"$in": oid_list}
    exams = list(get_collection("exams").find(query).sort("createdAt", -1))
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
        main_n, leaf_n = _exam_list_display_counts(exam)
        payload["totalMarks"] = _resolve_total_marks(exam, exam.get("questions", []))
        payload["displayQuestionCount"] = main_n
        payload["leafSegmentCount"] = leaf_n
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
        "leafSegmentCount": len(normalized_questions),
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
        segments = question_json.get("segments", [])
        structured = question_json.get("structured")
        if structured is None and isinstance(question_json, dict):
            legacy_sections = question_json.get("structuredSections")
            if legacy_sections is not None:
                question_json["structured"] = {"sections": legacy_sections if isinstance(legacy_sections, list) else []}
                structured = question_json["structured"]
        if not segments:
            err = question_json.get("error") if isinstance(question_json, dict) else None
            raise ValueError(
                f"Question extraction returned no segments. "
                f"{'Reason: ' + str(err) if err else 'Please retry upload.'}"
            )

        minimal_for_storage = trim_question_paper_to_minimal(question_json)
        rubrics_list = _deferred_rubrics_for_new_exam(minimal_for_storage)

        if not title:
            title = filename.rsplit(".", 1)[0]
        meta_subj = _default_exam_subject_from_question_json(question_json)
        if not subject or str(subject).strip() in ("", "General"):
            subject = meta_subj if meta_subj else "General"
        pipeline_extras = expand_question_paper_for_pipeline(question_json, file_content, mime_type)
        merged_paper = {**question_json, **pipeline_extras}
        if _should_enable_icse_auto_policy(merged_paper):
            merged_scoring = merged_paper.get("scoringOptions") if isinstance(merged_paper.get("scoringOptions"), dict) else {}
            merged_scoring["autoDetectIcseSelectionPolicy"] = True
            merged_paper["scoringOptions"] = merged_scoring
            merged_paper["autoDetectIcseSelectionPolicy"] = True
            minimal_scoring = minimal_for_storage.get("scoringOptions") if isinstance(minimal_for_storage.get("scoringOptions"), dict) else {}
            minimal_scoring["autoDetectIcseSelectionPolicy"] = True
            minimal_for_storage["scoringOptions"] = minimal_scoring
            minimal_for_storage["autoDetectIcseSelectionPolicy"] = True

        exam_payload = _build_exam_payload(title, subject, merged_paper, rubrics_list)
        exam_payload["questionPaperJson"] = minimal_for_storage

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
    exam["leafSegmentCount"] = len(exam["questions"])
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
        {
            "$set": {
                "questions": exam["questions"],
                "rubrics": exam["rubrics"],
                "totalMarks": exam["totalMarks"],
                "displayQuestionCount": exam["displayQuestionCount"],
                "leafSegmentCount": exam["leafSegmentCount"],
                "updatedAt": _now(),
            }
        },
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
    new_max_marks = _to_number(data["maxMarks"]) if data.get("maxMarks") is not None else None

    def _rescale_criteria(criteria, target_max):
        if not isinstance(criteria, list) or target_max is None:
            return criteria
        rows = [c for c in criteria if isinstance(c, dict)]
        if not rows:
            return criteria
        current_total = sum(_to_number(c.get("maxMarks")) for c in rows)
        if current_total <= 0:
            each = (target_max / len(rows)) if len(rows) else 0
            for c in rows:
                c["maxMarks"] = int(each) if each == int(each) else round(each, 4)
            return rows
        scale = target_max / current_total if current_total > 0 else 0
        for c in rows:
            v = _to_number(c.get("maxMarks")) * scale
            c["maxMarks"] = int(v) if v == int(v) else round(v, 4)
        return rows

    def _generate_single_rubric_row(qid, qtext, qmarks, section_hint=None):
        if _to_number(qmarks) <= 0:
            return None
        payload = {
            "segments": [
                {
                    "id": str(qid),
                    "text": str(qtext or "").strip(),
                    "marks": _to_number(qmarks),
                    "section": section_hint or "Q1",
                }
            ]
        }
        try:
            generated_json = generate_rubrics_from_json(json.dumps(payload, ensure_ascii=False))
            parsed = json.loads(generated_json)
            rows = parsed.get("rubrics") if isinstance(parsed, dict) else []
            if isinstance(rows, list) and rows:
                row = rows[0] if isinstance(rows[0], dict) else None
                if row and str(row.get("rubric") or "").strip():
                    return row
        except Exception:
            return None
        return None

    target_question_text = ""
    target_rubric_text = ""
    target_question_ref = None
    for question in exam.get("questions", []):
        if str(question.get("questionId")) == question_id:
            if data.get("questionText") is not None:
                question["questionText"] = data["questionText"]
            if new_max_marks is not None:
                question["maxMarks"] = new_max_marks
                # Keep inline question rubric caps aligned when only marks are edited.
                if data.get("rubric") is None and isinstance(question.get("rubric"), list):
                    for item in question["rubric"]:
                        if isinstance(item, dict):
                            item["maxMarks"] = new_max_marks
            if data.get("rubric") is not None:
                question["rubric"] = data["rubric"]
            target_question_text = str(question.get("questionText") or "")
            if isinstance(question.get("rubric"), list) and question.get("rubric"):
                target_rubric_text = " ".join(
                    f"{item.get('description', '')}".strip()
                    for item in question.get("rubric", [])
                    if isinstance(item, dict)
                ).strip()
            target_question_ref = question
    for rubric in exam.get("rubrics", []):
        if str(rubric.get("id")) == question_id:
            if data.get("rubric") is not None:
                rubric["rubric"] = " ".join(
                    f"{item.get('description', '')} ({item.get('maxMarks', 0)} marks)."
                    for item in data["rubric"]
                )
                # If client submits criteria through rubric payload path in future, keep as-is.
            elif new_max_marks is not None:
                # Marks edited without rubric payload: keep existing rubric text,
                # but rescale stored criteria so evaluation is no longer 0/0.
                if isinstance(rubric.get("criteria"), list):
                    rubric["criteria"] = _rescale_criteria(rubric.get("criteria"), new_max_marks)
                else:
                    generated = generate_criteria_for_question(
                        target_question_text,
                        rubric.get("rubric") or target_rubric_text,
                        new_max_marks,
                    )
                    rubric["criteria"] = generated if generated else []

                # If rubric text is placeholder/empty, regenerate full rubric row now that marks exist.
                current_rubric_text = str(rubric.get("rubric") or "").strip().lower()
                is_pending = (
                    ("rubric pending" in current_rubric_text)
                    or ("will be generated when an answer" in current_rubric_text)
                    or (current_rubric_text == "")
                )
                if is_pending and target_question_ref is not None and new_max_marks > 0:
                    generated_row = _generate_single_rubric_row(
                        question_id,
                        target_question_text,
                        new_max_marks,
                        section_hint=str((target_question_ref.get("sourceId") or target_question_ref.get("questionId") or "Q1")).split(".", 1)[0],
                    )
                    if generated_row:
                        new_text = str(generated_row.get("rubric") or "").strip()
                        if new_text:
                            rubric["rubric"] = new_text
                            if isinstance(generated_row.get("criteria"), list):
                                rubric["criteria"] = generated_row.get("criteria")
                            # Keep question snapshot rubric description aligned with rubric store.
                            target_question_ref["rubric"] = [
                                {
                                    "description": new_text,
                                    "maxMarks": new_max_marks,
                                }
                            ]
    stats = _calculate_exam_display_stats(exam["questions"])
    exam["totalMarks"] = _recalculate_exam_total_marks(exam, exam["questions"])
    exam["displayQuestionCount"] = stats["displayQuestionCount"]
    exam["leafSegmentCount"] = len(exam.get("questions") or [])
    get_collection("exams").update_one(
        {"_id": exam["_id"]},
        {
            "$set": {
                "questions": exam["questions"],
                "rubrics": exam["rubrics"],
                "totalMarks": exam["totalMarks"],
                "displayQuestionCount": exam["displayQuestionCount"],
                "leafSegmentCount": exam["leafSegmentCount"],
                "updatedAt": _now(),
            }
        },
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
        "originalFilename": _normalize_upload_filename(filename),
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
        "selectionPolicyApplied": evaluation_bundle.get("selectionPolicyApplied"),
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


def _normalize_upload_filename(filename):
    if not filename:
        return ""
    base = os.path.basename(str(filename)).strip()
    return base or str(filename).strip()


def _find_blocking_duplicate_upload(institution_id, exam_id, filename):
    """
    Latest row for this exam + filename. Allow a new upload only if the last one ended in
    FAILED or FLAGGED (retry). Blocks in-flight and successful copies so API keys are not
    spent on accidental re-uploads.
    """
    base = _normalize_upload_filename(filename)
    if not base:
        return None
    raw = (filename or "").strip()
    or_clauses = [{"originalFilename": base}]
    if raw and raw != base:
        or_clauses.append({"originalFilename": raw})
    esc = re.escape(base)

    coll = get_collection("uploaded_scripts")
    doc = coll.find_one(
        {
            "institutionId": institution_id,
            "examId": str(exam_id),
            "$or": or_clauses
            + [{"originalFilename": {"$regex": rf"(?:^|[\\/]){esc}$", "$options": "i"}}],
        },
        sort=[("createdAt", -1)],
    )
    if not doc:
        return None
    st = doc.get("uploadStatus") or ""
    if st in ("FAILED", "FLAGGED"):
        return None
    return doc


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
        "originalFilename": _normalize_upload_filename(filename),
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
                        "selectionPolicyApplied": evaluation_bundle.get("selectionPolicyApplied"),
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
        filename = _normalize_upload_filename(filename)
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

    force_duplicate = request.form.get("forceDuplicate") in ("1", "true", "yes")

    try:
        file_payloads = []
        for file_storage in files:
            raw = file_storage.read()
            norm = _normalize_upload_filename(file_storage.filename)
            file_payloads.append({"raw": raw, "filename": norm or (file_storage.filename or "upload")})

        results = []
        to_queue = []
        for item in file_payloads:
            fn = item["filename"]
            if not force_duplicate:
                dup = _find_blocking_duplicate_upload(institution_id, exam_id, fn)
                if dup:
                    results.append(
                        {
                            "filename": fn,
                            "status": "SKIPPED_DUPLICATE",
                            "uploadedScriptId": str(dup["_id"]),
                            "reason": (
                                "This file is already uploaded for this exam. Open Scripts to view it, "
                                "or delete that upload before uploading again."
                            ),
                        }
                    )
                    continue
            to_queue.append(item)
            results.append({"filename": fn, "status": "QUEUED"})

        if not to_queue:
            return jsonify(
                {
                    "jobId": None,
                    "status": "ALL_DUPLICATES",
                    "message": "No new uploads — each file already exists for this exam (not failed).",
                    "results": results,
                }
            )

        job_id = BatchManager.create_job("SCRIPT_BATCH", institution_id, created_by, total_files=len(to_queue))

        for item in to_queue:
            process_script_task.delay(
                job_id,
                item["raw"],
                item["filename"],
                exam_id,
                institution_id,
                created_by,
            )

        return jsonify(
            {
                "jobId": job_id,
                "status": "PENDING",
                "message": f"Script processing started for {len(to_queue)} file(s)",
                "results": results,
            }
        )
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
                "selectionPolicyApplied": script.get("selectionPolicyApplied"),
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
        "selectionPolicyApplied": script.get("selectionPolicyApplied"),
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
                "selectionPolicyApplied": evaluation_bundle.get("selectionPolicyApplied"),
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
                "selectionPolicyApplied": evaluation_bundle.get("selectionPolicyApplied"),
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
