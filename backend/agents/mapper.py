import json
from prompts import get_extract_answers_prompt

def map_answers(segmented_as_json, ids, client):
    """
    Agent responsible for matching student answers to the corresponding structured questions.
    """
    prompt = get_extract_answers_prompt(segmented_as_json, ', '.join(ids))

    response = client.chat.complete(
        model="mistral-large-latest",
        messages=[{"role": "user", "content": prompt}],
        response_format={"type": "json_object"}
    )
    
    content = response.choices[0].message.content
    parsed = json.loads(content)
    results = parsed if isinstance(parsed, list) else (parsed.get('answers') or parsed.get('results') or [])
    return results
