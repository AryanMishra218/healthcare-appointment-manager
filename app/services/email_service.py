"""
email_service.py

Sends emails using Gmail SMTP.
No third-party email library needed -- Python has smtplib built in.

HOW GMAIL SMTP WORKS:
1. We connect to Gmail's mail server (smtp.gmail.com, port 587)
2. We "log in" using your Gmail address + App Password
3. We send the email
4. We disconnect

This is exactly what happens when you send an email from your phone --
we're just doing it from code instead.
"""

import smtplib
import logging
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from datetime import datetime

from flask import current_app
from app.models import db, NotificationLog

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────
#  INTERNAL HELPERS
# ─────────────────────────────────────────────

def _actually_send(to_email, subject, html_body):
    """
    The single point where emails actually leave our app via Gmail.
    Returns (True, None) on success, (False, error_message) on failure.
    """
    gmail_address  = current_app.config.get("GMAIL_ADDRESS")
    gmail_password = current_app.config.get("GMAIL_APP_PASSWORD")

    if not gmail_address or not gmail_password:
        logger.warning("Gmail credentials not configured — email skipped.")
        return False, "Gmail not configured"

    try:
        # Build the email message
        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"]    = f"HealthConnect <{gmail_address}>"
        msg["To"]      = to_email

        # Attach the HTML body
        msg.attach(MIMEText(html_body, "html"))

        # Connect to Gmail's SMTP server
        # Port 587 = TLS (encrypted, required by Gmail)
        with smtplib.SMTP("smtp.gmail.com", 587) as server:
            server.ehlo()           # say hello to the server
            server.starttls()       # upgrade to encrypted connection
            server.ehlo()           # say hello again after encryption
            server.login(gmail_address, gmail_password)
            server.sendmail(gmail_address, to_email, msg.as_string())

        return True, None

    except smtplib.SMTPAuthenticationError:
        error = "Gmail authentication failed. Check your App Password in .env"
        logger.error(error)
        return False, error

    except smtplib.SMTPException as e:
        error = f"SMTP error: {str(e)}"
        logger.error(error)
        return False, error

    except Exception as e:
        error = f"Unexpected email error: {str(e)}"
        logger.error(error)
        return False, error


def _log_and_send(to_email, notification_type, subject, html_body,
                  appointment_id=None, existing_log_id=None):
    """
    Standard wrapper used by every public function:
    1. Create/update a NotificationLog row (always saved to DB first)
    2. Try to send via Gmail
    3. Update the log row with the result (sent or failed)
    """
    if existing_log_id:
        log_entry = db.session.get(NotificationLog, existing_log_id)
        log_entry.status = "retrying"
        log_entry.retry_count += 1
    else:
        log_entry = NotificationLog(
            recipient_email=to_email,
            notification_type=notification_type,
            related_appointment_id=appointment_id,
            status="pending",
        )
        db.session.add(log_entry)

    db.session.commit()

    success, error_msg = _actually_send(to_email, subject, html_body)

    if success:
        log_entry.status  = "sent"
        log_entry.sent_at = datetime.utcnow()
        log_entry.error_message = None
    else:
        log_entry.status = "failed"
        log_entry.error_message = error_msg

    db.session.commit()
    return success


# ─────────────────────────────────────────────
#  EMAIL TEMPLATES
# ─────────────────────────────────────────────

def _base_template(title, body_html):
    """Wraps any email body in a clean, consistent layout."""
    return f"""
    <div style="font-family: Arial, sans-serif; max-width: 520px;
                margin: 0 auto; color: #1C2B2B;">
      <div style="background: #0B6E6E; padding: 20px 24px;
                  border-radius: 8px 8px 0 0;">
        <h1 style="color: white; margin: 0; font-size: 1.2rem;">
          ⚕ HealthConnect
        </h1>
      </div>
      <div style="background: #ffffff; padding: 24px;
                  border: 1px solid #DCE4E3; border-top: none;
                  border-radius: 0 0 8px 8px;">
        <h2 style="color: #084F4F; margin-top: 0;">{title}</h2>
        {body_html}
        <hr style="border: none; border-top: 1px solid #DCE4E3; margin: 24px 0;">
        <p style="color: #5C6B6B; font-size: 0.85rem; margin: 0;">
          This is an automated message from HealthConnect.
          Please do not reply.
        </p>
      </div>
    </div>
    """


