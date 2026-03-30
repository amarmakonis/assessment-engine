"""
Universal Question Paper Extractor
Handles: MCQ, Short, Long, Situational/Case Study, OR logic,
         Any-N-of-M sections, bilingual papers, mixed papers.
"""

import copy
import json
import logging
import os
import re
import time
import subprocess
import tempfile

from prompts import get_question_structuring_prompt
from agents.utils import get_raw_text
from agents.processor import (
    clean_ocr_text,
    process_extracted_json,
    flatten_segments,
    extract_attempt,
    global_segment_id,
)
from agents.utils import _mistral_error_retryable

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# Low-level text helpers
# ─────────────────────────────────────────────────────────────────────────────

def _normalize_whitespace(value):
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _extract_pdf_layout_text(file_content):
    """Use pdftotext -layout for mark-propagation heuristics."""
    if not file_content:
        return ""
    pdf_path = None
    try:
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as fh:
            fh.write(file_content)
            pdf_path = fh.name
        result = subprocess.run(
            ["pdftotext", "-layout", pdf_path, "-"],
            capture_output=True, text=True, check=True,
        )
        return result.stdout
    except Exception:
        return ""
    finally:
        if pdf_path:
            try:
                os.unlink(pdf_path)
            except OSError:
                pass


def _extract_paper_total_marks(raw_text):
    text = str(raw_text or "")
    patterns = [
        r"\bmaximum\s+marks?\s*[:\-]\s*(\d+(?:\.\d+)?)\b",
        r"\bmax(?:imum)?\.?\s+marks?\s*[:\-]\s*(\d+(?:\.\d+)?)\b",
        r"\bmarks?\s*[:\-]\s*(\d+(?:\.\d+)?)\b",
        r"\[Marks\s*[:\-]?\s*(\d+)\]",
        r"Max\.\s*Marks\s*[:\-]?\s*(\d+)",
    ]
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if match:
            return match.group(1)
    return None


# ─────────────────────────────────────────────────────────────────────────────
# Two-stage JSON structuring
# ─────────────────────────────────────────────────────────────────────────────

def _call_llm_json(client, prompt, label=""):
    """Call the LLM and return raw JSON string or raise."""
    max_attempts = 5
    last_exc = None
    for attempt in range(1, max_attempts + 1):
        try:
            response = client.chat.complete(
                model="mistral-large-latest",
                messages=[{"role": "user", "content": prompt}],
                response_format={"type": "json_object"},
            )
            return response.choices[0].message.content
        except Exception as e:
            last_exc = e
            if attempt < max_attempts and _mistral_error_retryable(e):
                delay = min(120, 8 * (2 ** (attempt - 1)))
                logger.warning(
                    "Mistral structuring (%s) attempt %s/%s: %s — retry in %ss",
                    label or "paper",
                    attempt,
                    max_attempts,
                    e,
                    delay,
                )
                time.sleep(delay)
                continue
            raise
    raise last_exc


def _structure_paper(text, client):
    """Stage 1: Convert raw OCR text → nested structured JSON (metadata + sections only)."""
    prompt = get_question_structuring_prompt(text)
    raw = _call_llm_json(client, prompt, "structure")
    # Strip accidental markdown fences
    raw = re.sub(r"^```(?:json)?\s*", "", raw.strip())
    raw = re.sub(r"\s*```$", "", raw.strip())
    data = json.loads(raw)
    if isinstance(data, dict) and "structured" in data and isinstance(data.get("structured"), dict):
        data = data["structured"]
    return data


# ─────────────────────────────────────────────────────────────────────────────
# Segment enrichment
# ─────────────────────────────────────────────────────────────────────────────

def _section_key(name):
    return re.sub(r"\s+", " ", str(name or "").strip()).lower()


