"""
Phase 8 tests — Google Calendar integration.

All Google API calls are mocked. This is correct practice:
- Real Google API calls need network + real credentials
- We test OUR logic: correct event structure, correct IDs stored,
  graceful failure when calendar isn't connected
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from datetime import date, time, timedelta, datetime
from unittest.mock import patch, MagicMock

from app import create_app
from app.models import db, User, DoctorProfile, Appointment, SymptomForm, GoogleOAuthToken

app = create_app()
app.config['WTF_CSRF_ENABLED'] = False
app.config['GOOGLE_CLIENT_ID'] = 'fake-client-id'
app.config['GOOGLE_CLIENT_SECRET'] = 'fake-client-secret'


def _seed_db():
    """Seed a basic DB with one doctor, one patient, one booked appointment."""
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
            working_start=time(9,0), working_end=time(17,0),
            slot_duration_minutes=30
        )
        db.session.add(doc)
        db.session.commit()

        appt = Appointment(
            patient_id=patient.id, doctor_id=doc.id,
            appointment_date=date.today() + timedelta(days=3),
            start_time=time(10,0), end_time=time(10,30),
            status='booked',
            hold_expires_at=datetime.utcnow() + timedelta(hours=1)
        )
        db.session.add(appt)
        db.session.commit()
        return appt.id


# TEST 1: No calendar connected -> create_calendar_event returns None gracefully
_seed_db()
with app.app_context():
    from app.services.calendar_service import create_calendar_event, is_calendar_connected
    appt = db.session.get(Appointment, 1)
    result = create_calendar_event(appt)
    assert result is None
    assert is_calendar_connected() is False
print('TEST 1 PASSED: No calendar connected -> returns None gracefully, no crash.')


# TEST 2: Token storage and retrieval
_seed_db()
with app.app_context():
    from app.services.calendar_service import _store_tokens, is_calendar_connected
    _store_tokens(
        refresh_token='fake-refresh-token',
        access_token='fake-access-token',
        expiry=datetime.utcnow() + timedelta(hours=1)
    )
    assert is_calendar_connected() is True
    token = db.session.get(GoogleOAuthToken, 1)
    assert token.refresh_token == 'fake-refresh-token'
print('TEST 2 PASSED: OAuth tokens stored and retrieved correctly from DB.')


# TEST 3: Calling store_tokens again UPDATES the existing row (no duplicates)
with app.app_context():
    from app.services.calendar_service import _store_tokens
    _store_tokens(refresh_token='new-refresh-token', access_token='new-access-token')
    count = GoogleOAuthToken.query.count()
    assert count == 1   # still only one row
    token = db.session.get(GoogleOAuthToken, 1)
    assert token.refresh_token == 'new-refresh-token'
print('TEST 3 PASSED: Re-storing tokens updates the existing row, no duplicates created.')


# TEST 4: create_calendar_event calls the Google API and stores the event ID
_seed_db()
with app.app_context():
    from app.services.calendar_service import _store_tokens, create_calendar_event

    _store_tokens(
        refresh_token='fake-refresh',
        access_token='fake-access',
        expiry=datetime.utcnow() + timedelta(hours=1)
    )

    # Mock the entire Google API call chain
    mock_service = MagicMock()
    mock_service.events().insert().execute.return_value = {"id": "google_event_abc123"}

    with patch('app.services.calendar_service._build_service', return_value=mock_service):
        appt = db.session.get(Appointment, 1)
        event_id = create_calendar_event(appt)

        assert event_id == "google_event_abc123"
        # Verify the correct parameters were passed to Google's API
        insert_call = mock_service.events().insert.call_args
        assert insert_call.kwargs['calendarId'] == 'primary'
        assert insert_call.kwargs['sendUpdates'] == 'all'
        body = insert_call.kwargs['body']
        assert 'Riya' in body['summary']
        assert 'Mehta' in body['summary']
        # Both patient and doctor must be in attendees
        attendee_emails = [a['email'] for a in body['attendees']]
        assert 'riya@test.com' in attendee_emails
        assert 'mehta@test.com' in attendee_emails

print('TEST 4 PASSED: Calendar event created with correct attendees, event ID returned.')


# TEST 5: delete_calendar_event calls Google delete with the right event ID
_seed_db()
with app.app_context():
    from app.services.calendar_service import _store_tokens, delete_calendar_event

    _store_tokens(refresh_token='fake', access_token='fake',
                  expiry=datetime.utcnow() + timedelta(hours=1))

    appt = db.session.get(Appointment, 1)
    appt.google_calendar_event_id = "event_to_delete_xyz"
    db.session.commit()

    mock_service = MagicMock()
    mock_service.events().delete().execute.return_value = {}

    with patch('app.services.calendar_service._build_service', return_value=mock_service):
        result = delete_calendar_event(appt)
        assert result is True
        delete_call = mock_service.events().delete.call_args
        assert delete_call.kwargs['eventId'] == 'event_to_delete_xyz'
        assert delete_call.kwargs['sendUpdates'] == 'all'

print('TEST 5 PASSED: Calendar event deleted with correct event ID and attendee notification.')


# TEST 6: delete_calendar_event with no event ID stored -> skips gracefully
_seed_db()
with app.app_context():
    from app.services.calendar_service import _store_tokens, delete_calendar_event

    _store_tokens(refresh_token='fake', access_token='fake',
                  expiry=datetime.utcnow() + timedelta(hours=1))

    appt = db.session.get(Appointment, 1)
    # google_calendar_event_id is None (never created)
    assert appt.google_calendar_event_id is None

    mock_service = MagicMock()
    with patch('app.services.calendar_service._build_service', return_value=mock_service):
        result = delete_calendar_event(appt)
        assert result is False
        mock_service.events().delete.assert_not_called()

print('TEST 6 PASSED: delete with no stored event ID skips gracefully, no API call made.')


# TEST 7: Google API failure on create -> returns None, no crash
_seed_db()
with app.app_context():
    from app.services.calendar_service import _store_tokens, create_calendar_event

    _store_tokens(refresh_token='fake', access_token='fake',
                  expiry=datetime.utcnow() + timedelta(hours=1))

    mock_service = MagicMock()
    mock_service.events().insert().execute.side_effect = Exception("Google API 503")

    with patch('app.services.calendar_service._build_service', return_value=mock_service):
        appt = db.session.get(Appointment, 1)
        result = create_calendar_event(appt)
        assert result is None  # graceful None, not an exception

print('TEST 7 PASSED: Google API error during create returns None gracefully, no crash.')


# TEST 8: update_calendar_event patches the existing event
_seed_db()
with app.app_context():
    from app.services.calendar_service import _store_tokens, update_calendar_event

    _store_tokens(refresh_token='fake', access_token='fake',
                  expiry=datetime.utcnow() + timedelta(hours=1))

    appt = db.session.get(Appointment, 1)
    appt.google_calendar_event_id = "existing_event_id"
    db.session.commit()

    mock_service = MagicMock()
    mock_service.events().update().execute.return_value = {"id": "existing_event_id"}

    with patch('app.services.calendar_service._build_service', return_value=mock_service):
        result = update_calendar_event(appt)
        assert result is True
        update_call = mock_service.events().update.call_args
        assert update_call.kwargs['eventId'] == 'existing_event_id'

print('TEST 8 PASSED: Calendar event updated correctly using the stored event ID.')

print('\nAll Phase 8 tests passed.')
