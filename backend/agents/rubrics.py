import os
from groq import Groq
from prompts import get_rubrics_generation_prompt

def generate_rubrics_from_json(qp_json_str):
    """
    Agent responsible for generating Evaluation Rubrics using Groq.
    """
    api_key = os.getenv("GROQ_API_KEY")
    if not api_key:
        raise Exception("GROQ_API_KEY is missing. Please add it to your .env file to generate rubrics.")
        
    client_groq = Groq(api_key=api_key)
    prompt = get_rubrics_generation_prompt(qp_json_str)

    response = client_groq.chat.completions.create(
        model="llama-3.3-70b-versatile",
        messages=[{"role": "user", "content": prompt}],
        response_format={"type": "json_object"},
        temperature=0.2
    )
    
    return response.choices[0].message.content
