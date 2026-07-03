"""
Phase 9 tests — Background jobs and reminder logic.

Split into two sections:
  A) Pure logic tests (no DB, no Flask, instant) — prescription parsing
  B) Integration tests (with DB + mocked email) — full reminder jobs
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from datetime import date, time, timedelta, datetime
from unittest.mock import patch, MagicMock

# ════════════════════════════════════════════
#  SECTION A: Pure prescription parsing logic
#  (no database, no Flask needed)
# ════════════════════════════════════════════

from app.services.reminder_service import (
    parse_frequency,
    parse_duration_days,
    should_send_medication_reminder_now,
    REMINDER_TIMES,
)

# ── parse_frequency tests ─────────────────────────────────────────────────────

assert parse_frequency("Paracetamol 500mg, twice daily, after meals") == 2
assert parse_frequency("Amoxicillin 250mg, 3x daily, for 7 days") == 3
assert parse_frequency("Vitamin C, once daily") == 1
assert parse_frequency("Ibuprofen, two times a day") == 2
assert parse_frequency("TID dosing") == 3
assert parse_frequency("BD administration") == 2
assert parse_frequency("OD - take at night") == 1
assert parse_frequency("Apply topically as needed") is None
assert parse_frequency(None) is None
assert parse_frequency("") is None
print("TEST 1 PASSED: parse_frequency handles all common prescription patterns correctly.")

# ── parse_duration_days tests ────────────────────────────────────────────────

assert parse_duration_days("for 5 days") == 5
assert parse_duration_days("7-day course") == 7
assert parse_duration_days("for 2 weeks") == 14
assert parse_duration_days("Paracetamol, twice daily, for 10 days") == 10
assert parse_duration_days("for five days") == 5
assert parse_duration_days("take as needed") is None
assert parse_duration_days(None) is None
print("TEST 2 PASSED: parse_duration_days extracts durations correctly.")

# ── should_send_medication_reminder_now tests ────────────────────────────────

visit = date.today() - timedelta(days=2)  # visited 2 days ago

# Frequency 2x/day sends at hours [8, 20]
# At 8 AM, 2 days after visit, within 5-day course → should send
with patch('app.services.reminder_service.datetime') as mock_dt:
    mock_dt.now.return_value = datetime(date.today().year, date.today().month, date.today().day, 8, 0)
    mock_dt.utcnow.return_value = datetime.utcnow()
    result = should_send_medication_reminder_now(visit, 2, 5)
    assert result is True
print("TEST 3 PASSED: Reminder correctly fires at 8 AM for twice-daily prescription.")

# At 3 PM (not in [8, 20]) → should NOT send
with patch('app.services.reminder_service.datetime') as mock_dt:
    mock_dt.now.return_value = datetime(date.today().year, date.today().month, date.today().day, 15, 0)
    mock_dt.utcnow.return_value = datetime.utcnow()
    result = should_send_medication_reminder_now(visit, 2, 5)
    assert result is False
print("TEST 4 PASSED: Reminder does NOT fire at 3 PM for twice-daily prescription.")

# Course is over (visited 10 days ago, 5-day course) → should NOT send
old_visit = date.today() - timedelta(days=10)
with patch('app.services.reminder_service.datetime') as mock_dt:
    mock_dt.now.return_value = datetime(date.today().year, date.today().month, date.today().day, 8, 0)
    mock_dt.utcnow.return_value = datetime.utcnow()
    result = should_send_medication_reminder_now(old_visit, 2, 5)
    assert result is False
print("TEST 5 PASSED: Reminder does NOT fire after the prescription course has ended.")

# No duration specified (ongoing medication) → should send
with patch('app.services.reminder_service.datetime') as mock_dt:
    mock_dt.now.return_value = datetime(date.today().year, date.today().month, date.today().day, 8, 0)
    mock_dt.utcnow.return_value = datetime.utcnow()
    result = should_send_medication_reminder_now(visit, 1, None)
    assert result is True
print("TEST 6 PASSED: Reminder fires for ongoing medication with no duration specified.")

# Visit is today → skip (patient just got home, too soon)
with patch('app.services.reminder_service.datetime') as mock_dt:
    mock_dt.now.return_value = datetime(date.today().year, date.today().month, date.today().day, 8, 0)
    mock_dt.utcnow.return_value = datetime.utcnow()
    result = should_send_medication_reminder_now(date.today(), 2, 5)
    assert result is False
print("TEST 7 PASSED: No medication reminder sent on the day of the visit itself.")


# ════════════════════════════════════════════
#  SECTION B: Integration tests (with Flask + DB)
# ════════════════════════════════════════════

from app import create_app
from app.models import db, User, DoctorProfile, Appointment, VisitNote, SymptomForm, NotificationLog

app = create_app()
app.config['WTF_CSRF_ENABLED'] = False


def _seed():
    with app.app_context():
        db.drop_all()
        db.create_all()

        doc_user = User(name='Mehta', email='mehta@test.com', role='doctor')
        doc_user.set_password('pass')
        patient = User(name='Riya', email='riya@test.com', role='patient')
        patient.set_password('pass')
        db.session.add_all([doc_user, patient])
        db.session.commit()

        doc = DoctorProfile(
            user_id=doc_user.id, specialization='Cardiology',
            working_start=time(9, 0), working_end=time(17, 0),
            slot_duration_minutes=30
        )
        db.session.add(doc)
        db.session.commit()
        return doc.id, patient.id


# ── Test 8: appointment reminder job ─────────────────────────────────────────

doc_id, patient_id = _seed()

with app.app_context():
    # Appointment scheduled for TOMORROW
    tomorrow_appt = Appointment(
        patient_id=patient_id, doctor_id=doc_id,
        appointment_date=date.today() + timedelta(days=1),
        start_time=time(10, 0), end_time=time(10, 30),
        status='booked',
        hold_expires_at=datetime.utcnow() + timedelta(hours=1)
    )
    # Appointment scheduled for next week (should NOT get a reminder today)
    next_week_appt = Appointment(
        patient_id=patient_id, doctor_id=doc_id,
        appointment_date=date.today() + timedelta(days=7),
        start_time=time(11, 0), end_time=time(11, 30),
        status='booked',
        hold_expires_at=datetime.utcnow() + timedelta(hours=1)
    )
    db.session.add_all([tomorrow_appt, next_week_appt])
    db.session.commit()
    tomorrow_id = tomorrow_appt.id
    next_week_id = next_week_appt.id

with patch('app.services.email_service._actually_send', return_value=(True, None)):
    from app.services.reminder_service import send_appointment_reminders
    count = send_appointment_reminders(app)
    assert count == 1  # only the tomorrow appointment

with app.app_context():
    # Confirm a reminder notification was logged for the right appointment
    reminder_log = NotificationLog.query.filter_by(
        related_appointment_id=tomorrow_id,
        notification_type='reminder',
        status='sent'
    ).first()
    assert reminder_log is not None

    # And NOT for next week's appointment
    no_log = NotificationLog.query.filter_by(
        related_appointment_id=next_week_id,
        notification_type='reminder'
    ).first()
    assert no_log is None

print("TEST 8 PASSED: Reminder job sends exactly 1 email for tomorrow's appointment, not next week's.")


# ── Test 9: no duplicate reminders ────────────────────────────────────────────

with patch('app.services.email_service._actually_send', return_value=(True, None)):
    count_second_run = send_appointment_reminders(app)
    assert count_second_run == 0  # already sent, should skip

print("TEST 9 PASSED: Running the reminder job twice does NOT send duplicate emails.")


# ── Test 10: medication reminder job ─────────────────────────────────────────

doc_id, patient_id = _seed()

with app.app_context():
    completed_appt = Appointment(
        patient_id=patient_id, doctor_id=doc_id,
        appointment_date=date.today() - timedelta(days=1),
        start_time=time(9, 0), end_time=time(9, 30),
        status='completed',
        hold_expires_at=datetime.utcnow() - timedelta(hours=5)
    )
    db.session.add(completed_appt)
    db.session.commit()

    vn = VisitNote(
        appointment_id=completed_appt.id,
        clinical_notes="Patient has mild fever.",
        prescription="Paracetamol 500mg, twice daily, after meals, for 5 days"
    )
    db.session.add(vn)
    db.session.commit()
    med_appt_id = completed_appt.id

# Mock current hour to 8 AM (one of the twice-daily reminder hours)
with patch('app.services.reminder_service.datetime') as mock_dt:
    mock_dt.now.return_value = datetime(
        date.today().year, date.today().month, date.today().day, 8, 0
    )
    mock_dt.utcnow.return_value = datetime.utcnow() - timedelta(hours=2)

    with patch('app.services.email_service._actually_send', return_value=(True, None)):
        from app.services.reminder_service import send_medication_reminders
        count = send_medication_reminders(app)
        assert count == 1

with app.app_context():
    med_log = NotificationLog.query.filter_by(
        related_appointment_id=med_appt_id,
        notification_type='medication_reminder',
        status='sent'
    ).first()
    assert med_log is not None

print("TEST 10 PASSED: Medication reminder sent at 8 AM for twice-daily prescription.")


# ── Test 11: expired prescription course → no reminder ───────────────────────

doc_id, patient_id = _seed()

with app.app_context():
    old_appt = Appointment(
        patient_id=patient_id, doctor_id=doc_id,
        appointment_date=date.today() - timedelta(days=10),
        start_time=time(9, 0), end_time=time(9, 30),
        status='completed',
        hold_expires_at=datetime.utcnow() - timedelta(hours=100)
    )
    db.session.add(old_appt)
    db.session.commit()

    vn2 = VisitNote(
        appointment_id=old_appt.id,
        clinical_notes="Routine checkup.",
        prescription="Ibuprofen 400mg, twice daily, for 5 days"  # 5 day course, 10 days ago = expired
    )
    db.session.add(vn2)
    db.session.commit()

with patch('app.services.reminder_service.datetime') as mock_dt:
    mock_dt.now.return_value = datetime(
        date.today().year, date.today().month, date.today().day, 8, 0
    )
    mock_dt.utcnow.return_value = datetime.utcnow()

    with patch('app.services.email_service._actually_send', return_value=(True, None)) as mock_send:
        count = send_medication_reminders(app)
        # Should be 0 since the prescription course expired 5 days ago
        assert count == 0

print("TEST 11 PASSED: No medication reminder sent for an expired prescription course.")


# ── Test 12: scheduler starts correctly ──────────────────────────────────────

# Simulate production environment (no Werkzeug reloader)
with patch.dict(os.environ, {'WERKZEUG_RUN_MAIN': 'true'}):
    test_app = create_app()
    test_app.debug = False

    from app.services.scheduler import get_scheduler_status
    with test_app.app_context():
        status = get_scheduler_status()
        # In test environment the scheduler starts; verify it reports correctly
        assert isinstance(status, dict)
        assert 'running' in status
        assert 'jobs' in status

print("TEST 12 PASSED: Scheduler status endpoint returns correct structure.")

print("\nAll Phase 9 tests passed.")
