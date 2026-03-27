import os
import json
import re
from groq import Groq
from prompts import get_evaluation_prompt


def _looks_like_or_alternative(question_text, rubric_text):
    combined_text = f"{question_text or ''}\n{rubric_text or ''}"
    patterns = [
        r"\banswer\s+any\s+one\b",
        r"\battempt\s+any\s+one\b",
        r"\bchoose\s+any\s+one\b",
        r"\bchoose\s+one\b",
        r"\beither\b",
        r"^\s*or\s*$",
        r"\(\s*or\s*\)",
    ]
    return any(re.search(pattern, combined_text, flags=re.IGNORECASE | re.MULTILINE) for pattern in patterns)

def _to_number(value, default=0):
    if isinstance(value, (int, float)):
        return float(value)

    text = str(value or "").strip()
    if not text:
        return default

    try:
        return float(text)
    except (TypeError, ValueError):
        match = re.search(r"\d+(?:\.\d+)?", text)
        return float(match.group(0)) if match else default

def _extract_marks_from_text(text):
    text = str(text or "").strip()
    if not text:
        return 0

    bracket_match = re.search(r"\[(\d+(?:\.\d+)?)\]", text)
    if bracket_match:
        return float(bracket_match.group(1))

    mark_matches = re.findall(r"(\d+(?:\.\d+)?)\s*marks?\b", text, flags=re.IGNORECASE)
    if not mark_matches:
        return 0

    total = sum(float(match) for match in mark_matches)
    return total

def _clamp01(val, default=0.75):
    try:
        x = float(val)
    except (TypeError, ValueError):
        return default
    return max(0.0, min(1.0, x))


def _normalize_answer_text(value):
    """Accept string/dict/list payloads and return a safe answer string."""
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        # Common structured payloads: {"text": "..."} or {"answer": "..."}
        for key in ("text", "answer", "content"):
            v = value.get(key)
            if isinstance(v, str) and v.strip():
                return v
        try:
            return json.dumps(value, ensure_ascii=False)
        except Exception:
            return str(value)
    if isinstance(value, list):
        try:
            return "\n".join(str(x) for x in value if str(x).strip())
        except Exception:
            return str(value)
    return str(value or "")


