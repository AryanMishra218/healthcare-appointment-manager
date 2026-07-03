import json
from datetime import datetime, date as date_cls, timedelta

from flask import Blueprint, render_template, redirect, url_for, flash, request
from flask_login import current_user
from sqlalchemy.exc import IntegrityError

from app.models import db, DoctorProfile, User, Appointment, SymptomForm
from app.forms import DateSelectForm, HoldSlotForm, ConfirmBookingForm, CancelAppointmentForm, SymptomReportForm
from app.utils import roles_required
from app.services.scheduling import get_available_slots, calculate_end_time, HOLD_DURATION_MINUTES
from app.services import llm_service
from app.services import email_service
from app.services import calendar_service

patient_bp = Blueprint("patient", __name__, url_prefix="/patient")


@patient_bp.route("/doctors")
@roles_required("patient")
def search_doctors():
    """Search/list doctors, optionally filtered by specialization."""
    specialization = request.args.get("specialization", "").strip()

    query = DoctorProfile.query.join(User)
    if specialization:
        query = query.filter(DoctorProfile.specialization.ilike(f"%{specialization}%"))
    doctors = query.order_by(User.name).all()

    # For the filter dropdown: every distinct specialization currently in the system
    all_specializations = sorted({d.specialization for d in DoctorProfile.query.all()})

    return render_template(
        "patient/search_doctors.html",
        doctors=doctors,
        all_specializations=all_specializations,
        current_filter=specialization,
    )


@patient_bp.route("/doctors/<int:doctor_id>/book", methods=["GET", "POST"])
@roles_required("patient")
def view_slots(doctor_id):
    """Patient picks a date, sees that doctor's available slots."""
    doctor = DoctorProfile.query.get_or_404(doctor_id)
    date_form = DateSelectForm()

    # Default to today if no date chosen yet
    if request.method == "POST" and date_form.validate_on_submit():
        chosen_date = date_form.appointment_date.data
    else:
        chosen_date = request.args.get("date")
        chosen_date = datetime.strptime(chosen_date, "%Y-%m-%d").date() if chosen_date else date_cls.today()

    if chosen_date < date_cls.today():
        flash("You can't book a date in the past.", "error")
        chosen_date = date_cls.today()

    date_form.appointment_date.data = chosen_date
    available_slots = get_available_slots(doctor, chosen_date)

    # Build one CSRF-protected hold-form per visible slot
    slot_forms = []
    for slot_time in available_slots:
        f = HoldSlotForm()
        f.appointment_date.data = chosen_date.isoformat()
        f.start_time.data = slot_time.isoformat()
        slot_forms.append((slot_time, f))

    return render_template(
        "patient/view_slots.html",
        doctor=doctor, date_form=date_form, chosen_date=chosen_date, slot_forms=slot_forms,
    )


@patient_bp.route("/doctors/<int:doctor_id>/hold", methods=["POST"])
@roles_required("patient")
def hold_slot(doctor_id):
    """
    Patient clicked a specific slot. We create a 'held' appointment.

    *** THIS IS WHERE THE DOUBLE-BOOKING PROTECTION ACTUALLY FIRES ***
    If two patients click the SAME slot within the same instant, both
    requests reach this code. The first one to commit succeeds. The
    second one hits our partial unique index from Phase 1 and raises
    an IntegrityError -- which we catch gracefully below instead of
    letting the app crash with a server error.
    """
    doctor = DoctorProfile.query.get_or_404(doctor_id)
    form = HoldSlotForm()

    if not form.validate_on_submit():
        flash("Something went wrong. Please try again.", "error")
        return redirect(url_for("patient.view_slots", doctor_id=doctor_id))

    appointment_date = datetime.strptime(form.appointment_date.data, "%Y-%m-%d").date()
    start_time = datetime.strptime(form.start_time.data, "%H:%M:%S").time()
    end_time = calculate_end_time(start_time, doctor.slot_duration_minutes)

    new_hold = Appointment(
        patient_id=current_user.id,
        doctor_id=doctor.id,
        appointment_date=appointment_date,
        start_time=start_time,
        end_time=end_time,
        status="held",
        hold_expires_at=datetime.utcnow() + timedelta(minutes=HOLD_DURATION_MINUTES),
    )
    db.session.add(new_hold)

    try:
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        flash("Sorry, someone just booked that slot. Please pick another.", "error")
        return redirect(url_for("patient.view_slots", doctor_id=doctor_id, date=appointment_date.isoformat()))

    flash(f"Slot held for {HOLD_DURATION_MINUTES} minutes. Please complete the symptom form to continue.", "success")
    return redirect(url_for("patient.symptom_form", appointment_id=new_hold.id))


