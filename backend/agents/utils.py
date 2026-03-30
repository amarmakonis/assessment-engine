import logging
import time

logger = logging.getLogger(__name__)


def _mistral_error_retryable(exc):
    err = str(exc)
    low = err.lower()
    return (
        "429" in err
        or "rate limit" in low
        or "rate_limited" in low
        or "503" in err
        or "504" in err
        or "internal server error" in low
    )


def get_raw_text(file_content, mime_type, filename, base64_content, client, fallback_prompt):
    text = ""
    max_retries = 5
    attempt: int = 0
    ocr_error = None

    while attempt < max_retries:
        try:
            # Try OCR API first
            response = client.ocr.process(
                model="mistral-ocr-latest",
                document={
                    "type": "document_url",
                    "document_url": f"data:{mime_type};base64,{base64_content}",
                    "document_name": filename
                }
            )
            
            if hasattr(response, 'pages'):
                text = "\n\n".join([p.markdown or p.text for p in response.pages])
            break

        except Exception as e:
            ocr_error = e
            attempt += 1
            logger.warning("Mistral OCR attempt %s failed: %s", attempt, e)
            if attempt < max_retries and _mistral_error_retryable(e):
                delay = min(120, 8 * (2 ** (attempt - 1)))
                logger.info("Retrying Mistral OCR in %ss…", delay)
                time.sleep(delay)
                continue

            break

    if not text:
        # Pixtral Fallback
        try:
            response = client.chat.complete(
                model="pixtral-12b-2409",
                messages=[
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": fallback_prompt},
                            { "type": "image_url", "image_url": f"data:{mime_type};base64,{base64_content}" }
                        ]
                    }
                ]
            )
            text = response.choices[0].message.content
        except Exception as e:
            if ocr_error is not None:
                raise Exception(f"OCR failed: {str(ocr_error)}; Pixtral fallback failed: {str(e)}")
            raise Exception(f"Pixtral Fallback failed: {str(e)}")

    return text
import re

def clean_ocr_text(text):
    text = re.sub(r'\n+', '\n', text)
    text = re.sub(r' +', ' ', text)
    text = text.replace('Q .', 'Q.')
    text = re.sub(r'(\d)\s+\.', r'\1.', text)
    return text.strip()