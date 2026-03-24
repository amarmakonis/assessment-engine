def get_question_structuring_prompt(text):
    return f"""
        You are an exhaustive question extractor. Structure the following Question Paper into JSON.
        
        RULES:
        1. ENGLISH ONLY: Strictly ignore/remove all Hindi or non-English characters.
        2. SECTION DETECTION: Detect section headers and instructions (e.g., "Answer any six (12 marks)").
           - Extract "section" name (e.g., "Q.1", "Section A").
           - Extract "attempt" count from instructions (e.g., "Any 6" -> 6).
           - Extract "total_options" (count of questions in that section).
           - Calculate "marks_per_question" = (Total Section Marks / Attempt Count).
        3. MARK CALCULATION:
           - Case 1: "Answer any six (12 marks)" -> marks_per_question = 12 / 6 = 2.
           - Case 2: "Write short notes any two (12 marks)" -> Marks per answer = 6.
           - Case 3: "Answer any three (39 marks)" -> Marks per answer = 13.
           - Case 4: "Answer in not more than two sentences (Any six) (12 marks)" -> marks_per_question = 2.
        4. HIERARCHY & SUBPARTS:
           - Preserve hierarchy: section -> question -> subquestion (e.g., 3a_i, 3a_ii).
           - If a question has subparts (i, ii, etc.), split marks EQUALLY unless specified.
           - Example: Total = 6 marks, i = 3, ii = 3.
           - For Situational/Case Study Questions: Parent CASE is the question, subparts share marks equally.
           - Repeat context text for subparts belonging to the same case study.
        5. OR LOGIC: Maintain OR logic if present.
           - Example: "Answer any two: a) b) c) d)" -> attempt = 2, options = 4.
        6. NO HALLUCINATION: Extract marks ONLY from section rules or explicit mark indicators. Do not guess.
        7. VERBATIM: Do not rephrase the question text.
        8. PAPER TOTAL: Calculate and include the total marks for the entire paper.
        
        OUTPUT FORMAT:
        {{
          "total_paper_marks": 75,
          "sections": [
            {{
              "section": "Q1",
              "attempt": 6,
              "total_options": 8,
              "marks_per_question": 2,
              "segments": [
                {{ "id": "1", "text": "...", "marks": 2 }},
                {{ "id": "3.(a).(i)", "text": "...", "marks": 3 }},
                {{ "id": "3.(a).(ii)", "text": "...", "marks": 3 }}
              ]
            }}
          ]
        }}
        
        NOTE ON IDs: Use standard numbers. Do NOT prefix with "Q" or "Question". For subparts, use format like "1.(a)" or "3.(i)".
        
        Question Paper Text:
        ---
        {text}
        ---
        """

def get_answer_segmentation_prompt(text):
    return f"""
        You are a verbatim text segmenter for STUDENT ANSWER SCRIPTS.
        Identify and segment student answers by their ID (e.g., "1", "31.1", "28a", "29b").
        
        RULES:
        1. ENGLISH ONLY: Ignore/remove Hindi text and administrative noise.
        2. EXHAUSTIVE: Process all pages to the very end. DO NOT TRUNCATE.
        3. VERBATIM: Copy student's answers exactly as written.
        4. GRANULAR IDs & 'OR' CHOICES: Capture sub-question IDs or "OR" choices (e.g., "28a", "29b").
        5. CLEAN TEXT: Remove the answer ID (like "28a.", "Ans 1", "or b)") from the start of the "text" field.
        6. SECTIONS: Identify which Section (e.g., "A", "B", "C") the answer belongs to, if indicated.
        7. FORMAT: Return a JSON OBJECT with a "segments" array.
        
        RAW OCR TEXT:
        ---
        {text}
        ---
        
        OUTPUT JSON:
        {{
          "segments": [
            {{ "id": "1", "section": "A", "text": "..." }},
            {{ "id": "3.(a)", "section": "A", "text": "..." }}
          ]
        }}
        
        NOTE ON IDs: Use the SAME ID format as seen in the question (e.g., "1", "3.(a)", "28.(i)"). Strip redundant prefixes like "Ans" or "Q".
        """

def get_pixtral_fallback_prompt():
    return "Extract all text verbatim. Focus on English and ignore non-English text."

def get_extract_questions_prompt(text):
    return f"""
        You are an exhaustive question extractor. 
        TASK: Extract EVERY SINGLE question from the provided paper.
        
        STRICT RULES:
        1. ENGLISH ONLY: Strictly ignore/remove all Hindi or other non-English characters. If a question is bilingual, extract ONLY the English part.
        2. EXHAUSTIVE: I expect approximately 34 questions. Do not skip any. Look for questions in all sections.
        3. MARKS: Include the marks for each question at the end (e.g., "Why did... [2]").
        4. IDs: Extract the question number/ID exactly as written (e.g., "1", "24.a", "34").
        5. FORMAT: Return a JSON array of objects: [{{"id": "...", "question": "..."}}]
        
        Question Paper Text:
        ---
        {text}
        ---
        
        OUTPUT JSON:
    """