@patient_bp.route("/appointments/<int:appointment_id>/symptoms", methods=["GET", "POST"])
@roles_required("patient")
def symptom_form(appointment_id):
    """
    Step 2 of booking: patient describes symptoms before confirming.
    We ALWAYS save the raw symptoms text first (guaranteed to succeed,
    it's just our own database) and only THEN attempt the AI summary
    as a separate, fail-safe step.
    """
    appointment = Appointment.query.get_or_404(appointment_id)

    if appointment.patient_id != current_user.id:
        flash("You don't have access to this appointment.", "error")
        return redirect(url_for("patient.search_doctors"))

    if appointment.status != "held":
        flash("This booking is no longer pending.", "error")
        return redirect(url_for("patient.my_appointments"))

    if appointment.hold_expires_at < datetime.utcnow():
        appointment.status = "cancelled"
        db.session.commit()
        flash("Your hold on this slot expired. Please choose a slot again.", "error")
        return redirect(url_for("patient.view_slots", doctor_id=appointment.doctor_id))

    existing_record = appointment.symptom_form
    form = SymptomReportForm(obj=existing_record) if existing_record else SymptomReportForm()

    if form.validate_on_submit():
        if existing_record:
            symptom_record = existing_record
            symptom_record.symptoms_text = form.symptoms_text.data
        else:
            symptom_record = SymptomForm(appointment_id=appointment.id, symptoms_text=form.symptoms_text.data)
            db.session.add(symptom_record)

        # Save the raw symptoms NOW -- this part cannot fail due to an
        # external service, so the patient's input is never lost.
        db.session.commit()

        # Attempt the AI summary as a clearly separate, fail-safe step.
        ai_result = llm_service.generate_pre_visit_summary(form.symptoms_text.data)

        if ai_result:
            symptom_record.ai_urgency_level = ai_result["urgency_level"]
            symptom_record.ai_chief_complaint = ai_result["chief_complaint"]
            symptom_record.ai_suggested_questions = json.dumps(ai_result["suggested_questions"])
            symptom_record.ai_summary_failed = False
            flash("Symptoms submitted. An AI summary has been prepared for your doctor.", "success")
        else:
            symptom_record.ai_summary_failed = True
            flash("Symptoms submitted. (AI summary is temporarily unavailable, but your doctor will see your full symptoms.)", "success")

        db.session.commit()
        return redirect(url_for("patient.confirm_booking", appointment_id=appointment.id))

    seconds_remaining = int((appointment.hold_expires_at - datetime.utcnow()).total_seconds())
    return render_template(
        "patient/symptom_form.html", appointment=appointment, form=form, seconds_remaining=seconds_remaining
    )


@patient_bp.route("/appointments/<int:appointment_id>/confirm", methods=["GET", "POST"])
@roles_required("patient")
def confirm_booking(appointment_id):
    appointment = Appointment.query.get_or_404(appointment_id)

    # Security check: a patient must only be able to confirm THEIR OWN hold
    if appointment.patient_id != current_user.id:
        flash("You don't have access to this appointment.", "error")
        return redirect(url_for("patient.search_doctors"))

    if appointment.status != "held":
        flash("This booking is no longer pending confirmation.", "error")
        return redirect(url_for("patient.my_appointments"))

    if appointment.hold_expires_at < datetime.utcnow():
        appointment.status = "cancelled"
        db.session.commit()
        flash("Your hold on this slot expired. Please choose a slot again.", "error")
        return redirect(url_for("patient.view_slots", doctor_id=appointment.doctor_id))

    if appointment.symptom_form is None:
        flash("Please tell us your symptoms before confirming.", "error")
        return redirect(url_for("patient.symptom_form", appointment_id=appointment.id))

    form = ConfirmBookingForm()
    if form.validate_on_submit():
        appointment.status = "booked"
        db.session.commit()

        # Send confirmation emails to both patient and doctor.
        email_service.send_booking_confirmation_patient(appointment)
        email_service.send_booking_confirmation_doctor(appointment)

        # Create a Google Calendar event (clinic calendar, both as attendees).
        # Fire-and-forget: failure here never blocks the booking.
        event_id = calendar_service.create_calendar_event(appointment)
        if event_id:
            appointment.google_calendar_event_id = event_id
            db.session.commit()

        flash("Appointment confirmed! A confirmation email has been sent.", "success")
        return redirect(url_for("patient.my_appointments"))

    seconds_remaining = int((appointment.hold_expires_at - datetime.utcnow()).total_seconds())
    return render_template(
        "patient/confirm_booking.html", appointment=appointment, form=form, seconds_remaining=seconds_remaining
    )


@patient_bp.route("/appointments")
@roles_required("patient")
def my_appointments():
    appointments = (
        Appointment.query.filter_by(patient_id=current_user.id)
        .filter(Appointment.status.in_(["booked", "completed", "cancelled"]))
        .order_by(Appointment.appointment_date.desc(), Appointment.start_time.desc())
        .all()
    )
    cancel_form = CancelAppointmentForm()
    return render_template("patient/my_appointments.html", appointments=appointments, cancel_form=cancel_form)


@patient_bp.route("/appointments/<int:appointment_id>/summary")
@roles_required("patient")
def visit_summary(appointment_id):
    """
    Patient views the AI-generated patient-friendly summary after a
    completed visit (Phase 6 output, viewed from the patient side).
    """
    appointment = Appointment.query.get_or_404(appointment_id)

    if appointment.patient_id != current_user.id:
        flash("You don't have access to this appointment.", "error")
        return redirect(url_for("patient.my_appointments"))

    if appointment.status != "completed" or appointment.visit_note is None:
        flash("This visit summary isn't available yet.", "error")
        return redirect(url_for("patient.my_appointments"))

    return render_template("patient/visit_summary.html", appointment=appointment)


@patient_bp.route("/appointments/<int:appointment_id>/cancel", methods=["POST"])
@roles_required("patient")
def cancel_appointment(appointment_id):
    appointment = Appointment.query.get_or_404(appointment_id)

    if appointment.patient_id != current_user.id:
        flash("You don't have access to this appointment.", "error")
        return redirect(url_for("patient.my_appointments"))

    if appointment.status != "booked":
        flash("Only booked appointments can be cancelled.", "error")
        return redirect(url_for("patient.my_appointments"))

    appointment.status = "cancelled"
    db.session.commit()

    # Notify the patient their booking is cancelled.
    email_service.send_cancellation_patient(appointment)

    # Delete the calendar event -- Google notifies attendees automatically.
    calendar_service.delete_calendar_event(appointment)

    flash("Appointment cancelled.", "success")
    return redirect(url_for("patient.my_appointments"))
