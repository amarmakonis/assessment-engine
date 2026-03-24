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

def evaluate_mapped_results(mapped_results, rubrics_data):
    """
    Evaluates each mapped answer against its corresponding rubric using Groq.
    Also handles 'OR' logic filtering by keeping the highest scoring choice if multiple are answered,
    or the attempted choice if only one is answered.
    """
    api_key = os.getenv("GROQ_API_KEY")
    client = Groq(api_key=api_key) if api_key else None
    rubric_lookup = {
        str(r.get("id")): r.get("rubric", "")
        for r in rubrics_data.get("rubrics", [])
    }
    
    evaluated_results = []
    
    for item in mapped_results:
        ans = item.get("answer", "")
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
        rubric_text = rubric_lookup.get(str(item.get("id")), "No rubric found")
                
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
                
        prompt = get_evaluation_prompt(final_q_text, ans, rubric_text, marks)
        try:
            response = client.chat.completions.create(
                model="llama-3.3-70b-versatile",
                messages=[{"role": "user", "content": prompt}],
                response_format={"type": "json_object"},
                temperature=0.1
            )
            eval_json = json.loads(response.choices[0].message.content)
            score = float(eval_json.get("score", 0))
            score = max(0, min(score, marks))
            item["score"] = score
            item["feedback"] = eval_json.get("feedback", "")
        except Exception as e:
            item["score"] = 0
            item["feedback"] = f"Evaluation failed: {str(e)}"
            
        evaluated_results.append(item)
        
    # Now handle OR logic grouping
    # Choices typically look like "28a" and "28b"
    choices_group = {}
    final_filtered = []
    
    for item in evaluated_results:
        q_id = str(item["id"])
        # Match pattern like "28a" -> group 1="28", group 2="a"
        match = re.match(r'^(\d+)([a-zA-Z])$', q_id)
        rubric_text = rubric_lookup.get(q_id, "")
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
            
    # Re-sort to maintain order
    def sort_key(x):
        id_str = str(x["id"])
        match = re.search(r'^(\d+)', id_str)
        num = int(match.group(1)) if match else 999
        return (num, id_str)
        
    final_filtered.sort(key=sort_key)
    return final_filtered
