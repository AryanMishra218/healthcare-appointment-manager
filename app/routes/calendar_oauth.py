"""
Routes for the Google Calendar OAuth 2.0 authorization flow.
Only admins can connect/disconnect the clinic's Google Calendar.
"""
import os
from flask import Blueprint, redirect, request, flash, url_for, session, render_template
from flask_login import login_required

from app.utils import roles_required
from app.services import calendar_service

calendar_oauth_bp = Blueprint("calendar_oauth", __name__, url_prefix="/calendar")


@calendar_oauth_bp.route("/status")
@roles_required("admin")
def status():
    """Shows the admin whether Google Calendar is connected and working."""
    connected = calendar_service.is_calendar_connected()
    from app.services.calendar_service import _get_redirect_uri
    redirect_uri = _get_redirect_uri()
    return render_template("admin/calendar_status.html", connected=connected, redirect_uri=redirect_uri)


@calendar_oauth_bp.route("/authorize")
@roles_required("admin")
def authorize():
    """
    Step 1: Admin clicks 'Connect Google Calendar'.
    We generate the Google auth URL and redirect them there.
    The 'state' is saved in the user's session so we can verify it
    when Google redirects back -- this prevents CSRF attacks.
    """
    authorization_url, state = calendar_service.get_authorization_url()

    if not authorization_url:
        flash("Google Calendar credentials are not configured. Please check your .env file.", "error")
        return redirect(url_for("calendar_oauth.status"))

    # Store state in session for verification in the callback
    session["google_oauth_state"] = state

    # Allow insecure transport in development (HTTP instead of HTTPS).
    # Render uses HTTPS so this env var is NOT set in production.
    os.environ["OAUTHLIB_INSECURE_TRANSPORT"] = "1"

    return redirect(authorization_url)


@calendar_oauth_bp.route("/callback")
@roles_required("admin")
def oauth_callback():
    """
    Step 2: Google redirects the admin back here after they click Allow.
    We receive an authorization code and exchange it for real tokens.
    """
    error = request.args.get("error")
    if error:
        flash(f"Google authorization was denied: {error}", "error")
        return redirect(url_for("calendar_oauth.status"))

    code = request.args.get("code")
    state = request.args.get("state")

    # Verify the state parameter matches what we stored -- CSRF protection
    stored_state = session.pop("google_oauth_state", None)
    if not stored_state or stored_state != state:
        flash("Invalid OAuth state. Please try connecting again.", "error")
        return redirect(url_for("calendar_oauth.status"))

    os.environ["OAUTHLIB_INSECURE_TRANSPORT"] = "1"

    success = calendar_service.exchange_code_for_tokens(code, state)

    if success:
        flash("Google Calendar connected successfully! Appointments will now create calendar events.", "success")
    else:
        flash("Failed to connect Google Calendar. Please try again.", "error")

    return redirect(url_for("calendar_oauth.status"))


@calendar_oauth_bp.route("/disconnect", methods=["POST"])
@roles_required("admin")
def disconnect():
    """Admin disconnects the Google Calendar integration."""
    from app.models import db, GoogleOAuthToken
    token = db.session.get(GoogleOAuthToken, 1)
    if token:
        db.session.delete(token)
        db.session.commit()
        flash("Google Calendar disconnected.", "success")
    return redirect(url_for("calendar_oauth.status"))
