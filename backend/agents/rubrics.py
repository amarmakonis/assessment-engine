import copy
import json
import os

from groq import Groq

from prompts import get_rubrics_generation_prompt, get_rubric_criteria_prompt


def _to_number(value):
    try:
        if value is None:
            return 0.0
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _normalize_id(value):
    s = str(value or "").strip().lower()
    s = s.replace("(", ".").replace(")", "")
    s = s.replace("_", ".")
    while ".." in s:
        s = s.replace("..", ".")
    if s.startswith("question"):
        s = s[len("question") :]
    if s.startswith("q"):
        s = s[1:]
    s = s.strip(" .:-")
    return s


def _normalize_criteria(rows, marks):
    items = rows if isinstance(rows, list) else []
    cleaned = []
    for i, row in enumerate(items):
        if not isinstance(row, dict):
            continue
        cid = str(row.get("criterionId") or f"C{i + 1}").strip() or f"C{i + 1}"
        desc = str(row.get("description") or f"Criterion {i + 1}").strip()
        mx = _to_number(row.get("maxMarks"))
        if mx < 0:
            mx = 0.0
        cleaned.append({"criterionId": cid, "description": desc, "maxMarks": mx})

    if not cleaned:
        return []

    total = sum(_to_number(x.get("maxMarks")) for x in cleaned)
    target = max(_to_number(marks), 0.0)
    if target <= 0:
        return cleaned
    if total <= 0:
        each = target / len(cleaned)
        for x in cleaned:
            x["maxMarks"] = each
    elif abs(total - target) > 1e-6:
        scale = target / total
        for x in cleaned:
            x["maxMarks"] = _to_number(x.get("maxMarks")) * scale

    for x in cleaned:
        v = _to_number(x.get("maxMarks"))
        x["maxMarks"] = int(v) if v == int(v) else round(v, 4)
    return cleaned


def generate_criteria_for_question(question_text, rubric_text, marks):
    """
    Generate criterion template for a single question using LLM.
    Returns normalized criteria list (can be empty on failure).
    """
    api_key = os.getenv("GROQ_API_KEY")
    if not api_key:
        return []
    try:
        client_groq = Groq(api_key=api_key)
        prompt = get_rubric_criteria_prompt(
            str(question_text or "").strip(),
            str(rubric_text or "").strip(),
            _to_number(marks),
        )
        response = client_groq.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[{"role": "user", "content": prompt}],
            response_format={"type": "json_object"},
            temperature=0.1,
        )
        parsed = json.loads(response.choices[0].message.content)
        rows = parsed.get("criteria") if isinstance(parsed, dict) else []
        return _normalize_criteria(rows, marks)
    except Exception:
        return []


