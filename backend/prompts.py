"""
Universal Question Paper Prompts
Handles: MCQ, Short Answer, Long Answer, Situational/Case Study,
         OR logic, Any-N-of-M sections, bilingual papers, mixed papers.
"""

def get_question_structuring_prompt(text):
    return f"""
You are an expert question paper parser.

Convert the given question paper into structured JSON.

RULES:
1. Extract ALL questions exactly as written (no rephrasing).
2. Use section_id exactly as on the paper (e.g. Q1, Q2, Q3 — no trailing dot after Q unless printed).
3. Extract instructions like:
   - "Any 6"
   - "All compulsory"
4. Identify question types:
   - mcq
   - short_answer
   - long_answer
   - case_study
5. For case_study / situational problems:
   - Put the scenario in case_text on the PARENT question (type case_study).
   - Each sub-question MUST have id, text, marks. Sub-question ids MUST be compound: if the parent case is id "1", use "1.a", "1.b"; if parent is "2", use "2.a", "2.b", "2.c". Never use bare "a" or "b" alone as id.
6. For ordinary questions, use ids as printed (1, 2, 3 or 1.(a) style — normalize consistently).
7. Extract options (MCQ), sub_questions, case_text as above.
8. total_marks in metadata: use the number from the paper when stated; otherwise null.
9. Do NOT guess marks if not explicitly given on the question or section.

OUTPUT FORMAT (top-level keys ONLY "metadata" and "sections"; no other root keys):

{{
  "metadata": {{
    "title": "",
    "subject": "",
    "duration": "",
    "total_marks": null
  }},
  "sections": [
    {{
      "section_id": "Q1",
      "instruction": "",
      "attempt": null,
      "questions": [
        {{
          "id": "",
          "text": "",
          "type": "",
          "marks": null,
          "options": [],
          "sub_questions": [],
          "case_text": null
        }}
      ]
    }}
  ]
}}

Question Paper:
{text}

Return ONLY JSON.
"""


def get_answer_segmentation_prompt(text):
    return f"""
You are a verbatim text segmenter for STUDENT ANSWER SCRIPTS.
Identify and segment student answers by their question ID.

RULES:
1. ENGLISH ONLY: Ignore Hindi text and administrative noise.
2. EXHAUSTIVE: Process ALL pages to the very end. DO NOT TRUNCATE.
3. VERBATIM: Copy student answers exactly as written.
4. GRANULAR IDs: Capture sub-question IDs (e.g. "1.(a)", "3.1.(b)", "Q.2").
5. CLEAN TEXT: Remove the answer ID label (like "Ans 1", "Q.2.", "or b)") from the START of the text field.
6. SECTION: Identify which section the answer belongs to if indicated.
7. FLEXIBLE ID MATCHING: Normalise IDs — "1a" = "1.(a)", "Q3" = "3", etc.

OUTPUT FORMAT:
{{
  "segments": [
    {{ "id": "1", "section": "A", "text": "..." }},
    {{ "id": "1.(a)", "section": "B", "text": "..." }}
  ]
}}

RAW OCR TEXT:
---
{text}
---

Return ONLY valid JSON. No markdown fences.
"""


def get_pixtral_fallback_prompt():
    return "Extract all text verbatim. Focus on English and ignore non-English text."


def get_rubrics_generation_prompt(qp_json_str):
    return f"""
You are an expert Rubrics Generation Agent.
Generate detailed evaluation rubrics for every question in the Question Paper JSON below.
(The input may contain only longer / higher-mark items; short questions are handled separately.)

RULES:
1. Read each question. Generate a concise, point-based rubric matching the marks available.
2. MCQ / OBJECTIVE:
   - Solve the question using the options and context provided.
   - State: "Correct option is (X) <option text>. Award N mark(s) if correct, otherwise 0."
3. SHORT / LONG / ESSAY:
   - Break into numbered marking points totalling the available marks.
   - Focus on key terms, concepts, legal principles, case names.
4. SITUATIONAL sub-questions: treat each sub-question as its own rubric entry.
5. Never omit a rubric for any question id in the input.
6. For OR questions: provide rubrics for BOTH alternatives.

INPUT JSON:
---
{qp_json_str}
---

OUTPUT FORMAT:
{{
  "rubrics": [
    {{
      "id": "Q.1",
      "rubric": "Correct option is (b) Resolution of disputes involving individuals across different legal jurisdictions. Award 1 mark if correct, otherwise 0.",
      "criteria": [
        {{
          "criterionId": "C1",
          "description": "Correct option identified",
          "maxMarks": 1
        }}
      ]
    }},
    {{
      "id": "3.1.(a)",
      "rubric": "1 mark: State whether English court gives effect to French decree. 1 mark: Explain the public policy / comity rationale. 1 mark: Cite relevant principle or case.",
      "criteria": [
        {{
          "criterionId": "C1",
          "description": "States whether decree is recognized",
          "maxMarks": 1
        }},
        {{
          "criterionId": "C2",
          "description": "Explains legal rationale",
          "maxMarks": 1
        }},
        {{
          "criterionId": "C3",
          "description": "Mentions principle/case",
          "maxMarks": 1
        }}
      ]
    }}
  ]
}}

Return ONLY valid JSON. No markdown fences.
"""


