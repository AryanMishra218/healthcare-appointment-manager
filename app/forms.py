from flask_wtf import FlaskForm
from wtforms import StringField, PasswordField, SubmitField, TimeField, DateField, IntegerField, TextAreaField, HiddenField
from wtforms.validators import DataRequired, Email, Length, EqualTo, NumberRange


class RegisterForm(FlaskForm):
    """
    Public registration form. ONLY for patients -- notice there is no
    'role' field here at all. The role is hardcoded to 'patient' in the
    route itself, so a user can never trick this form into making
    themselves a doctor or admin.
    """
    name = StringField("Full Name", validators=[DataRequired(), Length(min=2, max=120)])
    email = StringField("Email", validators=[DataRequired(), Email()])
    password = PasswordField("Password", validators=[DataRequired(), Length(min=8)])
    confirm_password = PasswordField(
        "Confirm Password",
        validators=[DataRequired(), EqualTo("password", message="Passwords must match.")]
    )
    submit = SubmitField("Register")


class LoginForm(FlaskForm):
    """Used by ALL roles (patient, doctor, admin) -- same login page for everyone."""
    email = StringField("Email", validators=[DataRequired(), Email()])
    password = PasswordField("Password", validators=[DataRequired()])
    submit = SubmitField("Log In")

class ChangePasswordForm(FlaskForm):
    """Used by a doctor to replace their admin-issued temporary password."""
    current_password = PasswordField("Current Password", validators=[DataRequired()])
    new_password = PasswordField("New Password", validators=[DataRequired(), Length(min=8)])
    confirm_new_password = PasswordField(
        "Confirm New Password",
        validators=[DataRequired(), EqualTo("new_password", message="Passwords must match.")]
    )
    submit = SubmitField("Update Password")


class CreateDoctorForm(FlaskForm):
    """
    Admin-only form. Creates BOTH a User (login=role doctor) AND a
    DoctorProfile (specialization, hours) in one step -- the admin
    shouldn't have to do this as two separate actions.
    """
    name = StringField("Doctor's Full Name", validators=[DataRequired(), Length(min=2, max=120)])
    email = StringField("Email", validators=[DataRequired(), Email()])
    specialization = StringField("Specialization", validators=[DataRequired(), Length(min=2, max=120)])
    working_start = TimeField("Working Hours Start", validators=[DataRequired()])
    working_end = TimeField("Working Hours End", validators=[DataRequired()])
    slot_duration_minutes = IntegerField(
        "Slot Duration (minutes)",
        validators=[DataRequired(), NumberRange(min=5, max=120)],
        default=30
    )
    submit = SubmitField("Create Doctor Profile")

class EditDoctorForm(FlaskForm):
    """
    Admin-only form to update an existing doctor's login email and
    clinical profile (specialization, hours, slot length). Password
    is never touched here -- that's handled separately by the doctor
    themselves via 'Change Password'.
    """
    email = StringField("Email", validators=[DataRequired(), Email()])
    specialization = StringField("Specialization", validators=[DataRequired(), Length(min=2, max=120)])
    working_start = TimeField("Working Hours Start", validators=[DataRequired()])
    working_end = TimeField("Working Hours End", validators=[DataRequired()])
    slot_duration_minutes = IntegerField(
        "Slot Duration (minutes)",
        validators=[DataRequired(), NumberRange(min=5, max=120)]
    )
    submit = SubmitField("Save Changes")

class AddLeaveForm(FlaskForm):
    """Admin marks a specific doctor unavailable on a specific date."""
    leave_date = DateField("Leave Date", validators=[DataRequired()])
    reason = TextAreaField("Reason (optional)", validators=[Length(max=255)])
    submit = SubmitField("Add Leave Day")


class DateSelectForm(FlaskForm):
    """Patient picks a date to view a doctor's available slots."""
    appointment_date = DateField("Choose a date", validators=[DataRequired()])
    submit = SubmitField("View Slots")


class HoldSlotForm(FlaskForm):
    """
    One of these is rendered per visible slot button. The date/time are
    hidden fields -- the patient never types them, they just click a
    slot, but we still get CSRF protection on the action.
    """
    appointment_date = HiddenField(validators=[DataRequired()])
    start_time = HiddenField(validators=[DataRequired()])


class ConfirmBookingForm(FlaskForm):
    """Just a CSRF-protected submit button -- all real data is already
    saved on the 'held' appointment by the time this form is shown."""
    submit = SubmitField("Confirm Appointment")


class CancelAppointmentForm(FlaskForm):
    submit = SubmitField("Cancel Appointment")


class SymptomReportForm(FlaskForm):
    """Patient fills this in before their appointment is confirmed."""
    symptoms_text = TextAreaField(
        "Describe your symptoms",
        validators=[DataRequired(), Length(min=10, max=2000, message="Please provide at least a few words about how you're feeling.")]
    )
    submit = SubmitField("Submit Symptoms")


class VisitNoteForm(FlaskForm):
    """Doctor fills this in after seeing the patient."""
    clinical_notes = TextAreaField(
        "Clinical Notes", validators=[DataRequired(), Length(min=5, max=3000)]
    )
    prescription = TextAreaField(
        "Prescription (medication, dosage, frequency, duration)",
        validators=[Length(max=1000)]
    )
    submit = SubmitField("Complete Visit & Generate Summary")
