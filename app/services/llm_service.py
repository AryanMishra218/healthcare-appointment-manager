import json
import logging
import traceback
import re

from google import genai
from google.genai import types
from flask import current_app

logger = logging.getLogger(__name__)

# The exact prompt structure from the assignment brief, kept as one
# clearly-labeled constant so it's easy to find and tweak.
PRE_VISIT_PROMPT_TEMPLATE = """Analyse these symptoms and return: urgency level (Low / Medium / High), chief complaint, and three suggested questions for the doctor. Symptoms: {symptoms}

Respond with ONLY valid JSON in exactly this shape, no markdown formatting, no extra commentary:
{{
  "urgency_level": "Low",
  "chief_complaint": "one short sentence",
  "suggested_questions": ["question 1", "question 2", "question 3"]
}}"""

GEMINI_MODELS = ["gemini-flash-latest", "gemini-2.5-flash", "gemini-flash-lite-latest"]

def generate_pre_visit_summary(symptoms_text):
    """
    Calls Gemini to turn a patient's free-text symptoms into a structured
    summary for the doctor.

    Returns:
        dict with keys 'urgency_level', 'chief_complaint',
        'suggested_questions' on SUCCESS.
        None on ANY failure (missing API key, network error, malformed
        response, Gemini being down, etc).
    """
    api_key = current_app.config.get("GEMINI_API_KEY")
    if not api_key:
        logger.warning("GEMINI_API_KEY not configured -- skipping AI summary.")
        return None

    try:
        client = genai.Client(api_key=api_key)

        prompt = PRE_VISIT_PROMPT_TEMPLATE.format(symptoms=symptoms_text)
        response = None
        last_error = None
        for model_name in GEMINI_MODELS:
            try:
                response = client.models.generate_content(
                    model=model_name,
                    contents=prompt,
                    config=types.GenerateContentConfig(
                        temperature=0.3,
                        max_output_tokens=2000,
                        thinking_config=types.ThinkingConfig(thinking_budget=0),
                    ),
                )
                print(f"Succeeded with model: {model_name}")
                break
            except Exception as model_err:
                print(f"Model {model_name} failed: {model_err}")
                last_error = model_err
                continue

        if response is None:
            raise last_error

        print("=" * 80)
        print("FULL RESPONSE OBJECT:")
        print(repr(response))
        if response.candidates:
            for i, cand in enumerate(response.candidates):
                print(f"candidate[{i}] finish_reason:", cand.finish_reason)
        print("=" * 80)

        raw_text = response.text or ""
        raw_text = raw_text.strip()

        print("=" * 80)
        print("RAW GEMINI RESPONSE:")
        print(repr(raw_text))
        print("=" * 80)

        # Pull out just the {...} JSON object, ignoring any preamble
        # text or markdown code fences the model adds around it.
        match = re.search(r"\{.*\}", raw_text, re.DOTALL)
        if not match:
            logger.error(f"No JSON object found in Gemini response: {raw_text!r}")
            return None
        json_text = match.group(0)

        print("=" * 80)
        print("EXTRACTED JSON:")
        print(repr(json_text))
        print("=" * 80)

        data = json.loads(json_text)

        required_keys = {"urgency_level", "chief_complaint", "suggested_questions"}
        if not required_keys.issubset(data.keys()):
            logger.error(f"Gemini response missing required keys: {data}")
            return None

        if data["urgency_level"] not in ("Low", "Medium", "High"):
            logger.error(f"Gemini returned invalid urgency_level: {data['urgency_level']}")
            return None

        if not isinstance(data["suggested_questions"], list):
            logger.error("Gemini suggested_questions was not a list.")
            return None

        return data

    except Exception as e:
        print("=" * 80)
        traceback.print_exc()
        print("=" * 80)
        logger.error(f"Gemini pre-visit summary generation failed: {e}")
        return None


def generate_post_visit_summary(clinical_notes, prescription):
    """
    Calls Gemini to convert a doctor's clinical notes + prescription into
    a patient-friendly summary with medication schedule and follow-up
    steps.

    Returns a plain-text summary string on success, or None on ANY
    failure -- same fail-safe philosophy as generate_pre_visit_summary.
    """
    api_key = current_app.config.get("GEMINI_API_KEY")
    if not api_key:
        logger.warning("GEMINI_API_KEY not configured -- skipping post-visit AI summary.")
        return None

    combined_notes = f"Clinical notes: {clinical_notes}\nPrescription: {prescription or 'None prescribed'}"
    prompt = (
        "Convert these clinical notes into a patient-friendly summary with "
        f"medication schedule and follow-up steps: {combined_notes}\n\n"
        "Write in plain, reassuring language a patient with no medical "
        "background can understand. Keep it under 200 words. Respond with "
        "plain text only, no markdown formatting."
    )

    try:
        client = genai.Client(api_key=api_key)
        response = None
        last_error = None
        for model_name in GEMINI_MODELS:
            try:
                response = client.models.generate_content(
                    model=model_name,
                    contents=prompt,
                    config=types.GenerateContentConfig(
                        temperature=0.4,
                        max_output_tokens=800,
                        thinking_config=types.ThinkingConfig(thinking_budget=0),
                    ),
                )
                break
            except Exception as model_err:
                last_error = model_err
                continue

        if response is None:
            raise last_error

        summary_text = response.text.strip()

        if not summary_text:
            logger.error("Gemini returned an empty post-visit summary.")
            return None

        return summary_text

    except Exception as e:
        logger.error(f"Gemini post-visit summary generation failed: {e}")
        return None