import json
import os
import re
import subprocess
import tempfile
from prompts import get_question_structuring_prompt
from agents.utils import get_raw_text


def _normalize_whitespace(value):
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _extract_shared_or_stem_mark(raw_text, base_id):
    pattern = rf"(?ims)\b{re.escape(base_id)}\.\s*(.*?)(?=^\s*\(\s*a\s*\)|^\s*a\))"
    match = re.search(pattern, raw_text or "")
    if not match:
        return None

    stem_text = _normalize_whitespace(match.group(1))
    if not stem_text:
        return None

    or_patterns = [
        r"\banswer\s+any\s+one\b",
        r"\battempt\s+any\s+one\b",
        r"\bchoose\s+any\s+one\b",
        r"\bone\s+of\s+the\s+two\b",
        r"\beither\b",
    ]
    if not any(re.search(pattern, stem_text, flags=re.IGNORECASE) for pattern in or_patterns):
        return None

    mark_match = re.search(r"(\d+(?:\.\d+)?)\s*$", stem_text)
    return mark_match.group(1) if mark_match else None


def _extract_pdf_layout_text(file_content):
    if not file_content:
        return ""

    pdf_path = None
    try:
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as handle:
            handle.write(file_content)
            pdf_path = handle.name

        result = subprocess.run(
            ["pdftotext", "-layout", pdf_path, "-"],
            capture_output=True,
            text=True,
            check=True,
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


def _segment_has_marks(segment):
    existing_marks = segment.get("marks")
    return existing_marks is not None and str(existing_marks).strip()


def _extract_paper_total_marks(raw_text):
    text = str(raw_text or "")
    if not text.strip():
        return None

    patterns = [
        r"\bmaximum\s+marks?\s*[:\-]\s*(\d+(?:\.\d+)?)\b",
        r"\bmax(?:imum)?\.?\s+marks?\s*[:\-]\s*(\d+(?:\.\d+)?)\b",
        r"\bmarks?\s+maximum\s*[:\-]\s*(\d+(?:\.\d+)?)\b",
    ]
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if match:
            return match.group(1)
    return None


def _normalized_line(value):
    return re.sub(r"[^a-z0-9]+", " ", str(value or "").lower()).strip()


def _extract_line_end_mark_from_segment(raw_text, segment):
    segment_text = str(segment.get("text", "")).strip()
    if not segment_text:
        return None

    normalized_segment = _normalized_line(segment_text)
    if not normalized_segment:
        return None

    first_words = normalized_segment.split()[:8]
    if not first_words:
        return None
    needle = " ".join(first_words)

    for line in str(raw_text or "").splitlines():
        normalized_line = _normalized_line(line)
        if needle not in normalized_line:
            continue
        mark_match = re.search(r"(\d+(?:\.\d+)?)\s*$", line.strip())
        if mark_match:
            return mark_match.group(1)
    return None


def _collect_segments_recursive(node, section_name=None, inherited_marks=None, parent_text=None):
    """
    Recursively collects leaf nodes as segments, inheriting properties from parents.
    """
    segments = []
    
    # 1. Inherit or override properties
    current_section = node.get("section") or section_name
    
    # Marks inheritance: prioritize explicit marks, then inherited marks, then marks_per_question
    current_marks = node.get("marks")
    if current_marks is None:
        current_marks = node.get("marks_per_question")
    if current_marks is None:
        current_marks = inherited_marks
        
    current_text = str(node.get("text", "")).strip()
    
    # 2. Identify children
    child_keys = ["segments", "sub_questions", "sub_parts"]
    children = []
    for key in child_keys:
        val = node.get(key)
        if isinstance(val, list):
            children.extend(val)
            
    # 3. Handle recursion or leaf collection
    if children:
        # This is a container node (Section, Case Study, or Question with subparts)
        # We pass down the text if it looks like a passage or shared stem
        new_parent_text = current_text if current_text and len(current_text) > 30 else parent_text
        
        for child in children:
            segments.extend(_collect_segments_recursive(child, current_section, current_marks, new_parent_text))
    else:
        # This is a leaf node (Actual question)
        if node.get("id") and current_text:
            segments.append({
                "id": str(node.get("id")).strip(),
                "section": current_section,
                "text": current_text,
                "context": parent_text,
                "marks": current_marks,
                "options": node.get("options")
            })
            
    return segments

def _propagate_shared_or_marks(structured_json_text, raw_text):
    try:
        payload = json.loads(structured_json_text)
    except (TypeError, ValueError, json.JSONDecodeError):
        return structured_json_text

    # 1. Flatten all segments recursively
    all_segments = []
    
    # Handle top-level "sections"
    if "sections" in payload and isinstance(payload["sections"], list):
        for section in payload["sections"]:
            all_segments.extend(_collect_segments_recursive(section))
            
    # Also check if it returned a flat "segments" list instead of "sections"
    elif "segments" in payload and isinstance(payload["segments"], list):
        for segment in payload["segments"]:
            all_segments.extend(_collect_segments_recursive(segment))
            
    if not all_segments:
        return json.dumps(payload)

    # 2. Update payload with flattened segments
    payload["segments"] = all_segments

    # 3. Original propagation logic for IDs like 28a, 28b
    grouped = {}
    for segment in all_segments:
        question_id = str(segment.get("id", "")).strip()
        match = re.match(r"^(\d+)([A-Za-z])$", question_id)
        if not match:
            continue
        grouped.setdefault(match.group(1), []).append(segment)

    for base_id, items in grouped.items():
        if len(items) < 2:
            continue

        shared_mark = _extract_shared_or_stem_mark(raw_text, base_id)
        if not shared_mark:
            continue

        for item in items:
            if _segment_has_marks(item):
                continue
            item["marks"] = shared_mark

    for segment in all_segments:
        if _segment_has_marks(segment):
            continue
        line_mark = _extract_line_end_mark_from_segment(raw_text, segment)
        if line_mark:
            segment["marks"] = line_mark

    return json.dumps(payload)

def extract_question_paper(file_content, mime_type, filename, base64_content, client, fallback_prompt):
    """
    Agent responsible for extracting and structuring the Question Paper.
    """
    # 1. Get raw text
    text = get_raw_text(file_content, mime_type, filename, base64_content, client, fallback_prompt)
    propagation_text = text
    if mime_type == "application/pdf":
        layout_text = _extract_pdf_layout_text(file_content)
        if layout_text.strip():
            propagation_text = layout_text
    paper_total_marks = _extract_paper_total_marks(propagation_text) or _extract_paper_total_marks(text)
    
    # 2. Structure into JSON
    prompt = get_question_structuring_prompt(text)
    try:
        response = client.chat.complete(
            model="mistral-large-latest",
            messages=[{"role": "user", "content": prompt}],
            response_format={"type": "json_object"}
        )
        structured_json = _propagate_shared_or_marks(response.choices[0].message.content, propagation_text)
        try:
            payload = json.loads(structured_json)
        except (TypeError, ValueError, json.JSONDecodeError):
            return structured_json

        # Prioritize total marks from prompt response
        prompt_total = payload.get("total_paper_marks")
        if prompt_total:
            payload["paperTotalMarks"] = prompt_total
        elif paper_total_marks:
            payload["paperTotalMarks"] = paper_total_marks

        return json.dumps(payload)
    except Exception as e:
        print(f"JSON Structuring failed for question paper: {str(e)}")
        return json.dumps({"segments": [], "error": f"Structuring failed: {str(e)}", "raw": text})
