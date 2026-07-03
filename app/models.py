from datetime import datetime
import json
from flask_sqlalchemy import SQLAlchemy
from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash
from sqlalchemy import Index, text

# db is the object that connects our Python classes to the actual database.
# We create it here, and "attach" it to our Flask app in __init__.py
db = SQLAlchemy()


class User(UserMixin, db.Model):
    """
    ONE table for patients, doctors, AND admins.
    Why one table instead of three? Because login/auth logic
    (email, password, "who is this") is identical for all three roles.
    The 'role' column is what tells us which type of user this is.
    This is a standard pattern called 'Single Table Inheritance'.
    """
    __tablename__ = "users"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False, index=True)

    # We NEVER store the actual password. We store a one-way scrambled
    # version (a "hash"). Even if our database leaks, passwords stay safe.
    password_hash = db.Column(db.String(255), nullable=False)

    # role is restricted to one of these 3 values only
    role = db.Column(db.String(20), nullable=False)  # 'patient' | 'doctor' | 'admin'

    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    # --- relationships: lets us write "user.doctor_profile" in Python
    # instead of writing manual SQL joins every time ---
    doctor_profile = db.relationship(
        "DoctorProfile", backref="user", uselist=False, cascade="all, delete-orphan"
    )

    def set_password(self, raw_password):
        """Turns a plain password into a secure hash before saving."""
        self.password_hash = generate_password_hash(raw_password)

    def check_password(self, raw_password):
        """Checks a login attempt's password against the stored hash."""
        return check_password_hash(self.password_hash, raw_password)

    def __repr__(self):
        return f"<User {self.email} ({self.role})>"


class DoctorProfile(db.Model):
    """
    Extra info that ONLY doctors have. Kept separate from User
    so the 'users' table stays clean and simple for all roles.
    """
    __tablename__ = "doctor_profiles"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), unique=True, nullable=False)

    specialization = db.Column(db.String(120), nullable=False)

    # Working hours stored as simple time values, e.g. 09:00 to 17:00
    working_start = db.Column(db.Time, nullable=False)
    working_end = db.Column(db.Time, nullable=False)

    # How long each appointment slot is, in minutes (e.g. 15, 30)
    slot_duration_minutes = db.Column(db.Integer, nullable=False, default=30)

    leaves = db.relationship("DoctorLeave", backref="doctor", cascade="all, delete-orphan")
    appointments = db.relationship("Appointment", backref="doctor", cascade="all, delete-orphan")

    def __repr__(self):
        return f"<DoctorProfile {self.specialization}>"


class DoctorLeave(db.Model):
    """
    A single date a doctor is unavailable.
    When admin adds a leave, our app logic (Phase 3) will check this
    table for existing bookings on that date and notify affected patients.
    """
    __tablename__ = "doctor_leaves"

    id = db.Column(db.Integer, primary_key=True)
    doctor_id = db.Column(db.Integer, db.ForeignKey("doctor_profiles.id"), nullable=False)
    leave_date = db.Column(db.Date, nullable=False)
    reason = db.Column(db.String(255))

    __table_args__ = (
        # A doctor can't have the same leave date added twice
        db.UniqueConstraint("doctor_id", "leave_date", name="uq_doctor_leave_date"),
    )


class Appointment(db.Model):
    """
    THE CORE TABLE of this entire project.

    *** HOW WE PREVENT DOUBLE-BOOKING (the hardest requirement) ***
    Two patients could click "Book" on the exact same slot at the exact
    same millisecond. If we only check "is this slot free?" in Python
    code first, BOTH requests can pass that check before either one saves
    -- this is called a 'race condition' and is a classic real-world bug.

    The fix: a UNIQUE INDEX at the database level, on
    (doctor_id, appointment_date, start_time), but ONLY for appointments
    that are still 'booked' or 'completed' (not 'cancelled').
    The database itself will REJECT the second booking attempt outright,
    even under simultaneous requests -- this is something application
    code alone cannot guarantee, but the database engine can.

    We exclude 'cancelled' appointments from the rule on purpose:
    if a patient cancels, that slot must become bookable again by
    someone else.
    """
    __tablename__ = "appointments"

    id = db.Column(db.Integer, primary_key=True)
    patient_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    doctor_id = db.Column(db.Integer, db.ForeignKey("doctor_profiles.id"), nullable=False)

    # Lets us write "appointment.patient.name" instead of a manual query.
    # We don't need a similar relationship for the doctor's User record
    # because we already reach it via appointment.doctor.user.name
    # (doctor -> DoctorProfile -> user, set up in Phase 1/3).
    patient = db.relationship("User", foreign_keys=[patient_id])

    appointment_date = db.Column(db.Date, nullable=False)
    start_time = db.Column(db.Time, nullable=False)
    end_time = db.Column(db.Time, nullable=False)

    # 'held' = patient is filling the symptom form (temporary lock, Phase 4)
    # 'booked' = confirmed
    # 'completed' = visit happened
    # 'cancelled' = freed up, slot can be rebooked
    status = db.Column(db.String(20), nullable=False, default="held")

    # If status='held', this tells us when the temporary hold expires.
    hold_expires_at = db.Column(db.DateTime, nullable=True)

    # Stored when we create a Google Calendar event so we can
    # UPDATE it on reschedule or DELETE it on cancellation.
    # Null means either calendar isn't connected, or event creation failed.
    google_calendar_event_id = db.Column(db.String(255), nullable=True)

    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    symptom_form = db.relationship(
        "SymptomForm", backref="appointment", uselist=False, cascade="all, delete-orphan"
    )
    visit_note = db.relationship(
        "VisitNote", backref="appointment", uselist=False, cascade="all, delete-orphan"
    )

    __table_args__ = (
        Index(
            "uq_active_doctor_slot",
            "doctor_id", "appointment_date", "start_time",
            unique=True,
            # This WHERE clause is what makes it a "partial" unique index --
            # the rule only applies to rows where status is not 'cancelled'.
            postgresql_where=text("status != 'cancelled'"),
            sqlite_where=text("status != 'cancelled'"),
        ),
    )

    def __repr__(self):
        return f"<Appointment {self.appointment_date} {self.start_time} status={self.status}>"


