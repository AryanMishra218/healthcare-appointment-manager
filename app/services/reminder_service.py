"""
reminder_service.py

Contains all the logic for:
1. Finding appointments needing a reminder tomorrow
2. Parsing prescription text to extract frequency + duration
3. Deciding which medication reminders to send right now

This file contains LOGIC only -- it never sends emails directly.
It calls email_service functions to do the actual sending, keeping
responsibilities cleanly separated.
"""

import re
import logging
from datetime import date, datetime, timedelta

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────
#  APPOINTMENT REMINDERS
# ─────────────────────────────────────────────

def send_appointment_reminders(app):
    """
    Finds all appointments scheduled for TOMORROW and sends each
    patient a reminder email.

    WHY tomorrow (not today)? Giving 24 hours notice lets patients
    rearrange their day. Same-day reminders are too late to be useful.

    Called by the scheduler once every morning at 8 AM.
    """
    with app.app_context():
        from app.models import db, Appointment, NotificationLog
        from app.services import email_service

        tomorrow = date.today() + timedelta(days=1)

        appointments_tomorrow = Appointment.query.filter_by(
            appointment_date=tomorrow,
            status="booked",
        ).all()

        sent = 0
        for appt in appointments_tomorrow:
            # Avoid duplicate reminders: check if we already sent one today
            already_sent = NotificationLog.query.filter_by(
                related_appointment_id=appt.id,
                notification_type="reminder",
                status="sent",
            ).first()

            if already_sent:
                continue

            email_service.send_appointment_reminder(appt)
            sent += 1

        logger.info(f"Appointment reminder job: sent {sent} reminder(s) for {tomorrow}.")
        return sent


# ─────────────────────────────────────────────
#  PRESCRIPTION PARSING
# ─────────────────────────────────────────────

# Maps common prescription frequency phrases to "times per day"
# Real production systems would use an NLP model for this; for an
# internship assignment, pattern matching is perfectly appropriate.
FREQUENCY_PATTERNS = [
    # Most specific patterns first (order matters for regex matching)
    (r'\b3\s*[x×]\s*(?:daily|day|a day)\b',    3),
    (r'\bthree\s+times?\s+(?:a\s+)?daily?\b',   3),
    (r'\bthrice\s+daily\b',                      3),
    (r'\btid\b',                                 3),  # medical abbreviation
    (r'\b2\s*[x×]\s*(?:daily|day|a day)\b',    2),
    (r'\btwice\s+(?:a\s+)?daily?\b',            2),
    (r'\btwo\s+times?\s+(?:a\s+)?(?:daily?|day|per\s+day)\b', 2),
    (r'\bbd\b|\bbid\b',                         2),  # medical abbreviation
    (r'\bonce\s+(?:a\s+)?daily?\b',             1),
    (r'\b1\s*[x×]\s*(?:daily|day|a day)\b',    1),
    (r'\bonce\s+per\s+day\b',                   1),
    (r'\bod\b',                                  1),  # medical abbreviation
    (r'\bdaily\b',                               1),  # fallback
]

# Maps "times per day" to the clock hours we send reminders at
# Designed to spread them across waking hours (8am, 2pm, 8pm)
REMINDER_TIMES = {
    1: [8],           # once daily  → 8 AM
    2: [8, 20],       # twice daily → 8 AM, 8 PM
    3: [8, 14, 20],   # three times → 8 AM, 2 PM, 8 PM
}


def parse_frequency(prescription_text):
    """
    Extracts how many times per day a medication should be taken.
    Returns an int (1, 2, or 3) or None if we can't determine it.

    Example inputs and expected outputs:
        "Paracetamol 500mg, twice daily, after meals"  → 2
        "Amoxicillin 250mg, 3x/day, for 7 days"        → 3
        "Vitamin C, once daily"                         → 1
        "Apply topically as needed"                     → None (no frequency found)
    """
    if not prescription_text:
        return None

    text = prescription_text.lower()
    for pattern, freq in FREQUENCY_PATTERNS:
        if re.search(pattern, text, re.IGNORECASE):
            return freq

    return None


