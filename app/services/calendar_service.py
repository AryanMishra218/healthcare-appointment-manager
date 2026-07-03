"""
calendar_service.py

The ONLY file in the project that talks to the Google Calendar API.
Every other file calls functions from here.

ARCHITECTURE NOTE:
We store ONE set of OAuth tokens (the clinic's Google account).
Patients and doctors are added as ATTENDEES on each event --
Google sends them invitation emails automatically, which appear
in their own Google Calendars if they accept.

This is how real clinic software works (Zocdoc, Practo etc.)
and avoids requiring every patient to do their own OAuth flow.
"""

import logging
from datetime import datetime, timedelta

from flask import current_app, url_for

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────
#  OAUTH SETUP & TOKEN MANAGEMENT
# ─────────────────────────────────────────────

SCOPES = ["https://www.googleapis.com/auth/calendar.events"]


def _get_flow():
    """
    Builds a Google OAuth2 flow object using the credentials from .env.
    A 'flow' is the object that knows how to talk to Google's auth servers.
    Returns None if credentials are not configured.
    """
    client_id = current_app.config.get("GOOGLE_CLIENT_ID")
    client_secret = current_app.config.get("GOOGLE_CLIENT_SECRET")

    if not client_id or not client_secret:
        logger.warning("Google Calendar credentials not configured.")
        return None

    try:
        from google_auth_oauthlib.flow import Flow
        flow = Flow.from_client_config(
            client_config={
                "web": {
                    "client_id": client_id,
                    "client_secret": client_secret,
                    "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                    "token_uri": "https://oauth2.googleapis.com/token",
                    "redirect_uris": [_get_redirect_uri()],
                }
            },
            scopes=SCOPES,
        )
        flow.redirect_uri = _get_redirect_uri()
        return flow
    except Exception as e:
        logger.error(f"Could not build OAuth flow: {e}")
        return None


def _get_redirect_uri():
    """Returns the OAuth callback URL. Must match what's registered in Google Cloud Console."""
    try:
        return url_for("calendar_oauth.oauth_callback", _external=True)
    except RuntimeError:
        # Outside request context (e.g. in tests) -- return a placeholder
        return "http://localhost:5000/calendar/callback"


def get_authorization_url():
    """
    Step 1 of OAuth: generate the URL to redirect the admin to Google's
    consent page. Returns (url, state) or (None, None) if not configured.
    The 'state' is a random value we'll verify in the callback to prevent
    CSRF attacks on the OAuth flow itself.
    """
    flow = _get_flow()
    if not flow:
        return None, None

    authorization_url, state = flow.authorization_url(
        access_type="offline",   # 'offline' = we get a refresh token too
        include_granted_scopes="true",
        prompt="consent",        # forces Google to show the consent screen
    )                            # even if the user already granted access
    return authorization_url, state


def exchange_code_for_tokens(code, state):
    """
    Step 2 of OAuth: Google redirected back with a 'code'. We exchange
    it for actual tokens and store them in our DB.
    Returns True on success, False on failure.
    """
    flow = _get_flow()
    if not flow:
        return False

    try:
        flow.fetch_token(code=code)
        creds = flow.credentials

        _store_tokens(
            refresh_token=creds.refresh_token,
            access_token=creds.token,
            expiry=creds.expiry,
        )
        return True
    except Exception as e:
        logger.error(f"Token exchange failed: {e}")
        return False


def _store_tokens(refresh_token, access_token=None, expiry=None):
    """
    Saves OAuth tokens to the DB. Overwrites any existing row
    (there is only ever one clinic-level token row, id=1).
    """
    from app.models import db, GoogleOAuthToken
    existing = db.session.get(GoogleOAuthToken, 1)
    if existing:
        existing.refresh_token = refresh_token
        existing.access_token = access_token
        existing.token_expiry = expiry
    else:
        token_row = GoogleOAuthToken(
            id=1,
            refresh_token=refresh_token,
            access_token=access_token,
            token_expiry=expiry,
        )
        db.session.add(token_row)
    db.session.commit()


def _get_credentials():
    """
    Loads stored tokens from the DB and returns a google.oauth2.credentials
    object ready to use with the Calendar API.

    If the access token is expired, google-auth refreshes it automatically
    using the refresh token -- we don't need to do anything special for that.

    Returns None if no tokens are stored (calendar not connected yet).
    """
    from app.models import db, GoogleOAuthToken
    token_row = db.session.get(GoogleOAuthToken, 1)
    if not token_row:
        return None

    client_id = current_app.config.get("GOOGLE_CLIENT_ID")
    client_secret = current_app.config.get("GOOGLE_CLIENT_SECRET")

    try:
        from google.oauth2.credentials import Credentials
        from google.auth.transport.requests import Request

        creds = Credentials(
            token=token_row.access_token,
            refresh_token=token_row.refresh_token,
            token_uri="https://oauth2.googleapis.com/token",
            client_id=client_id,
            client_secret=client_secret,
            scopes=SCOPES,
        )

        # If expired, refresh it and save the new access token
        if creds.expired and creds.refresh_token:
            creds.refresh(Request())
            _store_tokens(
                refresh_token=creds.refresh_token or token_row.refresh_token,
                access_token=creds.token,
                expiry=creds.expiry,
            )

        return creds
    except Exception as e:
        logger.error(f"Could not load/refresh credentials: {e}")
        return None