def get_extract_answers_prompt(segmented_as_json, ids_str):
    return f"""
        Match student answers to these Specific Question IDs: {ids_str}.
        
        RULES:
        1. Use the "Segmented Answer Script" (JSON) provided below.
        2. Find the segment in the JSON that corresponds to each Paper ID.
        3. Be extremely flexible with ID formats:
           - "1.(a)" matches "1a", "1_a", "1.a", or "1(a)".
           - "1_i" matches "1(i)", "1.i", "1 i", or "1".
           - "Q.9" matches "9".
        4. JUMBLED ORDER: The student may have answered in any order (e.g., Q9, then Q8, then Q2). Search the entire list of segments for each ID.
        5. CONTENT MATCHING: If the ID is ambiguous, look at the segment text to see if it matches the question context/topic.
        6. VERBATIM: Copy the student's text EXACTLY.
        7. STIRCTLY ENGLISH ONLY.
        8. If an answer is missing or cannot be found after exhaustive search, return "Not found in student script".
        
        Segmented Answer Script (JSON):
        {segmented_as_json}
        
        Output JSON Format: [{{"id": "1", "answer": "..."}}, {{"id": "1.(a)", "answer": "..."}}]
    """

def get_rubrics_generation_prompt(qp_json_str):
    return f"""
        You are an expert Rubrics Generation Agent. 
        Your task is to create detailed evaluation rubrics based on the extracted Question Paper provided below.

        RULES:
        1. Read the Question Paper JSON. For each question, generate a concise point-based rubric.
        2. FOR MCQs / OBJECTIVE QUESTIONS:
           - You MUST SOLVE the question yourself using the provided context/options.
           - Explicitly state the CORRECT OPTION and its text in the rubric.
           - Example Rubric: "Correct option is (B) 1947. Award 1 mark if correct, otherwise 0."
        3. For Subjective Questions:
           - If marks are provided, break the rubric into numbered marking points totaling that value.
           - If marks are NOT provided, do NOT invent them.
        4. Focus on key terms, concepts, or steps.
        5. Never omit a rubric for any question id present in the input JSON.
        
        Question Paper JSON:
        ---
        {qp_json_str}
        ---
        
        OUTPUT JSON FORMAT:
        {{
          "rubrics": [
            {{ 
              "id": "1_i", 
              "rubric": "Correct option is (D) source of unconditional love. Award 1 mark if correct, otherwise 0."
            }}
          ]
        }}
    """

# def get_evaluation_prompt(question_text, student_answer, rubric_text, marks):
#     return f"""
#         You are an Expert Grader.
#         Evaluate the student's answer against the provided rubric and assign a score.
        
#         Question: {question_text}
#         Maximum Marks: {marks}
#         Rubric: {rubric_text}
        
#         Student's Answer:
#         ---
#         {student_answer}
#         ---
        
#         RULES:
#         1. Be objective and strictly follow the points in the rubric.
#         2. Assign a numerical "score" between 0 and the Maximum Marks.
#         3. Provide a brief 1-2 sentence "feedback" explaining why points were awarded or deducted.
#         4. If the student's answer is "Not found in student script" or completely blank/irrelevant, the score is 0.
#         5. FORMAT: Return a JSON object ONLY with "score" and "feedback" keys.
        
#         OUTPUT JSON FORMAT:
#         {{
#             "score": 1.5,
#             "feedback": "The student correctly identified X, but missed the explanation for Y as required by the rubric."
#         }}
#     """



def get_evaluation_prompt(question_text, student_answer, rubric_text, marks):
    return f"""
        You are an expert exam evaluator grading handwritten student answers extracted using OCR.

        QUESTION:
        {question_text}

        MAXIMUM MARKS:
        {marks}

        RUBRIC:
        {rubric_text}

        STUDENT ANSWER (may contain OCR spelling mistakes):
        ---
        {student_answer}
        ---

        IMPORTANT RULES:

        1. The answer may contain OCR errors such as:
           "inat law" instead of "international law",
           "governu" instead of "governs".

        2. Ignore spelling mistakes and grammar errors.
        3. Evaluate based on **conceptual correctness**.
        4. Award **partial marks whenever a relevant concept appears**.
        5. Only give 0 if the answer is completely missing or irrelevant.
        6. FOR MCQ / OBJECTIVE QUESTIONS:
           - Compare the student's selected option/answer against the CORRECT OPTION specified in the rubric.
           - If the student wrote only the letter (e.g., "B") or only the text (e.g., "international law"), and it matches the correct option, award FULL MARKS.
           - Do not expect explanation or justification for MCQs.
           - Award 0 if the selection is incorrect.
        7. Overall "score" must be between **0 and {marks}** and must equal the sum of criteria[].marksAwarded.

        BREAKDOWN (required):
        - Split the rubric into **2 to 5 criteria** (use IDs C1, C2, ...).
        - Each criterion gets maxMarks that reflect its weight; **sum(maxMarks) must equal {marks}** (use decimals if needed).
        - Allocate marksAwarded per criterion; **sum(marksAwarded) must equal score**.
        - justificationQuote: a short verbatim snippet from the student answer (or empty if none).
        - justificationReason: one sentence why that mark was given.
        - confidenceScore: 0.0–1.0 for that criterion.

        FEEDBACK OBJECT (required):
        - strengths: 1–3 short bullet strings.
        - improvements: 0–3 objects with criterionId (e.g. C1), gap (what was weak), suggestion (how to improve).
        - encouragementNote: one short supportive line.

        Return JSON ONLY with this shape:
        {{
          "score": number,
          "feedback": "2-3 sentence summary for the student",
          "criteria": [
            {{
              "criterionId": "C1",
              "description": "What this criterion checks (from rubric)",
              "maxMarks": number,
              "marksAwarded": number,
              "justificationQuote": "string or empty",
              "justificationReason": "string",
              "confidenceScore": number
            }}
          ],
          "strengths": ["..."],
          "improvements": [{{ "criterionId": "C1", "gap": "...", "suggestion": "..." }}],
          "encouragementNote": "..."
        }}
    """
