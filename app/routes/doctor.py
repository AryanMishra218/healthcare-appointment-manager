from datetime import date as date_cls

from flask import Blueprint, render_template, redirect, url_for, flash, current_app
from flask_login import current_user

from app.forms import VisitNoteForm, ChangePasswordForm, LeaveRequestForm
from app.models import db, Appointment, DoctorProfile, VisitNote, LeaveRequest
from app.utils import roles_required
from app.services import llm_service
from app.services import email_service

doctor_bp = Blueprint("doctor", __name__, url_prefix="/doctor")


def _get_current_doctor_profile():
    """
    Every doctor User has exactly one DoctorProfile (set up in Phase 1's
    relationship). This little helper saves us repeating the lookup in
    every route below.
    """
    return current_user.doctor_profile


@doctor_bp.route("/appointments")
@roles_required("doctor")
def appointments_list():
    doctor = _get_current_doctor_profile()

    upcoming = (
        Appointment.query.filter_by(doctor_id=doctor.id, status="booked")
        .order_by(Appointment.appointment_date, Appointment.start_time)
        .all()
    )
    completed = (
        Appointment.query.filter_by(doctor_id=doctor.id, status="completed")
        .order_by(Appointment.appointment_date.desc())
        .limit(10)
        .all()
    )

    return render_template("doctor/appointments_list.html", upcoming=upcoming, completed=completed)


@doctor_bp.route("/appointments/<int:appointment_id>", methods=["GET", "POST"])
@roles_required("doctor")
def appointment_detail(appointment_id):
    doctor = _get_current_doctor_profile()
    appointment = Appointment.query.get_or_404(appointment_id)

    # Security check: a doctor can only see THEIR OWN patients' appointments
    if appointment.doctor_id != doctor.id:
        flash("You don't have access to this appointment.", "error")
        return redirect(url_for("doctor.appointments_list"))

    form = VisitNoteForm()

    if appointment.status == "booked" and form.validate_on_submit():
        # Step 1: save the doctor's raw notes -- guaranteed to succeed,
        # this never depends on Gemini being available.
        visit_note = VisitNote(
            appointment_id=appointment.id,
            clinical_notes=form.clinical_notes.data,
            prescription=form.prescription.data,
        )
        db.session.add(visit_note)
        appointment.status = "completed"
        db.session.commit()

        # Step 2: attempt the AI patient-friendly summary as a separate,
        # fail-safe step -- a Gemini outage must never block the doctor
        # from completing a visit.
        ai_summary = llm_service.generate_post_visit_summary(
            form.clinical_notes.data, form.prescription.data
        )

        if ai_summary:
            visit_note.ai_patient_summary = ai_summary
            visit_note.ai_summary_failed = False
            flash("Visit completed. A patient-friendly summary has been generated.", "success")
        else:
            visit_note.ai_summary_failed = True
            flash("Visit completed. (AI patient summary is temporarily unavailable — your notes are saved.)", "success")

        db.session.commit()

       # Notify the patient their summary is ready to read.
        try:
            email_service.send_visit_summary_notification(appointment)
        except Exception as e:
            current_app.logger.error(f"Visit summary email failed: {e}")

        return redirect(url_for("doctor.appointments_list"))

    return render_template("doctor/appointment_detail.html", appointment=appointment, form=form)

@doctor_bp.route("/change-password", methods=["GET", "POST"])
@roles_required("doctor")
def change_password():
    form = ChangePasswordForm()

    if form.validate_on_submit():
        if not current_user.check_password(form.current_password.data):
            flash("Current password is incorrect.", "error")
            return redirect(url_for("doctor.change_password"))

        current_user.set_password(form.new_password.data)
        db.session.commit()
        flash("Password updated successfully.", "success")
        return redirect(url_for("dashboard.doctor_dashboard"))

    return render_template("doctor/change_password.html", form=form)

@doctor_bp.route("/leave-request", methods=["GET", "POST"])
@roles_required("doctor")
def leave_request():
    doctor = current_user.doctor_profile
    form = LeaveRequestForm()

    if form.validate_on_submit():
        # Don't allow duplicate pending requests for the same date
        existing = LeaveRequest.query.filter_by(
            doctor_id=doctor.id, leave_date=form.leave_date.data, status="pending"
        ).first()
        if existing:
            flash("You already have a pending request for this date.", "error")
            return redirect(url_for("doctor.leave_request"))

        req = LeaveRequest(
            doctor_id=doctor.id,
            leave_date=form.leave_date.data,
            reason=form.reason.data,
        )
        db.session.add(req)
        db.session.commit()
        flash("Leave request submitted. You'll be notified once admin responds.", "success")
        return redirect(url_for("doctor.leave_request"))

    my_requests = (
        LeaveRequest.query.filter_by(doctor_id=doctor.id)
        .order_by(LeaveRequest.requested_at.desc())
        .all()
    )
    return render_template("doctor/leave_request.html", form=form, requests=my_requests)