def _build_structured_evaluation(eval_json, marks, score, rubric_criteria=None):
    """Turn model JSON into criterionScores + groundedRubric + feedback object."""
    raw_criteria = eval_json.get("criteria") if isinstance(eval_json.get("criteria"), list) else []
    required_criteria = rubric_criteria if isinstance(rubric_criteria, list) else []

    criterion_scores = []
    grounded_criteria = []

    for idx, row in enumerate(raw_criteria):
        if not isinstance(row, dict):
            continue
        cid = str(row.get("criterionId") or f"C{idx + 1}").strip() or f"C{idx + 1}"
        desc = str(row.get("description") or f"Criterion {idx + 1}").strip()
        mx = _to_number(row.get("maxMarks"), default=0)
        aw = _to_number(row.get("marksAwarded"), default=0)
        criterion_scores.append(
            {
                "criterionId": cid,
                "marksAwarded": aw,
                "maxMarks": mx,
                "justificationQuote": str(row.get("justificationQuote") or "").strip(),
                "justificationReason": str(row.get("justificationReason") or "").strip(),
                "confidenceScore": _clamp01(row.get("confidenceScore")),
            }
        )
        grounded_criteria.append(
            {
                "criterionId": cid,
                "description": desc,
                "maxMarks": mx,
                "requiredEvidencePoints": [],
                "isAmbiguous": False,
            }
        )

    if required_criteria:
        llm_by_id = {}
        for row in raw_criteria:
            if not isinstance(row, dict):
                continue
            cid = str(row.get("criterionId") or "").strip()
            if cid and cid not in llm_by_id:
                llm_by_id[cid] = row

        criterion_scores = []
        grounded_criteria = []
        for idx, rc in enumerate(required_criteria):
            if not isinstance(rc, dict):
                continue
            cid = str(rc.get("criterionId") or f"C{idx + 1}").strip() or f"C{idx + 1}"
            desc = str(rc.get("description") or f"Criterion {idx + 1}").strip()
            max_marks = _to_number(rc.get("maxMarks"), default=0)
            llm_row = llm_by_id.get(cid) or {}
            awarded = _to_number(llm_row.get("marksAwarded"), default=0)
            awarded = max(0.0, min(awarded, max_marks))
            criterion_scores.append(
                {
                    "criterionId": cid,
                    "marksAwarded": awarded,
                    "maxMarks": max_marks,
                    "justificationQuote": str(llm_row.get("justificationQuote") or "").strip(),
                    "justificationReason": str(llm_row.get("justificationReason") or "").strip(),
                    "confidenceScore": _clamp01(llm_row.get("confidenceScore")),
                }
            )
            grounded_criteria.append(
                {
                    "criterionId": cid,
                    "description": desc,
                    "maxMarks": max_marks,
                    "requiredEvidencePoints": [],
                    "isAmbiguous": False,
                }
            )

    if not criterion_scores and marks > 0:
        criterion_scores = [
            {
                "criterionId": "OVERALL",
                "marksAwarded": min(max(score, 0), marks),
                "maxMarks": marks,
                "justificationQuote": "",
                "justificationReason": "Single overall score; model did not return per-criterion rows.",
                "confidenceScore": 0.65,
            }
        ]
        grounded_criteria = [
            {
                "criterionId": "OVERALL",
                "description": "Overall answer vs rubric",
                "maxMarks": marks,
                "requiredEvidencePoints": [],
                "isAmbiguous": False,
            }
        ]

    # Normalize maxMarks to sum to marks
    sum_max = sum(_to_number(c["maxMarks"]) for c in criterion_scores)
    if sum_max > 0 and marks > 0 and abs(sum_max - marks) > 0.02:
        scale = marks / sum_max
        for c in criterion_scores:
            c["maxMarks"] = round(_to_number(c["maxMarks"]) * scale, 4)
        for c in grounded_criteria:
            c["maxMarks"] = round(_to_number(c["maxMarks"]) * scale, 4)

    sum_awarded = sum(_to_number(c["marksAwarded"]) for c in criterion_scores)
    if criterion_scores and abs(sum_awarded - score) > 0.05:
        scale_s = score / sum_awarded if sum_awarded > 0 else 0
        for c in criterion_scores:
            c["marksAwarded"] = round(_to_number(c["marksAwarded"]) * scale_s, 4)
        # Clamp each row to its maxMarks
        for c in criterion_scores:
            cap = _to_number(c["maxMarks"])
            c["marksAwarded"] = max(0.0, min(_to_number(c["marksAwarded"]), cap))

    strengths = eval_json.get("strengths")
    if not isinstance(strengths, list):
        strengths = []
    strengths = [str(s).strip() for s in strengths if str(s).strip()]

    improvements_in = eval_json.get("improvements")
    improvements = []
    if isinstance(improvements_in, list):
        for imp in improvements_in:
            if isinstance(imp, dict):
                improvements.append(
                    {
                        "criterionId": str(imp.get("criterionId") or "GENERAL"),
                        "gap": str(imp.get("gap") or "").strip(),
                        "suggestion": str(imp.get("suggestion") or "").strip(),
                    }
                )
            elif isinstance(imp, str) and imp.strip():
                improvements.append({"criterionId": "GENERAL", "gap": imp.strip(), "suggestion": ""})

    summary = str(eval_json.get("feedback") or "").strip()
    encouragement = str(eval_json.get("encouragementNote") or "").strip()

    feedback_obj = {
        "summary": summary,
        "strengths": strengths,
        "improvements": [i for i in improvements if i.get("gap") or i.get("suggestion")],
        "studyRecommendations": [],
        "encouragementNote": encouragement,
    }

    for i, gc in enumerate(grounded_criteria):
        if i < len(criterion_scores):
            gc["maxMarks"] = criterion_scores[i]["maxMarks"]

    grounded = {
        "totalMarks": marks,
        "criteria": grounded_criteria,
        "groundingConfidence": 0.82,
    }

    return criterion_scores, grounded, feedback_obj


