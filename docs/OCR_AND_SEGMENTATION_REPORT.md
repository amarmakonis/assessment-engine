# OCR & Segmentation Technical Report

**Assessment Engine — Models, Pipeline, and Edge Cases**

---

## 1. Executive Summary

This report documents the **OCR (Optical Character Recognition)** and **Answer Segmentation** components of the Assessment Engine. It covers the models used, the end-to-end pipeline, image preprocessing, and the edge cases addressed in segmentation so that raw script text is correctly mapped to per-question answers for evaluation.

---

## 2. Models Used for OCR

### 2.1 Primary Vision Model

| Setting | Default | Purpose |
|--------|---------|--------|
| **OPENAI_MODEL_VISION** | `gpt-4o` | Model used for extracting handwritten and printed text from answer-script page images. |

- **Recommendation:** `gpt-4o` is used by default for best accuracy on handwritten and mixed-format answer booklets.
- The image is sent to the OpenAI Chat Completions API with **Vision** (image input); the model returns a single text response containing the transcribed content of the page.
- **Detail level:** Images are sent with `detail="high"` to preserve fine detail for handwriting.

### 2.2 Supporting Stack (Non-LLM)

| Component | Role |
|-----------|------|
| **pdf2image** (Poppler) | Converts PDF pages to images before Vision OCR. Requires `poppler-utils` (e.g. `pdfinfo`, `pdftoppm`) on the system. |
| **PIL (Pillow)** | Image loading, preprocessing (contrast, sharpness, resize), and saving. |
| **OCR_DPI** (config) | DPI used when converting PDF → image (default: 120; can be increased to 150 for denser scripts). |

### 2.3 OCR Request Flow

- **One image per API call:** Each page is processed separately. For an *N*-page PDF, there are *N* calls to the Vision API.
- **Input:** Page image (PNG/JPEG) as **base64** inside the request body (`data:image/png;base64,...`).
- **Output:** Plain text transcript for that page (no JSON; segmentation consumes the concatenated full script text later).

---

## 3. OCR Pipeline Overview

```
Upload (PDF/Image) → Ingest → [PDF only: Convert to images] → Per-page Vision OCR → Aggregate pages → Segmentation → Evaluation
```

### 3.1 Stages

1. **Ingest (`ingest_file`)**  
   - Downloads the file from storage.  
   - If PDF: triggers `convert_pdf_to_images`.  
   - If single image: triggers `process_page` for page 1, then `aggregate_pages`.

2. **Convert PDF to images (`convert_pdf_to_images`)**  
   - Uses **pdf2image** with **OCR_DPI**.  
   - Saves one PNG per page in a temp directory.  
   - Dispatches one **process_page** task per page (Celery `group`).  
   - Schedules **aggregate_pages** with a countdown so pages can complete.

3. **Process page (`process_page`)**  
   - Runs **image preprocessing** (see Section 4).  
   - Calls **Vision API** once for that page.  
   - Stores result in **OCR page results** (extracted text, confidence, quality flags).  
   - Confidence &lt; **LOW_CONFIDENCE_THRESHOLD** (0.65) adds a `LOW_CONFIDENCE` quality flag.

4. **Aggregate pages (`aggregate_pages`)**  
   - Waits until all pages for the script are available (with retries).  
   - Concatenates page text in order: `"\n\n".join(page_texts)`.  
   - Dispatches **segment_answers** with full script text and confidence/flags.

5. **Segment answers (`segment_answers`)**  
   - Uses the **Segmentation Agent** (LLM) to map full OCR text to per-question answers.  
   - Optionally runs **unmapped-text recovery** (see Section 6).  
   - On success, triggers the evaluation pipeline (**prepare_script**).

---

## 4. Image Preprocessing (Before OCR)

To improve accuracy on faint or noisy handwriting, each page image is preprocessed before being sent to the Vision API:

| Step | Description |
|------|-------------|
| **Mode** | Convert to RGB if not already. |
| **Resize** | If the longest side &gt; 2048 px, downscale (thumbnail) to avoid timeouts. |
| **Contrast** | Enhanced by factor **1.8** to make pencil/faint ink stand out. |
| **Sharpness** | Enhanced by factor **2.0** to crisp character edges. |
| **Color** | Slight desaturation (factor **0.5**) to whiten paper and reduce tint. |
| **Output** | Saved as temporary JPEG (quality 85) and passed to the Vision API; temp file is deleted after the call. |