def _parse_marks_from_instruction(instruction_text):
    text = str(instruction_text or "")
    m = re.search(r"\((\d+(?:\.\d+)?)\s*marks?\)", text, flags=re.IGNORECASE)
    if m:
        return m.group(1)
    m = re.search(r"\b(\d+)\s*marks?\b", text, flags=re.IGNORECASE)
    if m:
        return m.group(1)
    m = re.search(r"\((\d+)\)", text)
    if m:
        return m.group(1)
    return None


def _derive_group_marks_considered(section_dict):
    attempt = section_dict.get("attempt")
    if attempt is None:
        attempt = extract_attempt(section_dict.get("instruction") or "")
    mpq = section_dict.get("marks_per_question") or section_dict.get("derived_marks_per_question")
    try:
        a = int(attempt) if attempt is not None else None
    except (TypeError, ValueError):
        a = None
    try:
        mpq_f = float(mpq) if mpq is not None else 0.0
    except (TypeError, ValueError):
        mpq_f = 0.0
    if a and a > 0 and mpq_f > 0:
        val = a * mpq_f
        return int(val) if val == int(val) else val
    parsed = _parse_marks_from_instruction(section_dict.get("instruction") or "")
    if parsed:
        try:
            v = float(parsed)
            return int(v) if v == int(v) else v
        except (TypeError, ValueError):
            return None
    return None


def _apply_structured_section_metadata_main_questions(main_questions, structured_json):
    """Attach section rules once per main block (not repeated on every leaf segment)."""
    sections = structured_json.get("sections") if isinstance(structured_json, dict) else []
    if not isinstance(sections, list):
        return main_questions

    meta_by_key = {}
    for sec in sections:
        if not isinstance(sec, dict):
            continue
        sec_label = sec.get("section") or sec.get("section_id")
        sk = _section_key(sec_label)
        if not sk:
            continue
        marks_cap = _derive_group_marks_considered(sec)
        meta_by_key[sk] = {
            "sectionAttemptLimit": sec.get("attempt") if sec.get("attempt") is not None else extract_attempt(sec.get("instruction") or ""),
            "sectionTotalOptions": sec.get("total_options"),
            "sectionMarksPerQuestion": sec.get("marks_per_question") or sec.get("derived_marks_per_question"),
            "mainQuestionMarksConsidered": marks_cap,
        }

    for mq in main_questions:
        sk = _section_key(mq.get("section"))
        meta = meta_by_key.get(sk)
        if not meta:
            continue
        if meta.get("sectionAttemptLimit") is not None:
            mq["sectionAttemptLimit"] = meta["sectionAttemptLimit"]
        if meta.get("sectionTotalOptions") is not None:
            mq["sectionTotalOptions"] = meta["sectionTotalOptions"]
        mq["sectionMarksPerQuestion"] = meta["sectionMarksPerQuestion"]
        mq["mainQuestionMarksConsidered"] = meta["mainQuestionMarksConsidered"]

    return main_questions


def _hierarchical_ordered_id(source_id):
    """Preserve paper IDs like 1.2, 1.2.3, or 1.(a), 2.(b)."""
    sid = str(source_id or "").strip()
    if not sid:
        return None
    if re.match(r"^\d+\.\d+(?:\.\d+)*$", sid):
        return sid
    if re.match(r"^\d+\.\([^)]+\)(?:\.\([^)]+\))*$", sid):
        return sid
    return None


