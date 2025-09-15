import os
from google import genai
import json
import logging
from fastapi import HTTPException
# Configure the Gemini client
try:
    client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))
except Exception as e:
    logging.error(f"Error configuring Gemini: {e}", exc_info=True)
    client = None

def generate_json_response(prompt: str):
    """
    Calls the Gemini model with a specific prompt to get a JSON response.
    Uses Gemini's JSON mode for reliable output.
    """
    if not client:
        raise HTTPException(status_code=500, detail="AI client is not configured.")

    try:
        # Using JSON mode
        response = client.models.generate_content(
            model="gemini-2.5-flash-lite",
            contents=prompt,
            config={"response_mime_type": "application/json"}
        )
        # The API returns a string, so we need to parse it into a Python dict
        text_output = response.candidates[0].content.parts[0].text
        return json.loads(text_output)
    except Exception as e:
        logging.error(f"Error generating JSON from AI: {e}", exc_info=True)
        raise HTTPException(status_code=503, detail="AI service failed to generate a valid JSON response.")

def generate_text_response(prompt: str):
    """
    Calls the Gemini model with a prompt to get a simple text response.
    """
    if not client:
        raise HTTPException(status_code=500, detail="AI model is not configured.")

    try:
        response = client.models.generate_content(
            model="gemini-2.5-flash-lite", 
            contents=prompt
        )
        return response.text
    except Exception as e:
        logging.error(f"Error generating text from AI: {e}", exc_info=True)
        raise HTTPException(status_code=503, detail="AI service failed to generate a text response.")