def generate_rubrics_from_json(qp_json_str):
    """
    Generate evaluation rubrics for every question via LLM.
    No deterministic fallback rubric is used.
    """
    data = json.loads(qp_json_str) if isinstance(qp_json_str, str) else (qp_json_str or {})
    segments = data.get("segments") or []
    segments = [copy.deepcopy(s) for s in segments if isinstance(s, dict) and str(s.get("id", "")).strip()]
    if not segments:
        return json.dumps({"rubrics": []}, ensure_ascii=False)

    api_key = os.getenv("GROQ_API_KEY")
    if not api_key:
        raise Exception("GROQ_API_KEY is missing. Please add it to your .env file to generate rubrics.")

    client_groq = Groq(api_key=api_key)

    def _call_for_segments(seg_rows):
        payload = copy.deepcopy(data)
        payload["segments"] = seg_rows
        prompt = get_rubrics_generation_prompt(json.dumps(payload, ensure_ascii=False))
        response = client_groq.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[{"role": "user", "content": prompt}],
            response_format={"type": "json_object"},
            temperature=0.2,
        )
        parsed = json.loads(response.choices[0].message.content)
        rows = parsed.get("rubrics") if isinstance(parsed, dict) else []
        return rows if isinstance(rows, list) else []

    def _first_valid_rubric_text(rows):
        if not isinstance(rows, list):
            return ""
        for r in rows:
            if not isinstance(r, dict):
                continue
            text = str(r.get("rubric", "")).strip()
            if text:
                return text
        return ""

    def _call_criteria_for_question(seg, rubric_text):
        q_text = str(seg.get("text") or "").strip()
        marks = _to_number(seg.get("marks"))
        prompt = get_rubric_criteria_prompt(q_text, str(rubric_text or ""), marks)
        response = client_groq.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[{"role": "user", "content": prompt}],
            response_format={"type": "json_object"},
            temperature=0.1,
        )
        parsed = json.loads(response.choices[0].message.content)
        return _normalize_criteria(parsed.get("criteria") if isinstance(parsed, dict) else [], marks)

    rubrics_out = _call_for_segments(segments)

    # Keep first valid row per id from bulk generation.
    by_id = {}
    by_norm = {}
    for r in rubrics_out:
        if not isinstance(r, dict):
            continue
        rid = str(r.get("id", "")).strip()
        if not rid or rid in by_id:
            continue
        criteria = r.get("criteria") if isinstance(r.get("criteria"), list) else []
        row = {
            "id": rid,
            "rubric": str(r.get("rubric", "")).strip(),
            "criteria": criteria,
        }
        by_id[rid] = row
        rnorm = _normalize_id(rid)
        if rnorm and rnorm not in by_norm:
            by_norm[rnorm] = row

    # Ensure every segment has LLM-generated rubric row.
    for s in segments:
        sid = str(s.get("id", "")).strip()
        if not sid:
            continue
        marks = _to_number(s.get("marks"))
        if marks <= 0:
            # Never copy/borrow rubric content for zero-mark questions.
            picked = {
                "id": sid,
                "rubric": "Rubric pending: question marks are missing. Set marks and regenerate rubric.",
                "criteria": [],
            }
            by_id[sid] = picked
            snorm = _normalize_id(sid)
            if snorm:
                by_norm[snorm] = picked
            continue

        row = by_id.get(sid) or by_norm.get(_normalize_id(sid))
        if row and row.get("rubric"):
            continue
        single_rows = _call_for_segments([s])
        picked = None
        for r in single_rows:
            if not isinstance(r, dict):
                continue
            rid = str(r.get("id", "")).strip() or sid
            picked = {
                "id": sid,
                "rubric": str(r.get("rubric", "")).strip(),
                "criteria": r.get("criteria") if isinstance(r.get("criteria"), list) else [],
            }
            if picked["rubric"]:
                break

        if (not picked or not picked.get("rubric")) and single_rows and marks > 0:
            # Same robustness as evaluation flow: bind first valid generated rubric to requested question id.
            text = _first_valid_rubric_text(single_rows)
            if text:
                picked = {"id": sid, "rubric": text, "criteria": []}

        if (not picked or not picked.get("rubric")) and marks > 0:
            # Last resort: regenerate once more for this single question and bind by request id.
            retry_rows = _call_for_segments([s])
            text = _first_valid_rubric_text(retry_rows)
            if text:
                picked = {"id": sid, "rubric": text, "criteria": []}
        if not picked or not picked.get("rubric"):
            # For zero/missing-mark questions, avoid copying unrelated rubric content.
            picked = {
                "id": sid,
                "rubric": "Rubric pending: question marks are missing. Set marks and regenerate rubric.",
                "criteria": [],
            }
        by_id[sid] = picked
        snorm = _normalize_id(sid)
        if snorm:
            by_norm[snorm] = picked

    final_rubrics = []
    for s in segments:
        sid = str(s.get("id", "")).strip()
        if not sid:
            continue
        hit = by_id.get(sid) or by_norm.get(_normalize_id(sid))
        if not hit or not str(hit.get("rubric", "")).strip():
            hit = {
                "id": sid,
                "rubric": "Rubric pending: question marks are missing. Set marks and regenerate rubric.",
                "criteria": [],
            }
        out = {"id": sid, "rubric": str(hit.get("rubric", "")).strip()}
        criteria = _normalize_criteria(hit.get("criteria"), s.get("marks"))
        if not criteria:
            criteria = _call_criteria_for_question(s, out["rubric"])
        if criteria:
            out["criteria"] = criteria
        final_rubrics.append(out)

    return json.dumps({"rubrics": final_rubrics}, ensure_ascii=False)