class SymptomForm(db.Model):
    """
    Patient fills this BEFORE the visit. Gemini AI reads the symptoms
    and generates a structured summary for the doctor (Phase 5).
    """
    __tablename__ = "symptom_forms"

    id = db.Column(db.Integer, primary_key=True)
    appointment_id = db.Column(db.Integer, db.ForeignKey("appointments.id"), unique=True, nullable=False)

    symptoms_text = db.Column(db.Text, nullable=False)

    # --- AI-generated fields, filled in by Phase 5 ---
    ai_urgency_level = db.Column(db.String(10))  # 'Low' | 'Medium' | 'High'
    ai_chief_complaint = db.Column(db.Text)
    ai_suggested_questions = db.Column(db.Text)  # stored as JSON string

    # If Gemini fails (Phase 5 requirement: "must not break the system"),
    # we record that here instead of crashing, and the doctor sees
    # "AI summary unavailable" instead of an error page.
    ai_summary_failed = db.Column(db.Boolean, default=False)

    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    @property
    def ai_suggested_questions_list(self):
        """
        ai_suggested_questions is stored as a JSON string in the DB
        (since SQL columns can't hold Python lists directly). Templates
        shouldn't need to know that -- this property hands back a clean
        Python list, or an empty list if nothing was stored.
        """
        if not self.ai_suggested_questions:
            return []
        try:
            return json.loads(self.ai_suggested_questions)
        except (json.JSONDecodeError, TypeError):
            return []


class VisitNote(db.Model):
    """
    Doctor fills this AFTER the visit. Gemini turns clinical notes into
    a patient-friendly summary with medication schedule (Phase 6).
    """
    __tablename__ = "visit_notes"

    id = db.Column(db.Integer, primary_key=True)
    appointment_id = db.Column(db.Integer, db.ForeignKey("appointments.id"), unique=True, nullable=False)

    clinical_notes = db.Column(db.Text, nullable=False)
    prescription = db.Column(db.Text)  # e.g. "Paracetamol 500mg, 3x/day, 5 days"

    ai_patient_summary = db.Column(db.Text)
    ai_summary_failed = db.Column(db.Boolean, default=False)

    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class NotificationLog(db.Model):
    """
    Records EVERY attempt to send an email -- this is how we satisfy
    the 'notification failure handling' requirement professionally.
    Instead of an email silently failing and nobody knowing, every
    attempt is logged with a status. A background job (Phase 9) scans
    for 'failed' rows and retries them automatically.
    """
    __tablename__ = "notifications_log"

    id = db.Column(db.Integer, primary_key=True)
    recipient_email = db.Column(db.String(120), nullable=False)
    notification_type = db.Column(db.String(50), nullable=False)
    # e.g. 'booking_confirmation' | 'reminder' | 'cancellation' | 'medication_reminder'

    related_appointment_id = db.Column(db.Integer, db.ForeignKey("appointments.id"), nullable=True)

    status = db.Column(db.String(20), nullable=False, default="pending")
    # 'pending' | 'sent' | 'failed' | 'retrying'

    retry_count = db.Column(db.Integer, default=0)
    error_message = db.Column(db.Text, nullable=True)

    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    sent_at = db.Column(db.DateTime, nullable=True)


class GoogleOAuthToken(db.Model):
    """
    Stores the clinic's Google OAuth tokens so calendar operations
    survive server restarts.

    WHY store in DB instead of a file?
    Files get wiped on Render's free tier between deploys. A DB row
    persists forever. Also, a DB row can be updated atomically when
    tokens are refreshed -- no race conditions possible with file writes.

    There will only ever be ONE row in this table (the clinic's token).
    We use id=1 as a fixed key.
    """
    __tablename__ = "google_oauth_tokens"

    id = db.Column(db.Integer, primary_key=True)
    # The refresh token is the important one -- it never expires
    # (unless the user revokes access in their Google account settings)
    refresh_token = db.Column(db.Text, nullable=False)
    # Access tokens expire in 1 hour; we store the last one to avoid
    # unnecessary refresh calls
    access_token = db.Column(db.Text, nullable=True)
    token_expiry = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
