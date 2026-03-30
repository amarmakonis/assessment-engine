import json
import logging
import time

from prompts import get_answer_segmentation_prompt
from agents.utils import get_raw_text

logger = logging.getLogger(__name__)


def segment_answer_script(file_content, mime_type, filename, base64_content, client, fallback_prompt):
    """
    Agent responsible for extracting and segmenting the Answer Script.
    """
    # 1. Get raw text
    text = get_raw_text(file_content, mime_type, filename, base64_content, client, fallback_prompt)
    logger.info(
        "Answer script OCR done: file=%r raw_text_chars=%d",
        filename,
        len(text or ""),
    )

    # 2. Structure into JSON
    prompt = get_answer_segmentation_prompt(text)
    try:
        t0 = time.perf_counter()
        response = client.chat.complete(
            model="mistral-large-latest",
            messages=[{"role": "user", "content": prompt}],
            response_format={"type": "json_object"},
        )
        elapsed = time.perf_counter() - t0
        logger.info(
            "Answer script segmentation (mistral-large-latest) done in %.1fs prompt_chars=%d",
            elapsed,
            len(prompt or ""),
        )
        return response.choices[0].message.content
    except Exception as e:
        print(f"JSON Structuring failed for answer script: {str(e)}")
        return json.dumps({"segments": [], "error": f"Structuring failed: {str(e)}", "raw": text})