def parse_duration_days(prescription_text):
    """
    Extracts how many days a prescription lasts.
    Returns an int or None if we can't determine it.

    Example inputs:
        "for 5 days"  → 5
        "7-day course" → 7
        "take for two weeks" → 14
        "as needed" → None
    """
    if not prescription_text:
        return None

    text = prescription_text.lower()

    # "for N days" or "N days"
    match = re.search(r'for\s+(\d+)\s+days?', text)
    if match:
        return int(match.group(1))

    match = re.search(r'(\d+)[\s-]day(?:s)?\s+course', text)
    if match:
        return int(match.group(1))

    # "for N weeks"
    match = re.search(r'for\s+(\d+)\s+weeks?', text)
    if match:
        return int(match.group(1)) * 7

    # Word numbers: "two weeks", "five days"
    word_to_num = {'one': 1, 'two': 2, 'three': 3, 'four': 4, 'five': 5,
                   'six': 6, 'seven': 7, 'ten': 10, 'fourteen': 14}
    for word, num in word_to_num.items():
        if re.search(rf'for\s+{word}\s+days?', text):
            return num
        if re.search(rf'for\s+{word}\s+weeks?', text):
            return num * 7

    return None


def should_send_medication_reminder_now(visit_date, frequency_per_day, duration_days):
    """
    Given visit date, frequency, and duration: should we send a reminder
    RIGHT NOW (at the current hour)?

    Logic:
    1. If today is after (visit_date + duration_days), the course is over → False
    2. If today is the visit day itself, skip day 0 → False  
    3. Check if the current hour matches one of the reminder times → True/False

    Returns True if a reminder should be sent, False otherwise.
    """
    if frequency_per_day not in REMINDER_TIMES:
        return False

    today = date.today()
    current_hour = datetime.now().hour

    # Hasn't started yet (shouldn't happen, but be safe)
    if today < visit_date:
        return False

    # Course is finished
    if duration_days and today > visit_date + timedelta(days=duration_days):
        return False

    # Skip the day of the visit itself (patient just got home, not ready yet)
    if today == visit_date:
        return False

    reminder_hours = REMINDER_TIMES[frequency_per_day]
    return current_hour in reminder_hours


# ─────────────────────────────────────────────
#  MEDICATION REMINDER JOB
# ─────────────────────────────────────────────

def send_medication_reminders(app):
    """
    Scans all completed appointments with prescriptions and sends
    medication reminders for any that are due right now.

    Called by the scheduler every hour.
    """
    with app.app_context():
        from app.models import db, Appointment, VisitNote, NotificationLog
        from app.services import email_service

        # Only look at appointments that were completed (have visit notes + prescription)
        completed = (
            Appointment.query
            .join(VisitNote, Appointment.id == VisitNote.appointment_id)
            .filter(
                Appointment.status == "completed",
                VisitNote.prescription.isnot(None),
                VisitNote.prescription != "",
            )
            .all()
        )

        sent = 0
        for appt in completed:
            prescription = appt.visit_note.prescription
            frequency = parse_frequency(prescription)
            duration = parse_duration_days(prescription)

            if not frequency:
                # Can't parse frequency → skip (don't guess)
                continue

            if not should_send_medication_reminder_now(
                appt.appointment_date, frequency, duration
            ):
                continue

            # Avoid sending duplicate reminders in the same hour
            # Check if we sent one in the last 60 minutes for this appointment
            one_hour_ago = datetime.utcnow() - timedelta(hours=1)
            recent_reminder = NotificationLog.query.filter(
                NotificationLog.related_appointment_id == appt.id,
                NotificationLog.notification_type == "medication_reminder",
                NotificationLog.status == "sent",
                NotificationLog.sent_at >= one_hour_ago,
            ).first()

            if recent_reminder:
                continue

            # Pull out the individual medication lines from the prescription
            # so the email names the specific medication
            for line in prescription.strip().split("\n"):
                line = line.strip()
                if line:
                    email_service.send_medication_reminder(appt, line)
                    sent += 1
                    break  # one reminder per appointment per trigger

        logger.info(f"Medication reminder job: sent {sent} reminder(s).")
        return sent