If preprocessing fails, the original image path is used so OCR still runs.

---

## 5. OCR System Prompt (Rules)

The Vision model is instructed to:

- **Preserve layout:** Line breaks, paragraphs, indentation.  
- **Transcribe verbatim:** No correction of spelling or grammar.  
- **Illegible text:** Use placeholder `[illegible]` when a word cannot be read.  
- **No hallucination:** Output only visible text; no commentary or markdown code fences.  
- **Symbols/math:** Transcribe formulas and special characters if present.  
- **Crossed-out text:** **Ignore** any crossed-out, struck-through, or scratched text; do not include it in the output.

Confidence for the page is derived from the proportion of `[illegible]` tokens in the extracted text (higher illegible count → lower confidence).

---

## 6. Segmentation: Model and Role

### 6.1 Model

| Setting | Default | Purpose |
|--------|---------|---------|
| **OPENAI_MODEL_SEGMENTATION** | `gpt-4o-mini` | LLM used to map full OCR transcript to per-question answers. |

- **OPENAI_SEGMENTATION_MAX_TOKENS** (default 16384) is set high so long answers are not truncated.  
- **SEGMENTATION_MAX_OCR_CHARS** (default 0): no truncation of OCR text; full script is sent.  
- **SEGMENTATION_MAX_QUESTION_TEXT_CHARS** (default 300): each question text can be truncated in the prompt to control token usage.

The agent receives the **exam question list** (with questionIds and question text) and the **full raw OCR transcript**, and returns a structured JSON: one entry per question with `questionId` and `answerText` (or `null`), plus `unmappedText`, `segmentationConfidence`, and `notes`.

---

## 7. Segmentation Edge Cases Addressed

The segmentation prompt and post-processing are designed to handle the following edge cases.

### 7.1 Correct Question Mapping (No Off-by-One)

- **Problem:** Answer written after “31” or “Q31” was sometimes assigned to q32 (or similar).  
- **Handling:** Explicit instructions that the block after a question number maps to **that** question: e.g. “31”/“Q31” → **q31**; “32” → **q32**; “28” → **q28**. Never shift by one.  
- **Prompt:** “Answer after ‘31’ or ‘Q31’ goes to q31, not q32”; “Before setting answerText to null, scan the ENTIRE transcript for that question number in any form.”

### 7.2 Full Answer Text (No Truncation)

- **Problem:** Only the first line or first sentence of an answer was returned.  
- **Handling:** Rules that **answerText** must contain the **full** student response: every line and paragraph until the next question or end of script.  
- **Prompt:** “Include the FULL answer”; “Never output only the first line”; “Do not truncate.”

### 7.3 Section Structure (SECTION A / B / C / D)

- **Problem:** Papers with sections (e.g. SECTION D) and section-relative numbering (e.g. “1)”, “2)”, “3)” in Section D) were not mapped to the correct absolute question IDs.  
- **Handling:**  
  - Use exam question order to infer which questions belong to each section.  
  - After “SECTION D”, “1)” = first question of that section (e.g. q29), “2)” = second (e.g. q30), “3)” = third (e.g. q31).  
- **Prompt:** “Section structure (SECTION A/B/C/D)”; “Section-relative numbering: ‘1)’ in Section D = first question of that section.”

### 7.4 Compound Sub-part Numbering (e.g. 3) 1), 3) 2))

- **Problem:** Numbering like “3) 1)”, “3) 2)”, “3) 3)” (question 3 in section, sub-parts 1–3) was not correctly attributed.  
- **Handling:**  
  - Interpret as question N in section, sub-parts M.  
  - If the exam has a single q31 with sub-parts, combine all blocks into one **answerText** for q31.  
  - If the exam has q31_1, q31_2, q31_3, map each block to the corresponding questionId.  
- **Prompt:** “Compound sub-part numbering”; “Use the exam question structure (questionIds and order) to decide.”

### 7.5 Variety of Question-Number Formats

- **Problem:** Students write question numbers in many ways.  
- **Handling:** Prompt enumerates accepted forms: e.g. “Q1”, “Q26”, “Ques 1”, “1.”, “26.”, “1)”, “26)”, “(26)”, “(31)”, “Answer 1”, “Answer to Q. 26”, “Question no 26”, “26th question”, “Q.No. 26”, “No. 32”, “(a)”, “(i)”, “Ans:”, “Section A”.  
- **Rule:** “Treat that number as the question marker and map **all following lines** of that answer to that question until the next question marker.”

