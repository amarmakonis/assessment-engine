import copy
import re

from agents.utils import clean_ocr_text

_WORD_ANY = {
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


def is_compulsory_instruction(instruction):
    text = str(instruction or "").lower()
    return "compulsory" in text or "all questions" in text or "answer all" in text


def detect_paper_type(data):
    sections = (data or {}).get("sections") or []
    if len(sections) == 1 and is_compulsory_instruction(sections[0].get("instruction")):
        return "flat_compulsory"
    return "sectional"


def extract_attempt(instruction):
    if not instruction:
        return None
    text = str(instruction)
    m = re.search(r"Any\s+(\d+)", text, re.IGNORECASE)
    if m:
        return int(m.group(1))
    m = re.search(r"Any\s+([a-z]+)", text, re.IGNORECASE)
    if m:
        w = m.group(1).lower()
        if w in _WORD_ANY:
            return _WORD_ANY[w]
    m = re.search(r"\b(one|two|three|four|five|six|seven|eight|nine|ten)\s+question", text, re.IGNORECASE)
    if m:
        return _WORD_ANY.get(m.group(1).lower())
    m = re.search(r"\b(\d+)\s+question", text, re.IGNORECASE)
    if m:
        return int(m.group(1))
    return None


def extract_section_marks(instruction):
    if not instruction:
        return None
    match = re.search(r'\((\d+)\s*marks?\)', instruction, re.IGNORECASE)
    if match:
        return int(match.group(1))
    match = re.search(r'\((\d+)\)', instruction)
    if match:
        return int(match.group(1))
    return None


def normalize_id(qid):
    """Normalize OCR/LLM ids: 1.(a) → 1.a; strip stray dots. Bare (a) → a (parent prefix added separately)."""
    if qid is None:
        return ""
    s = str(qid).strip()
    if not s:
        return ""
    s = re.sub(r"\s+", "", s)
    s = s.replace("(", ".").replace(")", "")
    s = re.sub(r"\.{2,}", ".", s)
    s = s.strip(".")
    return s


def _ensure_compound_sub_ids(parent_id, sub_questions):
    """Avoid duplicate bare 'a'/'b' ids: force 1.a, 2.b under case parent 1, 2."""
    if not sub_questions:
        return
    p = normalize_id(parent_id)
    if not p:
        return
    for sq in sub_questions:
        sid = normalize_id(sq.get("id"))
        if not sid:
            continue
        if sid.startswith(f"{p}."):
            sq["id"] = sid
            continue
        if re.match(r"^\d+\.", sid):
            sq["id"] = sid
            continue
        sq["id"] = f"{p}.{sid}"


def assign_marks(section):
    total_marks = extract_section_marks(section.get("instruction"))
    attempt = section.get("attempt")

    # Sectional papers: derive marks from (section total / attempt).
    if total_marks and attempt:
        marks_per_q = total_marks / attempt

        for q in section["questions"]:
            if q.get("marks") is None:
                q["marks"] = marks_per_q

            # Sub-questions: keep explicit marks; only split parent marks for missing children.
            if q.get("sub_questions"):
                sub_qs = q["sub_questions"]
                need_split = any(sq.get("marks") is None for sq in sub_qs) or all(
                    sq.get("marks") in (None, 0) for sq in sub_qs
                )
                if need_split:
                    pm = q.get("marks")
                    if pm is not None and len(sub_qs) > 0:
                        try:
                            sub_marks = float(pm) / len(sub_qs)
                        except (TypeError, ValueError):
                            sub_marks = None
                        if sub_marks is not None:
                            sm = int(sub_marks) if sub_marks == int(sub_marks) else sub_marks
                            for sq in sub_qs:
                                if sq.get("marks") is None or sq.get("marks") == 0:
                                    sq["marks"] = sm

        section["derived_marks_per_question"] = marks_per_q
        return section

    # Flat/compulsory papers: do not invent section-level mpq, only propagate from parent when needed.
    for q in section.get("questions", []):
        if q.get("sub_questions"):
            sub_qs = q["sub_questions"]
            if all(sq.get("marks") in (None, 0) for sq in sub_qs):
                pm = q.get("marks")
                if pm is not None and len(sub_qs) > 0:
                    try:
                        sub_marks = float(pm) / len(sub_qs)
                    except (TypeError, ValueError):
                        sub_marks = None
                    if sub_marks is not None:
                        sm = int(sub_marks) if sub_marks == int(sub_marks) else sub_marks
                        for sq in sub_qs:
                            if sq.get("marks") is None or sq.get("marks") == 0:
                                sq["marks"] = sm

    return section


def process_extracted_json(data):
    data = copy.deepcopy(data)
    paper_type = detect_paper_type(data)
    data["paperType"] = paper_type

    for section in data.get("sections", []):
        # normalize/derive attempt limit from both attempt field and instruction text
        raw_attempt = section.get("attempt")
        inferred_attempt = extract_attempt(raw_attempt) or extract_attempt(section.get("instruction"))
        if inferred_attempt is not None:
            section["attempt"] = inferred_attempt
        elif paper_type == "flat_compulsory" and is_compulsory_instruction(section.get("instruction")):
            section["attempt"] = len(section.get("questions", []))

        # normalize question ids
        for q in section.get("questions", []):
            q["id"] = normalize_id(q.get("id"))

            if q.get("sub_questions"):
                for sq in q["sub_questions"]:
                    sq["id"] = normalize_id(sq.get("id"))
                _ensure_compound_sub_ids(q.get("id"), q["sub_questions"])

        # assign marks
        section = assign_marks(section)

        if section.get("total_options") is None and section.get("questions"):
            section["total_options"] = len(section["questions"])

    return data


def global_segment_id(section_id, leaf_id):
    """Unique leaf id across the paper: Q1 + 1 → Q1.1; Q3 + 1.a → Q3.1.a."""
    sid = str(section_id or "").strip()
    lid = str(leaf_id or "").strip()
    if not lid:
        return lid
    if not sid:
        return lid
    prefix = f"{sid}."
    if lid.lower().startswith(prefix.lower()):
        return lid
    return f"{sid}.{lid}"


def _flat_main_id(raw_id):
    rid = str(raw_id or "").strip()
    if not rid:
        return ""
    if rid.lower().startswith("q"):
        return rid
    return f"Q{rid}"


def _sub_suffix(parent_id, sub_id):
    """Normalize child id for `Q7.a` style output in flat papers."""
    p = normalize_id(parent_id)
    s = normalize_id(sub_id)
    if not s:
        return ""
    if p and s.startswith(f"{p}."):
        s = s[len(p) + 1 :]
    parts = [x for x in s.split(".") if x]
    return parts[-1] if parts else s


def _sub_question_line_has_own_marks(text):
    return bool(
        re.search(r"\[\s*\d+(?:\.\d+)?\s*Marks?\s*\]", str(text or ""), re.I)
        or re.search(r"\(\s*\d+(?:\.\d+)?\s*marks?\s*\)", str(text or ""), re.I)
    )


def _should_collapse_instruction_subs(parent_q, sub_qs):
    """
    LLMs often split one long-essay prompt ("In your answer, examine… and determine…")
    into many sub_questions without per-part marks. Collapse back to one segment with the parent's total marks.
    """
    if not sub_qs or len(sub_qs) < 2:
        return False
    try:
        pm = float(parent_q.get("marks")) if parent_q.get("marks") is not None else 0
    except (TypeError, ValueError):
        pm = 0
    if pm <= 0:
        return False
    p_full = f"{parent_q.get('case_text') or ''}\n{parent_q.get('text') or ''}".strip()
    if not p_full:
        return False
    # Trigger when the stem reads like one multi-task essay, not separate exam items with their own marks.
    bridge = re.search(
        r"\bin your answer\b",
        p_full,
        re.I | re.DOTALL,
    ) or re.search(
        r"\b(discuss|examine|determine|assess)\b.*\b(discuss|examine|determine|assess|support)\b",
        p_full,
        re.I | re.DOTALL,
    )
    if not bridge:
        return False
    for sq in sub_qs:
        st = str(sq.get("text") or "")
        if len(st) > 450:
            return False
        if _sub_question_line_has_own_marks(st):
            return False
    return True


def _merge_collapsed_essay_text(parent_q, sub_qs):
    parts = []
    ct = str(parent_q.get("case_text") or "").strip()
    if ct:
        parts.append(ct)
    pt = str(parent_q.get("text") or "").strip()
    chunks = [str(sq.get("text") or "").strip() for sq in sub_qs if str(sq.get("text") or "").strip()]
    combined_subs = "\n\n".join(chunks)
    if pt:
        low_sub = combined_subs.lower()
        low_pt = pt.lower()
        if low_pt in low_sub or (combined_subs and low_sub in low_pt):
            parts.append(pt if len(pt) >= len(combined_subs) else combined_subs)
        else:
            parts.append(pt)
            if combined_subs:
                parts.append(combined_subs)
    elif combined_subs:
        parts.append(combined_subs)
    return "\n\n".join(parts)


def _is_fake_single_subquestion(parent_q, sub_q):
    """
    Collapse synthetic one-child splits often produced by OCR/LLM:
    parent 7 + single child (a) with same marks and near-duplicate text.
    """
    p_text = str(parent_q.get("text") or "").strip().lower()
    s_text = str(sub_q.get("text") or "").strip().lower()
    if not s_text:
        return True
    p_marks = parent_q.get("marks")
    s_marks = sub_q.get("marks")
    same_marks = (p_marks is not None and s_marks is not None and p_marks == s_marks)
    nested_text = bool(p_text and (s_text in p_text or p_text in s_text))
    sid = _sub_suffix(parent_q.get("id"), sub_q.get("id"))
    trivial_suffix = sid in {"a", "i", "1"}
    return same_marks or nested_text or trivial_suffix


def flatten_segments(data):
    segments = []
    paper_type = detect_paper_type(data)

    for section in data.get("sections", []):
        section_id = section.get("section") or section.get("section_id")

        for q in section.get("questions", []):
            if q.get("sub_questions"):
                # For flat compulsory papers, collapse fake one-child splits to keep Q7 (not Q7.a).
                if paper_type == "flat_compulsory" and len(q["sub_questions"]) == 1:
                    only_sq = q["sub_questions"][0]
                    if _is_fake_single_subquestion(q, only_sq):
                        segments.append({
                            "id": _flat_main_id(q.get("id")),
                            "text": only_sq.get("text") or q.get("text"),
                            "marks": only_sq.get("marks") if only_sq.get("marks") is not None else q.get("marks"),
                            "section": section_id,
                            "type": "short_answer",
                            "context": q.get("case_text"),
                        })
                        continue
                if _should_collapse_instruction_subs(q, q["sub_questions"]):
                    leaf_id = _flat_main_id(q.get("id")) if paper_type == "flat_compulsory" else global_segment_id(section_id, q.get("id"))
                    segments.append({
                        "id": leaf_id,
                        "text": _merge_collapsed_essay_text(q, q["sub_questions"]),
                        "marks": q.get("marks"),
                        "section": section_id,
                        "type": q.get("type") or "long_answer",
                        "context": q.get("case_text"),
                    })
                    continue
                for sq in q["sub_questions"]:
                    if paper_type == "flat_compulsory":
                        sid = _flat_main_id(q.get("id"))
                        suffix = _sub_suffix(q.get("id"), sq.get("id"))
                        leaf_id = f"{sid}.{suffix}" if suffix else sid
                    else:
                        leaf_id = global_segment_id(section_id, sq["id"])
                    segments.append({
                        "id": leaf_id,
                        "text": sq["text"],
                        "marks": sq.get("marks"),
                        "section": section_id,
                        "type": "short_answer",
                        "context": q.get("case_text")
                    })
            else:
                leaf_id = _flat_main_id(q.get("id")) if paper_type == "flat_compulsory" else global_segment_id(section_id, q["id"])
                segments.append({
                    "id": leaf_id,
                    "text": q["text"],
                    "marks": q.get("marks"),
                    "section": section_id,
                    "type": q.get("type"),
                    "context": None
                })

    return {
        "segments": segments
    }