def _appointment_details_html(appointment):
    """Reusable appointment info block used in multiple email types."""
    return f"""
    <table style="width:100%; border-collapse: collapse; margin: 16px 0;">
      <tr>
        <td style="padding: 8px 0; color: #5C6B6B; width: 40%;">Doctor</td>
        <td style="padding: 8px 0;">
          <strong>Dr. {appointment.doctor.user.name}</strong>
          ({appointment.doctor.specialization})
        </td>
      </tr>
      <tr>
        <td style="padding: 8px 0; color: #5C6B6B;">Date</td>
        <td style="padding: 8px 0;">
          <strong>
            {appointment.appointment_date.strftime('%A, %d %B %Y')}
          </strong>
        </td>
      </tr>
      <tr>
        <td style="padding: 8px 0; color: #5C6B6B;">Time</td>
        <td style="padding: 8px 0;">
          <strong>
            {appointment.start_time.strftime('%I:%M %p')} –
            {appointment.end_time.strftime('%I:%M %p')}
          </strong>
        </td>
      </tr>
    </table>
    """


# ─────────────────────────────────────────────
#  PUBLIC FUNCTIONS (called from routes)
# ─────────────────────────────────────────────

def send_booking_confirmation_patient(appointment):
    body = f"""
    <p>Hi {appointment.patient.name},</p>
    <p>Your appointment has been <strong>confirmed</strong>.</p>
    {_appointment_details_html(appointment)}
    <p>Please arrive 10 minutes early.</p>
    """
    return _log_and_send(
        to_email=appointment.patient.email,
        notification_type="booking_confirmation",
        subject="Your appointment is confirmed — HealthConnect",
        html_body=_base_template("Appointment Confirmed", body),
        appointment_id=appointment.id,
    )


def send_booking_confirmation_doctor(appointment):
    body = f"""
    <p>Hi Dr. {appointment.doctor.user.name},</p>
    <p>A new appointment has been booked with you:</p>
    {_appointment_details_html(appointment)}
    <p><strong>Patient:</strong> {appointment.patient.name}
       ({appointment.patient.email})</p>
    <p>The patient's symptom form will be in your dashboard.</p>
    """
    return _log_and_send(
        to_email=appointment.doctor.user.email,
        notification_type="booking_confirmation_doctor",
        subject=f"New appointment: {appointment.patient.name} "
                f"on {appointment.appointment_date.strftime('%d %b')}",
        html_body=_base_template("New Appointment Booked", body),
        appointment_id=appointment.id,
    )

def send_doctor_credentials(doctor_user, temp_password):
    """
    Sent once, at doctor account creation. Gives them their Doctor ID
    (their login identifier) and temporary password. Their real email
    is only ever used to receive notifications like this one -- it is
    never used to log in.
    """
    body = f"""
    <p>Hi Dr. {doctor_user.name},</p>
    <p>An account has been created for you on HealthConnect.</p>
    <table style="width:100%; border-collapse: collapse; margin: 16px 0;">
      <tr>
        <td style="padding: 8px 0; color: #5C6B6B; width: 40%;">Doctor ID</td>
        <td style="padding: 8px 0;"><strong>{doctor_user.username}</strong></td>
      </tr>
      <tr>
        <td style="padding: 8px 0; color: #5C6B6B;">Temporary Password</td>
        <td style="padding: 8px 0;"><strong>{temp_password}</strong></td>
      </tr>
    </table>
    <p>Log in at the HealthConnect portal using your <strong>Doctor ID</strong>
       (not your email) and this temporary password. Please change your
       password immediately after logging in, from your dashboard.</p>
    """
    return _log_and_send(
        to_email=doctor_user.email,
        notification_type="doctor_credentials",
        subject="Your HealthConnect Doctor Account",
        html_body=_base_template("Welcome to HealthConnect", body),
    )

def send_cancellation_patient(appointment, reason=None):
    reason_line = f"<p><strong>Reason:</strong> {reason}</p>" if reason else ""
    body = f"""
    <p>Hi {appointment.patient.name},</p>
    <p>Your appointment has been <strong>cancelled</strong>.</p>
    {_appointment_details_html(appointment)}
    {reason_line}
    <p>Please log in to book a new appointment.</p>
    """
    return _log_and_send(
        to_email=appointment.patient.email,
        notification_type="cancellation",
        subject="Your appointment has been cancelled — HealthConnect",
        html_body=_base_template("Appointment Cancelled", body),
        appointment_id=appointment.id,
    )


def send_appointment_reminder(appointment):
    body = f"""
    <p>Hi {appointment.patient.name},</p>
    <p>Reminder: you have an appointment <strong>tomorrow</strong>.</p>
    {_appointment_details_html(appointment)}
    <p>Please arrive 10 minutes early.</p>
    """
    return _log_and_send(
        to_email=appointment.patient.email,
        notification_type="reminder",
        subject="Appointment reminder for tomorrow — HealthConnect",
        html_body=_base_template("Appointment Tomorrow", body),
        appointment_id=appointment.id,
    )