### 7.6 Only Student Response (No Question Stem / Options)

- **Problem:** Repeated question text (e.g. in Hindi/English) or options (A/B/C/D) were included in **answerText**.  
- **Handling:** **answerText** must contain **only** the student’s response: no question stem, no options, no assertion/reason wording. For MCQ/assertion-reason, the student’s answer is their choice (e.g. “(B)”).  
- **Prompt:** “Exclude that repeated question stem”; “Do not include the question, options (A/B/C/D), assertion/reason wording.”

### 7.7 Unmapped Text Recovery (Post-Processing)

- **Problem:** The LLM sometimes left blocks that were clearly answers in **unmappedText**, so those answers were missing for evaluation.  
- **Handling:** After the segmentation LLM returns, a **recovery step** runs:  
  - **Regex** over **unmappedText** for question-number markers (e.g. “Q. 23”, “Question 26”, “23.”, “Ans 31”).  
  - For each match, if that questionId currently has **no** answer, the text block from that marker until the next marker (or end) is assigned to that question.  
  - Only blocks ≥ 15 characters are assigned; questions that already have an answer are left unchanged.  
- **Implementation:** `_recover_answers_from_unmapped()` in the OCR/segment pipeline, using `_QUESTION_MARKER_RE`.

### 7.8 Other Documented Edge Cases in the Prompt

- **Out-of-order answers:** Map by content and question markers, not by position.  
- **Missing answers:** If no identifiable answer for a question, set **answerText** to `null`; never omit the questionId.  
- **UnmappedText usage:** Use only for text that clearly does not belong to any question (headers, footers, “Roll No:”, watermarks, illegible scribbles). When in doubt, map to the most likely question.  
- **Boundaries:** When two answers are adjacent with no clear separator, split at a semantically sensible point and note ambiguity in `notes`.  
- **Essay/long answers:** Preserve full multi-line, multi-page response; use section headers and sub-part markers (e.g. “1.(a)”, “1.(b)”) to split.  
- **OR/choice questions:** One questionId; map the single option the student answered to that question.  
- **Bilingual scripts:** answerText = only the student’s response, not the repeated question in another language.  
- **“Continued on next page”:** Concatenate with the rest of that question’s answer.  
- **Multiple attempts at same question:** Include all text; note in `notes`.  
- **Illegible section:** Put in **unmappedText** and note.

---

## 8. Configuration Reference (OCR & Segmentation)

| Variable | Default | Notes |
|----------|---------|--------|
| **OPENAI_MODEL_VISION** | gpt-4o | Vision OCR model. |
| **OPENAI_MODEL_SEGMENTATION** | gpt-4o-mini | Segmentation model; set to main model for higher accuracy. |
| **OPENAI_SEGMENTATION_MAX_TOKENS** | 16384 | Max tokens for segmentation response (long answers). |
| **SEGMENTATION_MAX_OCR_CHARS** | 0 | Cap on OCR chars sent (0 = full script). |
| **SEGMENTATION_MAX_QUESTION_TEXT_CHARS** | 300 | Truncate question text in prompt (0 = no truncation). |
| **OCR_DPI** | 120 | PDF → image DPI; increase to 150 for denser scripts. |
| **LOW_CONFIDENCE_THRESHOLD** | 0.65 | Below this, page is flagged LOW_CONFIDENCE. |
| **MAX_PAGES_PER_SCRIPT** | 40 | Reject scripts with more pages. |

---

## 9. Summary

- **OCR** uses **OpenAI GPT-4o Vision** (configurable via **OPENAI_MODEL_VISION**) with **one image per API call**, after **PDF→image** (pdf2image/Poppler) and **image preprocessing** (contrast, sharpness, resize).  
- **Segmentation** uses **OpenAI gpt-4o-mini** (configurable via **OPENAI_MODEL_SEGMENTATION**) to map the full OCR transcript to per-question **answerText**, with strict rules and **unmapped-text recovery** to fix missed mappings.  
- **Edge cases** covered include: correct question-number mapping (no off-by-one), full answer text (no truncation), section-based and compound numbering (e.g. SECTION D, “3) 1)”), varied question-number formats, exclusion of question stem/options from **answerText**, and recovery of answers left in **unmappedText** via regex-based post-processing.

This report reflects the behavior of the codebase as implemented in the Assessment Engine.
