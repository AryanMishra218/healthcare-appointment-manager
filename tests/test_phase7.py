"""
Phase 7 tests — Email notification system.

All SendGrid calls are mocked. This is correct test practice:
- We test OUR logic (correct email type, correct recipient, retry logic)
- We do NOT test SendGrid itself (that's their job, not ours)
- Tests work without a real API key and run instantly
"""
from datetime import date, time, timedelta, datetime
from unittest.mock import patch, MagicMock

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from app import create_app
from app.models import db, User, DoctorProfile, Appointment, SymptomForm, NotificationLog

app = create_app()
app.config['WTF_CSRF_ENABLED'] = False

# ── helpers ──────────────────────────────────────────────────────────────────

def make_booked_appointment(app):
    """Creates a complete booked appointment in the DB and returns it."""
    with app.app_context():
        db.drop_all()
        db.create_all()

        admin = User(name='Admin', email='admin@test.com', role='admin')
        admin.set_password('adminpass')
        patient = User(name='Riya Shah', email='riya@test.com', role='patient')
        patient.set_password('pass1234')
        doc_user = User(name='Mehta', email='mehta@test.com', role='doctor')
        doc_user.set_password('pass1234')
        db.session.add_all([admin, patient, doc_user])
        db.session.commit()

        doc = DoctorProfile(
            user_id=doc_user.id, specialization='Cardiology',
            working_start=time(9, 0), working_end=time(17, 0),
            slot_duration_minutes=30
        )
        db.session.add(doc)
        db.session.commit()

        appt = Appointment(
            patient_id=patient.id, doctor_id=doc.id,
            appointment_date=date.today() + timedelta(days=3),
            start_time=time(10, 0), end_time=time(10, 30),
            status='booked',
            hold_expires_at=datetime.utcnow() + timedelta(minutes=5)
        )
        db.session.add(appt)
        db.session.commit()

        sf = SymptomForm(appointment_id=appt.id, symptoms_text='Chest pain')
        db.session.add(sf)
        db.session.commit()

        return appt.id, patient.id, doc_user.id


# ── Test 1: booking confirmation emails ──────────────────────────────────────

appt_id, patient_id, doc_user_id = make_booked_appointment(app)

with app.app_context():
    # Patch _actually_send so no real HTTP call is made
    with patch('app.services.email_service._actually_send', return_value=(True, None)) as mock_send:
        from app.services.email_service import send_booking_confirmation_patient, send_booking_confirmation_doctor
        appt = db.session.get(Appointment, appt_id)

        result_patient = send_booking_confirmation_patient(appt)
        result_doctor  = send_booking_confirmation_doctor(appt)

        assert result_patient is True
        assert result_doctor  is True
        assert mock_send.call_count == 2

        # Verify recipient emails were correct
        calls = mock_send.call_args_list
        recipients = [c[0][0] for c in calls]   # first positional arg = to_email
        assert 'riya@test.com'  in recipients
        assert 'mehta@test.com' in recipients

        # Both emails must be logged in the DB as 'sent'
        logs = NotificationLog.query.filter_by(related_appointment_id=appt_id).all()
        assert len(logs) == 2
        assert all(l.status == 'sent' for l in logs)

print('TEST 1 PASSED: Booking confirmation sent to both patient and doctor; both logged as sent.')


# ── Test 2: SendGrid failure is handled gracefully ───────────────────────────

appt_id2, _, _ = make_booked_appointment(app)

with app.app_context():
    with patch('app.services.email_service._actually_send',
               return_value=(False, 'Connection timeout')) as mock_send:
        from app.services.email_service import send_booking_confirmation_patient
        appt2 = db.session.get(Appointment, appt_id2)
        result = send_booking_confirmation_patient(appt2)

        assert result is False

        # Log row must exist and show the failure correctly
        log = NotificationLog.query.filter_by(
            related_appointment_id=appt_id2,
            notification_type='booking_confirmation'
        ).first()
        assert log is not None
        assert log.status == 'failed'
        assert 'Connection timeout' in log.error_message

print('TEST 2 PASSED: SendGrid failure is logged as "failed" with error message; no crash, no silent loss.')


# ── Test 3: cancellation email ───────────────────────────────────────────────

appt_id3, _, _ = make_booked_appointment(app)