def _enrich_segments(segments, structured_json, raw_text):
    """
    Attach metadata used by the rest of the pipeline:
      sourceId, mainQuestionId, orderedId
    Also attempt to back-fill missing marks from raw_text line-ends.
    """
    section_order = {}
    section_counter = {}
    main_questions = []

    for segment in segments:
        section_name = str(segment.get("section") or "").strip() or "UNSPECIFIED"

        if section_name not in section_order:
            sec_index = len(section_order) + 1
            section_order[section_name] = sec_index
            section_counter[section_name] = 0
            main_questions.append({
                "id": str(sec_index),
                "section": section_name,
                "items": [],
            })

        sec_index = section_order[section_name]
        section_counter[section_name] += 1
        leaf_index = section_counter[section_name]

        source_id = str(segment.get("id") or "").strip()
        segment["sourceId"] = source_id
        segment["mainQuestionId"] = str(sec_index)

        segment["orderedId"] = _hierarchical_ordered_id(source_id)

        # Back-fill marks from trailing digits in raw layout text
        if not segment.get("marks"):
            line_mark = _extract_line_end_mark(raw_text, segment)
            if line_mark:
                segment["marks"] = line_mark

        main_questions[sec_index - 1]["items"].append({
            "id": segment["orderedId"] or f"{sec_index}.{leaf_index}",
            "sourceId": source_id,
            "text": segment.get("text"),
            "context": segment.get("context"),
            "marks": segment.get("marks"),
            "type": segment.get("type"),
        })

    return segments, main_questions


def _extract_line_end_mark(raw_text, segment):
    """Look for a trailing number on the same line as the start of the question."""
    segment_text = str(segment.get("text", "")).strip()
    if not segment_text:
        return None
    first_words = re.sub(r"[^a-z0-9]+", " ", segment_text.lower()).split()[:8]
    if not first_words:
        return None
    needle = " ".join(first_words)
    for line in str(raw_text or "").splitlines():
        normalised = re.sub(r"[^a-z0-9]+", " ", line.lower())
        if needle in normalised:
            m = re.search(r"(\d+(?:\.\d+)?)\s*$", line.strip())
            if m:
                return m.group(1)
    return None


# ─────────────────────────────────────────────────────────────────────────────
# Fallback: rule-based flattener (used when LLM flatten fails)
# ─────────────────────────────────────────────────────────────────────────────

def _rule_based_flatten(structured_json):
    """
    Walk the nested structure and collect leaf segments without an LLM call.
    """
    segments = []
    meta = structured_json.get("metadata") if isinstance(structured_json.get("metadata"), dict) else {}
    total_marks = (
        structured_json.get("total_paper_marks")
        or meta.get("total_marks")
        or 0
    )

    for section in structured_json.get("sections", []):
        section_name = section.get("section") or section.get("section_id") or ""
        marks_per_q = section.get("marks_per_question") or section.get("derived_marks_per_question")

        for question in section.get("questions", []):
            _collect_leaf(question, section_name, marks_per_q, None, segments)

    return {
        "total_paper_marks": total_marks,
        "paper_title": structured_json.get("paper_title") or meta.get("title", ""),
        "segments": segments,
    }


def _collect_leaf(node, section_name, inherited_marks, parent_context, out):
    sub_qs = node.get("sub_questions") or []
    text = str(node.get("text", "") or "").strip()
    marks = node.get("marks") or inherited_marks
    context = node.get("context") or node.get("case_text") or parent_context
    qtype = node.get("type", "SHORT")

    if sub_qs:
        # Container node — descend into children
        new_context = text if (text and len(text) > 30) else parent_context
        for child in sub_qs:
            _collect_leaf(child, section_name, marks, new_context, out)
    else:
        if node.get("id") and text:
            out.append({
                "id": global_segment_id(section_name, str(node["id"]).strip()),
                "section": section_name,
                "text": text,
                "context": context,
                "marks": marks,
                "type": qtype,
                "options": node.get("options"),
                "or_group": node.get("or_group"),
            })


# ─────────────────────────────────────────────────────────────────────────────
# Public API
# ─────────────────────────────────────────────────────────────────────────────

def _coerce_marks_scalar(value):
    if value is None:
        return None
    try:
        f = float(value)
        return int(f) if f == int(f) else f
    except (TypeError, ValueError):
        return value


def _canonical_subquestion(sq):
    if not isinstance(sq, dict):
        return {}
    out = {}
    if sq.get("id") is not None:
        out["id"] = str(sq["id"]).strip()
    tx = sq.get("text")
    if tx is not None and str(tx).strip():
        out["text"] = str(tx).strip()
    if sq.get("marks") is not None:
        out["marks"] = _coerce_marks_scalar(sq["marks"])
    if sq.get("type") is not None and str(sq.get("type", "")).strip():
        out["type"] = sq["type"]
    return out