def get_evaluation_prompt(question_text, student_answer, rubric_text, marks, criteria_json=None):
    criteria_block = criteria_json or "[]"
    return f"""
You are an expert exam evaluator grading handwritten student answers extracted using OCR.

QUESTION:
{question_text}

MAXIMUM MARKS:
{marks}

RUBRIC:
{rubric_text}

REQUIRED CRITERIA (use exactly these criterionId values and maxMarks; do not invent new IDs):
{criteria_block}

STUDENT ANSWER (may contain OCR spelling mistakes):
---
{student_answer}
---

IMPORTANT RULES:
1. OCR errors: "inat law" = "international law". Ignore spelling/grammar; evaluate conceptual correctness.
2. Award partial marks whenever a relevant concept appears.
3. Give 0 ONLY if the answer is completely missing or wholly irrelevant.
4. MCQ / OBJECTIVE:
   - If the student wrote the letter OR the text matching the correct option, award FULL marks.
   - Do not require justification for MCQ.
   - Award 0 if the selection is wrong.
5. "score" must be between 0 and {marks} and must equal sum(criteria[].marksAwarded).

BREAKDOWN (required — 2 to 5 criteria):
- Use the REQUIRED CRITERIA list above as the source of truth whenever provided.
- Keep criterionId and maxMarks aligned with REQUIRED CRITERIA.
- If REQUIRED CRITERIA is empty, use IDs C1, C2, ... and ensure sum(maxMarks) = {marks}.
- marksAwarded per criterion; sum(marksAwarded) = score.
- justificationQuote: short verbatim snippet from the student answer (or empty).
- justificationReason: one sentence.
- confidenceScore: 0.0–1.0.

Return JSON ONLY:
{{
  "score": <number>,
  "feedback": "<2-3 sentence summary>",
  "criteria": [
    {{
      "criterionId": "C1",
      "description": "...",
      "maxMarks": <number>,
      "marksAwarded": <number>,
      "justificationQuote": "...",
      "justificationReason": "...",
      "confidenceScore": <number>
    }}
  ],
  "strengths": ["..."],
  "improvements": [{{"criterionId": "C1", "gap": "...", "suggestion": "..."}}],
  "encouragementNote": "..."
}}
"""


def get_rubric_criteria_prompt(question_text, rubric_text, marks):
    return f"""
You are preparing grading criteria during exam setup.

QUESTION:
{question_text}

MAXIMUM MARKS:
{marks}

RUBRIC:
{rubric_text}

Create a criterion template in the SAME structure used during evaluation.

RULES:
1. Return 2 to 5 criteria.
2. Criterion IDs must be C1, C2, C3... in order.
3. Each criterion must have:
   - criterionId
   - description
   - maxMarks
4. Sum of maxMarks must equal {marks}.
5. Keep descriptions concise and rubric-aligned.
6. Return only JSON.

OUTPUT:
{{
  "criteria": [
    {{
      "criterionId": "C1",
      "description": "....",
      "maxMarks": 0
    }}
  ]
}}
"""


def get_extract_answers_prompt(segmented_as_json, ids_str):
    return f"""
Match student answers to these Question IDs: {ids_str}.

RULES:
1. Use the segmented answer JSON below.
2. Be extremely flexible with ID formats:
   - Full exam IDs may include section, e.g. "Q1.1", "Q2.3", "Q3.1.a" — align these with how the student labelled answers.
   - "1.(a)" matches "1a", "1_a", "1.a", "1(a)"
   - "Q.1" / "Q1" matches section-wide numbering
3. JUMBLED ORDER: search the ENTIRE segment list for each ID.
4. CONTENT MATCHING: if ID is ambiguous, use the question context to match.
5. VERBATIM: copy student text exactly.
6. ENGLISH ONLY.
7. If not found after exhaustive search → "Not found in student script".

Segmented Answer Script (JSON):
{segmented_as_json}

Output JSON: [{{"id": "1", "answer": "..."}}, ...]
Return ONLY valid JSON.
"""
