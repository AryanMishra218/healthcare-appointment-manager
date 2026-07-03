import json
import logging
import traceback

import google.generativeai as genai
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


def generate_pre_visit_summary(symptoms_text):
    """
    Calls Gemini to turn a patient's free-text symptoms into a structured
    summary for the doctor.

    Returns:
        dict with keys 'urgency_level', 'chief_complaint',
        'suggested_questions' on SUCCESS.
        None on ANY failure (missing API key, network error, malformed
        response, Gemini being down, etc).

    *** WHY return None instead of letting exceptions bubble up? ***
    This function is called from inside the booking flow. If an
    exception here was allowed to crash the request, a Gemini outage
    would mean PATIENTS COULD NOT BOOK APPOINTMENTS AT ALL -- a third-
    party AI service being slow should never break our core business
    function. By always returning either a valid dict or None, the
    calling code only ever needs one simple check: "did it work or not."
    """
    api_key = current_app.config.get("GEMINI_API_KEY")
    if not api_key:
        logger.warning("GEMINI_API_KEY not configured -- skipping AI summary.")
        return None

    try:
        genai.configure(api_key=api_key)
        model = genai.GenerativeModel("gemini-flash-latest")

        prompt = PRE_VISIT_PROMPT_TEMPLATE.format(symptoms=symptoms_text)
        response = model.generate_content(
            prompt,
            generation_config={"temperature": 0.3, "max_output_tokens": 300, "response_mime_type": "application/json",},
        )

        raw_text = response.text.strip()

        print("=" * 80)
        print("RAW GEMINI RESPONSE:")
        print(repr(raw_text))
        print("=" * 80)

        # Gemini sometimes wraps JSON in ```json ... ``` markdown fences
        if raw_text.startswith("```"):
            raw_text = raw_text.replace("```json", "").replace("```", "").strip()

        print("=" * 80)
        print("AFTER CLEANUP:")
        print(repr(raw_text))
        print("=" * 80)

        data = json.loads(raw_text)

        # Validate the shape before trusting it -- never let a malformed
        # AI response silently corrupt our database.
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
        # Deliberately broad: ANY failure here (network, parsing,
        # API errors, timeouts) results in graceful degradation,
        # never a crashed request.
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
    failure -- same fail-safe philosophy as generate_pre_visit_summary:
    a Gemini outage must never stop a doctor from completing a visit.
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
        genai.configure(api_key=api_key)
        model = genai.GenerativeModel("gemini-flash-latest")
        response = model.generate_content(
            prompt, generation_config={"temperature": 0.4, "max_output_tokens": 400}
        )
        summary_text = response.text.strip()

        if not summary_text:
            logger.error("Gemini returned an empty post-visit summary.")
            return None

        return summary_text

    except Exception as e:
        logger.error(f"Gemini post-visit summary generation failed: {e}")
        return None