def _canonical_question(q):
    if not isinstance(q, dict):
        return {}
    out = {}
    if q.get("id") is not None:
        out["id"] = str(q["id"]).strip()
    tx = q.get("text")
    if tx is not None and str(tx).strip():
        out["text"] = str(tx).strip()
    if q.get("type") is not None and str(q.get("type", "")).strip():
        out["type"] = q["type"]
    if q.get("marks") is not None:
        out["marks"] = _coerce_marks_scalar(q["marks"])
    opts = q.get("options")
    if isinstance(opts, list) and len(opts) > 0:
        out["options"] = opts
    ct = q.get("case_text")
    if ct is not None and str(ct).strip():
        out["case_text"] = str(ct).strip()
    subs = q.get("sub_questions")
    if isinstance(subs, list) and subs:
        cleaned = [_canonical_subquestion(s) for s in subs if isinstance(s, dict)]
        cleaned = [c for c in cleaned if c.get("id")]
        if cleaned:
            out["sub_questions"] = cleaned
    return out


def canonical_structured(structured):
    """
    External contract: only metadata (title, subject, duration, total_marks) and sections
    with section_id, instruction, attempt, derived_marks_per_question, questions.
    Strips pipeline-only fields (e.g. total_options, duplicate section key).
    """
    if not isinstance(structured, dict):
        return {}
    out = {}
    meta = structured.get("metadata")
    if isinstance(meta, dict):
        m = {}
        for k in ("title", "subject", "duration", "total_marks"):
            if k not in meta:
                continue
            val = meta[k]
            if k == "total_marks" and val is not None:
                val = _coerce_marks_scalar(val)
            m[k] = val
        if m:
            out["metadata"] = m
    secs = structured.get("sections")
    if not isinstance(secs, list):
        return out
    out_sections = []
    for sec in secs:
        if not isinstance(sec, dict):
            continue
        sid = sec.get("section_id") or sec.get("section")
        block = {
            "section_id": str(sid).strip() if sid else "",
            "instruction": str(sec.get("instruction") or "").strip(),
            "questions": [],
        }
        if sec.get("attempt") is not None:
            block["attempt"] = sec["attempt"]
        dmp = sec.get("derived_marks_per_question")
        if dmp is None:
            dmp = sec.get("marks_per_question")
        if dmp is not None:
            block["derived_marks_per_question"] = _coerce_marks_scalar(dmp)
        for q in sec.get("questions") or []:
            cq = _canonical_question(q)
            if cq.get("id"):
                block["questions"].append(cq)
        out_sections.append(block)
    out["sections"] = out_sections
    return out


def _minimal_segments(segments):
    """Only id, text, marks, section — matches external contract."""
    out = []
    for s in segments or []:
        if not isinstance(s, dict):
            continue
        sid = str(s.get("id", "")).strip()
        if not sid:
            continue
        row = {
            "id": sid,
            "text": str(s.get("text", "") or "").strip(),
        }
        m = s.get("marks")
        if m is not None:
            row["marks"] = _coerce_marks_scalar(m)
        sec = s.get("section")
        if sec is not None and str(sec).strip() != "":
            row["section"] = sec
        out.append(row)
    return out


def trim_question_paper_to_minimal(question_json):
    """Persist only structured + minimal segments; segments always flattened from structured."""
    if not isinstance(question_json, dict):
        return {"structured": {}, "segments": []}
    raw_struct = question_json.get("structured") or {}
    if raw_struct.get("sections"):
        processed = process_extracted_json(copy.deepcopy(raw_struct))
        canonical = canonical_structured(processed)
        flat = flatten_segments(canonical)
        segs = flat.get("segments") or []
        if not segs:
            segs = _rule_based_flatten(processed).get("segments") or []
    else:
        canonical = canonical_structured(raw_struct)
        segs = question_json.get("segments") or []
    return {
        "structured": canonical,
        "segments": _minimal_segments(segs),
    }