def evaluate_mapped_results(mapped_results, rubrics_data):
    """
    Evaluates each mapped answer against its corresponding rubric using Groq.
    Also handles 'OR' logic filtering by keeping the highest scoring choice if multiple are answered,
    or the attempted choice if only one is answered.
    """
    api_key = os.getenv("GROQ_API_KEY")
    client = Groq(api_key=api_key) if api_key else None
    groq_model = os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile")
    rubric_rows = {
        str(r.get("id")): r
        for r in rubrics_data.get("rubrics", [])
        if isinstance(r, dict) and str(r.get("id", "")).strip()
    }
    
    # Keep original paper order stable for downstream UI rendering.
    order_index = {str(item.get("id")): idx for idx, item in enumerate(mapped_results)}
    evaluated_results = []
    
    for item in mapped_results:
        ans = _normalize_answer_text(item.get("answer", ""))
        item["answer"] = ans
        # If not found, score is 0
        if "Not found" in ans or not ans.strip():
            item["score"] = 0
            item["feedback"] = "Not attempted"
            evaluated_results.append(item)
            continue
            
        if not client:
            item["score"] = 0
            item["feedback"] = "Groq API key missing, skipped evaluation"
            evaluated_results.append(item)
            continue
            
        # Find rubric
        rubric_row = rubric_rows.get(str(item.get("id")), {})
        rubric_text = str(rubric_row.get("rubric", "No rubric found"))
        required_criteria = rubric_row.get("criteria") if isinstance(rubric_row.get("criteria"), list) else []
                
        # Marks must come from the mapped item or the extracted question text.
        marks = _to_number(item.get("maxMarks"), default=0)
        q_text = item.get("question", "")
        if marks <= 0:
            marks = _extract_marks_from_text(q_text)
        if marks <= 0:
            item["score"] = 0
            item["feedback"] = "Maximum marks missing for this question; evaluation skipped"
            evaluated_results.append(item)
            continue
                
        # Use context if available
        context = item.get("context", "")
        if context and context not in q_text:
            final_q_text = f"{context}\n\n{q_text}"
        else:
            final_q_text = q_text
                
        criteria_payload = json.dumps(required_criteria, ensure_ascii=False) if required_criteria else "[]"
        prompt = get_evaluation_prompt(final_q_text, ans, rubric_text, marks, criteria_payload)
        try:
            response = client.chat.completions.create(
                model=groq_model,
                messages=[{"role": "user", "content": prompt}],
                response_format={"type": "json_object"},
                temperature=0.1
            )
            eval_json = json.loads(response.choices[0].message.content)
            score = float(eval_json.get("score", 0))
            score = max(0, min(score, marks))
            item["feedback"] = eval_json.get("feedback", "")
            crit, grounded, fb_obj = _build_structured_evaluation(eval_json, marks, score, required_criteria)
            if required_criteria:
                # Ensure persisted score is exactly derived from fixed rubric criteria.
                score = sum(_to_number(c.get("marksAwarded"), 0) for c in crit)
                score = max(0, min(score, marks))
            item["score"] = score
            item["criterionScores"] = crit
            item["groundedRubric"] = grounded
            item["feedbackStructured"] = fb_obj
        except Exception as e:
            item["score"] = 0
            item["feedback"] = f"Evaluation failed: {str(e)}"
            item["criterionScores"] = []
            item["groundedRubric"] = None
            item["feedbackStructured"] = None
            
        evaluated_results.append(item)
        
    # Now handle OR logic grouping
    # Choices typically look like "28a" and "28b"
    choices_group = {}
    final_filtered = []
    
    for item in evaluated_results:
        q_id = str(item["id"])
        # Match pattern like "28a" -> group 1="28", group 2="a"
        match = re.match(r'^(\d+)([a-zA-Z])$', q_id)
        rubric_text = str((rubric_rows.get(q_id) or {}).get("rubric", ""))
        question_text = item.get("question", "")
        if match and _looks_like_or_alternative(question_text, rubric_text):
            base_num = match.group(1)
            if base_num not in choices_group:
                choices_group[base_num] = []
            choices_group[base_num].append(item)
        else:
            final_filtered.append(item)
            
    # Resolve choices
    for base_num, group in choices_group.items():
        if len(group) > 1:
            # We have multiple choices (e.g. 28a, 28b)
            # Find the best one (attempted, highest score)
            attempted_items = [i for i in group if i["feedback"] != "Not attempted"]
            
            if len(attempted_items) == 0:
                # None attempted, just pick the first one
                final_filtered.append(group[0])
            elif len(attempted_items) == 1:
                # Only one attempted, keep it
                final_filtered.append(attempted_items[0])
            else:
                # Multiple attempted, keep highest score
                best_item = max(attempted_items, key=lambda x: float(x.get("score", 0)))
                best_item["feedback"] += " [Selected as best choice among OR alternatives]"
                final_filtered.append(best_item)
        else:
            final_filtered.extend(group)
            
    # Re-sort using original mapped question order (handles Q1.10, Q3.1.a, etc.).
    final_filtered.sort(key=lambda x: order_index.get(str(x.get("id")), 10**9))
    return final_filtered