def send_medication_reminder(appointment, medication_line):
    body = f"""
    <p>Hi {appointment.patient.name},</p>
    <p>Medication reminder from your visit with
       Dr. {appointment.doctor.user.name}:</p>
    <p style="background:#F6F8F7; padding:12px;
              border-radius:6px; font-weight:bold;">
       {medication_line}
    </p>
    <p>Contact your doctor if you experience side effects.</p>
    """
    return _log_and_send(
        to_email=appointment.patient.email,
        notification_type="medication_reminder",
        subject="Medication reminder — HealthConnect",
        html_body=_base_template("Medication Reminder", body),
        appointment_id=appointment.id,
    )


def send_visit_summary_notification(appointment):
    body = f"""
    <p>Hi {appointment.patient.name},</p>
    <p>Dr. {appointment.doctor.user.name} has completed your visit notes.
       Your summary is ready to read.</p>
    {_appointment_details_html(appointment)}
    <p>Log in and go to <strong>My Appointments</strong>
       to view your summary.</p>
    """
    return _log_and_send(
        to_email=appointment.patient.email,
        notification_type="visit_summary_ready",
        subject="Your visit summary is ready — HealthConnect",
        html_body=_base_template("Visit Summary Ready", body),
        appointment_id=appointment.id,
    )


# ─────────────────────────────────────────────
#  RETRY & PENDING PROCESSORS (used by Phase 9)
# ─────────────────────────────────────────────

def retry_failed_notifications(max_retries=3):
    """Scans for failed emails and retries them (up to max_retries times)."""
    from app.models import NotificationLog, Appointment

    failed = NotificationLog.query.filter(
        NotificationLog.status == "failed",
        NotificationLog.retry_count < max_retries,
    ).all()

    retried = 0
    for log in failed:
        if not log.related_appointment_id:
            continue

        appointment = db.session.get(Appointment, log.related_appointment_id)
        if not appointment:
            continue

        if log.notification_type == "booking_confirmation":
            subject = "Your appointment is confirmed — HealthConnect"
            body = _base_template(
                "Appointment Confirmed",
                f"<p>Hi {appointment.patient.name}, your appointment is confirmed.</p>"
                f"{_appointment_details_html(appointment)}"
            )
        elif log.notification_type in ("cancellation", "leave_cancellation"):
            subject = "Your appointment has been cancelled — HealthConnect"
            body = _base_template(
                "Appointment Cancelled",
                f"<p>Hi {appointment.patient.name}, your appointment was cancelled.</p>"
                f"{_appointment_details_html(appointment)}"
            )
        elif log.notification_type == "reminder":
            subject = "Appointment reminder — HealthConnect"
            body = _base_template(
                "Appointment Reminder",
                f"<p>Hi {appointment.patient.name}, reminder for your appointment tomorrow.</p>"
                f"{_appointment_details_html(appointment)}"
            )
        else:
            continue

        _log_and_send(
            to_email=log.recipient_email,
            notification_type=log.notification_type,
            subject=subject,
            html_body=body,
            appointment_id=log.related_appointment_id,
            existing_log_id=log.id,
        )
        retried += 1

    logger.info(f"Email retry job: processed {retried} failed notification(s).")
    return retried


def process_pending_leave_cancellations():
    """Sends queued leave_cancellation notifications created by Phase 3."""
    from app.models import NotificationLog, Appointment

    pending = NotificationLog.query.filter_by(
        notification_type="leave_cancellation",
        status="pending",
    ).all()

    sent = 0
    for log in pending:
        appointment = db.session.get(Appointment, log.related_appointment_id)
        if not appointment:
            continue

        body = _base_template(
            "Appointment Cancelled — Doctor Unavailable",
            f"""
            <p>Hi {appointment.patient.name},</p>
            <p>Your appointment was <strong>cancelled</strong> because
               Dr. {appointment.doctor.user.name} is unavailable on
               that date.</p>
            {_appointment_details_html(appointment)}
            <p>Please log in to book a new slot. We apologise for
               any inconvenience.</p>
            """
        )
        _log_and_send(
            to_email=log.recipient_email,
            notification_type="leave_cancellation",
            subject="Your appointment has been cancelled — HealthConnect",
            html_body=body,
            appointment_id=log.related_appointment_id,
            existing_log_id=log.id,
        )
        sent += 1

    logger.info(f"Leave cancellation processor: sent {sent} notification(s).")
    return sent