def expand_question_paper_for_pipeline(question_json, file_content=None, mime_type=None):
    """
    From minimal or legacy {structured, segments}, produce enriched segments + mainQuestions
    and top-level totals for _build_exam_payload. Does not mutate the input dict.
    """
    if not isinstance(question_json, dict):
        return {}
    structured_in = question_json.get("structured") or {}
    segments_in = copy.deepcopy(list(question_json.get("segments") or []))

    processed = process_extracted_json(copy.deepcopy(structured_in)) if structured_in.get("sections") else structured_in

    if not segments_in and processed.get("sections"):
        flat = flatten_segments(processed)
        segments_in = flat.get("segments", [])

    propagation_text = ""
    if file_content and mime_type == "application/pdf":
        layout_text = _extract_pdf_layout_text(file_content)
        if layout_text.strip():
            propagation_text = layout_text

    segs, main_questions = _enrich_segments(segments_in, processed, propagation_text)
    main_questions = _apply_structured_section_metadata_main_questions(main_questions, processed)
    if str(processed.get("paperType") or "") == "flat_compulsory":
        # Flat compulsory papers do not have "attempt any" group semantics.
        main_questions = []

    flat_totals = {}
    if processed.get("sections"):
        fr = flatten_segments(processed)
        if isinstance(fr, dict):
            flat_totals = fr

    meta = processed.get("metadata") if isinstance(processed.get("metadata"), dict) else {}
    prompt_total = (
        meta.get("total_marks")
        or processed.get("total_paper_marks")
        or flat_totals.get("total_paper_marks")
    )
    try:
        paper_total_int = int(float(prompt_total)) if prompt_total else None
    except (TypeError, ValueError):
        paper_total_int = None

    return {
        "segments": segs,
        "mainQuestions": main_questions,
        "paperTotalMarks": paper_total_int,
        "paperType": processed.get("paperType"),
        "paper_title": processed.get("paper_title") or meta.get("title", ""),
        "duration": processed.get("duration") or meta.get("duration", ""),
        "instructions": processed.get("instructions", []),
        "structuredSections": processed.get("sections", []),
        "structured": processed,
    }


def extract_question_paper(file_content, mime_type, filename, base64_content, client, fallback_prompt):
    """
    OCR → clean → LLM structure → process_extracted_json → flatten_segments.
    Returns ONLY {"structured", "segments"} (+ error fields on failure).
    """
    # STEP 1: OCR
    raw_text = get_raw_text(file_content, mime_type, filename, base64_content, client, fallback_prompt)

    # STEP 2: CLEAN
    raw_text = clean_ocr_text(raw_text)

    # STEP 3: LLM STRUCTURE
    try:
        structured = _structure_paper(raw_text, client)
    except Exception as e:
        print(f"[extractor] Stage-1 structuring failed: {e}")
        return json.dumps(
            {
                "segments": [],
                "structured": {},
                "error": str(e),
                "raw": raw_text,
                "raw_text": raw_text,
            },
            ensure_ascii=False,
        )

    # STEP 4: PROCESS
    processed = process_extracted_json(structured)

    # STEP 5: Canonical structured + segments from same tree (single source of truth)
    structured_out = canonical_structured(processed)
    flat = flatten_segments(structured_out)
    segments = flat.get("segments", []) if isinstance(flat, dict) else flat

    if not segments:
        flat = flatten_segments(processed)
        segments = flat.get("segments", []) if isinstance(flat, dict) else flat
    if not segments:
        print("[extractor] flatten_segments empty; using rule-based fallback")
        flat = _rule_based_flatten(processed)
        segments = flat.get("segments", [])

    minimal = _minimal_segments(segments)

    return json.dumps(
        {
            "structured": structured_out,
            "segments": minimal,
        },
        ensure_ascii=False,
    )