with app.app_context():
    with patch('app.services.email_service._actually_send', return_value=(True, None)):
        from app.services.email_service import send_cancellation_patient
        appt3 = db.session.get(Appointment, appt_id3)
        result = send_cancellation_patient(appt3, reason="Doctor unavailable")
        assert result is True

        log = NotificationLog.query.filter_by(
            related_appointment_id=appt_id3,
            notification_type='cancellation'
        ).first()
        assert log.status == 'sent'

print('TEST 3 PASSED: Cancellation email sent and logged correctly.')


# ── Test 4: leave_cancellation queue is processed ───────────────────────────

appt_id4, _, _ = make_booked_appointment(app)

with app.app_context():
    # Simulate what Phase 3 does: queue a pending leave_cancellation
    queued = NotificationLog(
        recipient_email='riya@test.com',
        notification_type='leave_cancellation',
        related_appointment_id=appt_id4,
        status='pending',
    )
    db.session.add(queued)
    db.session.commit()
    queued_id = queued.id

    with patch('app.services.email_service._actually_send', return_value=(True, None)):
        from app.services.email_service import process_pending_leave_cancellations
        count = process_pending_leave_cancellations()

        assert count == 1
        processed = db.session.get(NotificationLog, queued_id)
        assert processed.status == 'sent'

print('TEST 4 PASSED: Phase-3 queued leave_cancellation was found and sent correctly.')


# ── Test 5: retry logic ──────────────────────────────────────────────────────

appt_id5, _, _ = make_booked_appointment(app)

with app.app_context():
    # Create a failed notification row
    failed_log = NotificationLog(
        recipient_email='riya@test.com',
        notification_type='booking_confirmation',
        related_appointment_id=appt_id5,
        status='failed',
        retry_count=0,
        error_message='Timeout',
    )
    db.session.add(failed_log)
    db.session.commit()
    failed_id = failed_log.id

    # First retry: SendGrid still failing
    with patch('app.services.email_service._actually_send', return_value=(False, 'Still down')):
        from app.services.email_service import retry_failed_notifications
        retry_failed_notifications(max_retries=3)

        log = db.session.get(NotificationLog, failed_id)
        assert log.status == 'failed'
        assert log.retry_count == 1   # incremented

    # Second retry: SendGrid now working
    with patch('app.services.email_service._actually_send', return_value=(True, None)):
        retry_failed_notifications(max_retries=3)

        log = db.session.get(NotificationLog, failed_id)
        assert log.status == 'sent'
        assert log.retry_count == 2
        assert log.sent_at is not None

print('TEST 5 PASSED: Retry logic works — failed emails are retried, success updates status to sent.')


# ── Test 6: max_retries cap ──────────────────────────────────────────────────

appt_id6, _, _ = make_booked_appointment(app)

with app.app_context():
    maxed_log = NotificationLog(
        recipient_email='riya@test.com',
        notification_type='booking_confirmation',
        related_appointment_id=appt_id6,
        status='failed',
        retry_count=3,   # already at limit
        error_message='Permanent failure',
    )
    db.session.add(maxed_log)
    db.session.commit()
    maxed_id = maxed_log.id

    with patch('app.services.email_service._actually_send', return_value=(True, None)) as mock_send:
        from app.services.email_service import retry_failed_notifications
        retry_failed_notifications(max_retries=3)

        # Should NOT have been retried (retry_count >= max_retries)
        log = db.session.get(NotificationLog, maxed_id)
        assert log.status == 'failed'   # unchanged
        assert mock_send.call_count == 0

print('TEST 6 PASSED: Notifications that have hit max_retries are NOT retried again (avoids spam).')


# ── Test 7: no API key = graceful skip, still creates a log row ─────────────

appt_id7, _, _ = make_booked_appointment(app)

with app.app_context():
    app.config['SENDGRID_API_KEY'] = None
    from app.services.email_service import send_booking_confirmation_patient
    appt7 = db.session.get(Appointment, appt_id7)
    result = send_booking_confirmation_patient(appt7)

    # Returns False (not sent) but the app should not crash
    assert result is False

    log = NotificationLog.query.filter_by(
        related_appointment_id=appt_id7,
        notification_type='booking_confirmation'
    ).first()
    assert log is not None
    assert log.status == 'failed'

print('TEST 7 PASSED: No API key configured -> email skipped gracefully, log row still created.')

print('\nAll Phase 7 tests passed.')
