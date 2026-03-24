import json
from prompts import get_answer_segmentation_prompt
from agents.utils import get_raw_text

def segment_answer_script(file_content, mime_type, filename, base64_content, client, fallback_prompt):
    """
    Agent responsible for extracting and segmenting the Answer Script.
    """
    # 1. Get raw text
    text = get_raw_text(file_content, mime_type, filename, base64_content, client, fallback_prompt)
    
    # 2. Structure into JSON
    prompt = get_answer_segmentation_prompt(text)
    try:
        response = client.chat.complete(
            model="mistral-large-latest",
            messages=[{"role": "user", "content": prompt}],
            response_format={"type": "json_object"}
        )
        return response.choices[0].message.content
    except Exception as e:
        print(f"JSON Structuring failed for answer script: {str(e)}")
        return json.dumps({"segments": [], "error": f"Structuring failed: {str(e)}", "raw": text})
