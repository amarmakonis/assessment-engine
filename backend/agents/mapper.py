import json
import logging
import re
import time

from prompts import get_extract_answers_prompt

logger = logging.getLogger(__name__)

_MISSING_MARKER = "not found in student script"


def _normalize_id(value):
    """
    Compare paper/exam ids with segment ids. Preserves dots so Q1.1 → 1.1 (not 11).
    Normalizes (a) → .a so 1(a) aligns with 1.a.
    """
    s = str(value or "").strip().lower()
    s = re.sub(r"^(q|question|ans|answer)\s*[.\-:]*", "", s, flags=re.IGNORECASE)
    s = s.replace("(", ".").replace(")", "")
    s = re.sub(r"\s+", "", s)
    s = re.sub(r"\.{2,}", ".", s)
    return s.strip(".")


def _extract_segments(segmented_as_json):
    try:
        payload = json.loads(segmented_as_json) if isinstance(segmented_as_json, str) else (segmented_as_json or {})
    except Exception:
        return []
    segments = payload.get("segments") if isinstance(payload, dict) else []
    return segments if isinstance(segments, list) else []


def _numeric_root(value):
    m = re.match(r"^(\d+)", _normalize_id(value))
    return m.group(1) if m else ""


def _apply_fallback_mapping(results, ids, segmented_as_json):
    by_norm = {}
    for row in results:
        key = _normalize_id(row.get("id"))
        if key and key not in by_norm:
            by_norm[key] = row

    segments = _extract_segments(segmented_as_json)
    seg_by_norm = {}
    seg_order = []
    for seg in segments:
        sid = _normalize_id(seg.get("id"))
        if sid and sid not in seg_by_norm:
            seg_by_norm[sid] = seg
            seg_order.append(sid)

    merged = []
    for qid in ids:
        qnorm = _normalize_id(qid)
        current = by_norm.get(qnorm)
        current_answer = str((current or {}).get("answer") or "").strip()
        needs_fill = (not current) or (not current_answer) or (_MISSING_MARKER in current_answer.lower())

        if needs_fill:
            seg = seg_by_norm.get(qnorm)
            strategy = "missing"
            status = "missing"
            matched_segment_id = None
            candidate_segment_ids = []
            # Conservative fallback: only use same numeric root when it maps
            # to exactly one non-empty segment. If multiple (e.g. 2a, 2c),
            # do not guess.
            if not seg:
                qroot = _numeric_root(qid)
                if qroot:
                    candidates = []
                    for sid in seg_order:
                        if _numeric_root(sid) == qroot:
                            candidate = seg_by_norm.get(sid)
                            if candidate and str(candidate.get("text") or "").strip():
                                candidates.append(candidate)
                    candidate_segment_ids = [str(c.get("id") or "").strip() for c in candidates if str(c.get("id") or "").strip()]
                    if len(candidates) == 1:
                        seg = candidates[0]
                        strategy = "root_unique"
                        status = "mapped"
                        matched_segment_id = str(seg.get("id") or "").strip() or None
                    elif len(candidates) > 1:
                        strategy = "ambiguous"
                        status = "ambiguous"
            else:
                strategy = "normalized_exact"
                status = "mapped"
                matched_segment_id = str(seg.get("id") or "").strip() or None
            if seg:
                text = str(seg.get("text") or "").strip()
                if text:
                    current = {
                        "id": qid,
                        "answer": text,
                        "matchStrategy": strategy,
                        "mappingStatus": status,
                        "matchedSegmentId": matched_segment_id,
                        "candidateSegmentIds": candidate_segment_ids,
                    }
                else:
                    current = {
                        "id": qid,
                        "answer": _MISSING_MARKER,
                        "matchStrategy": "missing",
                        "mappingStatus": "missing",
                        "matchedSegmentId": None,
                        "candidateSegmentIds": candidate_segment_ids,
                    }
            else:
                current = {
                    "id": qid,
                    "answer": _MISSING_MARKER,
                    "matchStrategy": strategy,
                    "mappingStatus": status,
                    "matchedSegmentId": matched_segment_id,
                    "candidateSegmentIds": candidate_segment_ids,
                }
        else:
            current["id"] = qid
            current["matchStrategy"] = str(current.get("matchStrategy") or "llm")
            current["mappingStatus"] = str(current.get("mappingStatus") or "mapped")
            current["matchedSegmentId"] = current.get("matchedSegmentId")
            candidate_ids = current.get("candidateSegmentIds")
            current["candidateSegmentIds"] = candidate_ids if isinstance(candidate_ids, list) else []

        merged.append(current)
    return merged


def map_answers(segmented_as_json, ids, client):
    """
    Agent responsible for matching student answers to the corresponding structured questions.
    """
    prompt = get_extract_answers_prompt(segmented_as_json, ', '.join(ids))

    t0 = time.perf_counter()
    response = client.chat.complete(
        model="mistral-large-latest",
        messages=[{"role": "user", "content": prompt}],
        response_format={"type": "json_object"},
    )
    logger.info(
        "Answer mapping (mistral-large-latest) done in %.1fs prompt_chars=%d question_ids=%d",
        time.perf_counter() - t0,
        len(prompt or ""),
        len(ids or []),
    )

    content = response.choices[0].message.content
    parsed = json.loads(content)
    results = parsed if isinstance(parsed, list) else (parsed.get('answers') or parsed.get('results') or [])
    if not isinstance(results, list):
        results = []
    return _apply_fallback_mapping(results, ids, segmented_as_json)