def is_calendar_connected():
    """Quick check: has the admin connected a Google account yet?"""
    from app.models import db, GoogleOAuthToken
    return db.session.get(GoogleOAuthToken, 1) is not None


# ─────────────────────────────────────────────
#  CALENDAR API OPERATIONS
# ─────────────────────────────────────────────

def _build_service():
    """
    Returns a ready-to-use Google Calendar API service object,
    or None if calendar is not connected or credentials can't be loaded.
    """
    creds = _get_credentials()
    if not creds:
        return None
    try:
        from googleapiclient.discovery import build
        return build("calendar", "v3", credentials=creds)
    except Exception as e:
        logger.error(f"Could not build Calendar service: {e}")
        return None


def _build_event_body(appointment):
    """
    Builds the dictionary that the Google Calendar API expects for a
    calendar event. Patient and doctor are added as attendees --
    Google sends them invitation emails automatically.
    """
    appt_date = appointment.appointment_date.isoformat()

    # Google Calendar needs datetime in ISO 8601 format with timezone
    start_dt = f"{appt_date}T{appointment.start_time.strftime('%H:%M:%S')}"
    end_dt = f"{appt_date}T{appointment.end_time.strftime('%H:%M:%S')}"

    return {
        "summary": f"Appointment: {appointment.patient.name} with Dr. {appointment.doctor.user.name}",
        "description": (
            f"Patient: {appointment.patient.name}\n"
            f"Doctor: Dr. {appointment.doctor.user.name} ({appointment.doctor.specialization})\n"
            f"Booked via HealthConnect"
        ),
        "start": {"dateTime": start_dt, "timeZone": "Asia/Kolkata"},
        "end": {"dateTime": end_dt, "timeZone": "Asia/Kolkata"},
        "attendees": [
            {"email": appointment.patient.email, "displayName": appointment.patient.name},
            {"email": appointment.doctor.user.email, "displayName": f"Dr. {appointment.doctor.user.name}"},
        ],
        # sendUpdates="all" tells Google to email invites to attendees
        # We pass this as a query param, not in the body
    }


def create_calendar_event(appointment):
    """
    Creates a Google Calendar event when an appointment is confirmed.
    Stores the returned event ID on the appointment so we can update/delete later.

    Returns the event ID string on success, or None on any failure.
    Failure here must NEVER crash the booking flow.
    """
    service = _build_service()
    if not service:
        logger.info("Calendar not connected — skipping event creation.")
        return None

    try:
        event_body = _build_event_body(appointment)
        event = service.events().insert(
            calendarId="primary",
            body=event_body,
            sendUpdates="all",    # emails invites to attendees
        ).execute()

        event_id = event.get("id")
        logger.info(f"Calendar event created: {event_id} for appointment {appointment.id}")
        return event_id

    except Exception as e:
        logger.error(f"Calendar event creation failed for appointment {appointment.id}: {e}")
        return None


def update_calendar_event(appointment):
    """
    Updates the calendar event if an appointment is rescheduled.
    If no event ID is stored (event was never created), does nothing.
    """
    if not appointment.google_calendar_event_id:
        return False

    service = _build_service()
    if not service:
        return False

    try:
        event_body = _build_event_body(appointment)
        service.events().update(
            calendarId="primary",
            eventId=appointment.google_calendar_event_id,
            body=event_body,
            sendUpdates="all",
        ).execute()
        logger.info(f"Calendar event updated: {appointment.google_calendar_event_id}")
        return True

    except Exception as e:
        logger.error(f"Calendar event update failed: {e}")
        return False


def delete_calendar_event(appointment):
    """
    Deletes the calendar event when an appointment is cancelled.
    Google notifies all attendees of the cancellation automatically.
    If no event ID is stored, does nothing gracefully.
    """
    if not appointment.google_calendar_event_id:
        return False

    service = _build_service()
    if not service:
        return False

    try:
        service.events().delete(
            calendarId="primary",
            eventId=appointment.google_calendar_event_id,
            sendUpdates="all",    # notifies attendees of cancellation
        ).execute()
        logger.info(f"Calendar event deleted: {appointment.google_calendar_event_id}")
        return True

    except Exception as e:
        logger.error(f"Calendar event deletion failed: {e}")
        return False
