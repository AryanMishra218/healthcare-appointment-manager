from datetime import datetime
from flask import Blueprint, render_template, redirect, url_for, flash, request
from flask_login import login_required

from app.models import db, User, DoctorProfile, DoctorLeave, Appointment, NotificationLog, LeaveRequest
from app.forms import CreateDoctorForm, AddLeaveForm, EditDoctorForm
from app.utils import roles_required, generate_temp_password
from app.services import email_service

admin_bp = Blueprint("admin", __name__, url_prefix="/admin")


@admin_bp.route("/doctors")
@roles_required("admin")
def list_doctors():
    doctors = DoctorProfile.query.join(User).order_by(User.name).all()
    return render_template("admin/doctors_list.html", doctors=doctors)


@admin_bp.route("/doctors/new", methods=["GET", "POST"])
@roles_required("admin")

#Creation of a new doctor profile by the admin. This route handles both displaying the form and processing the form submission.
def create_doctor():
    form = CreateDoctorForm()

    if form.validate_on_submit():
        email = form.email.data.lower().strip()

        if User.query.filter_by(email=email).first():
            flash("A user with this email already exists.", "error")
            return redirect(url_for("admin.create_doctor"))

        if form.working_start.data >= form.working_end.data:
            flash("Working start time must be before end time.", "error")
            return redirect(url_for("admin.create_doctor"))

        # Step 1: create the login account (role='doctor')
        temp_password = generate_temp_password()
        doctor_user = User(name=form.name.data.strip(), email=email, role="doctor")
        doctor_user.set_password(temp_password)
        db.session.add(doctor_user)
        db.session.flush()  # lets us use doctor_user.id before committing

        # Doctor ID is derived from their user id, so it's guaranteed
        # unique for free -- no separate uniqueness check needed.
        doctor_user.username = f"DOC{doctor_user.id:04d}"

        # Step 2: create their clinical profile
        profile = DoctorProfile(
            user_id=doctor_user.id,
            specialization=form.specialization.data.strip(),
            working_start=form.working_start.data,
            working_end=form.working_end.data,
            slot_duration_minutes=form.slot_duration_minutes.data,
        )
        db.session.add(profile)
        db.session.commit()

        # Email the credentials to the doctor's real email address.
        # This does NOT block account creation if it fails -- the admin
        # still sees the credentials on screen below either way.
        email_service.send_doctor_credentials(doctor_user, temp_password)

        flash(
            f"Doctor profile created for {doctor_user.name}. "
            f"Doctor ID: {doctor_user.username} — Temporary password: {temp_password} "
            f"(also emailed to {doctor_user.email}, but share this securely too — it won't be shown again here)",
            "success"
        )
        return redirect(url_for("admin.list_doctors"))

    return render_template("admin/create_doctor.html", form=form)


@admin_bp.route("/doctors/<int:doctor_id>")
@roles_required("admin")
def doctor_detail(doctor_id):
    doctor = DoctorProfile.query.get_or_404(doctor_id)
    leave_form = AddLeaveForm()
    upcoming_leaves = (
        DoctorLeave.query.filter_by(doctor_id=doctor.id)
        .filter(DoctorLeave.leave_date >= datetime.utcnow().date())
        .order_by(DoctorLeave.leave_date)
        .all()
    )
    return render_template(
        "admin/doctor_detail.html", doctor=doctor, leave_form=leave_form, leaves=upcoming_leaves
    )

@admin_bp.route("/doctors/<int:doctor_id>/edit", methods=["GET", "POST"])
@roles_required("admin")
def edit_doctor(doctor_id):
    doctor = DoctorProfile.query.get_or_404(doctor_id)
    form = EditDoctorForm(obj=doctor)

    if request.method == "GET":
        form.email.data = doctor.user.email

    if form.validate_on_submit():
        email = form.email.data.lower().strip()

        # Make sure this email isn't already used by a DIFFERENT user
        existing = User.query.filter_by(email=email).first()
        if existing and existing.id != doctor.user.id:
            flash("A user with this email already exists.", "error")
            return redirect(url_for("admin.edit_doctor", doctor_id=doctor_id))

        if form.working_start.data >= form.working_end.data:
            flash("Working start time must be before end time.", "error")
            return redirect(url_for("admin.edit_doctor", doctor_id=doctor_id))

        doctor.user.email = email
        doctor.specialization = form.specialization.data.strip()
        doctor.working_start = form.working_start.data
        doctor.working_end = form.working_end.data
        doctor.slot_duration_minutes = form.slot_duration_minutes.data

        db.session.commit()
        flash(f"{doctor.user.name}'s profile has been updated.", "success")
        return redirect(url_for("admin.doctor_detail", doctor_id=doctor_id))

    return render_template("admin/edit_doctor.html", doctor=doctor, form=form)


def _create_leave_and_cancel_conflicts(doctor, leave_date, reason):
    """
    Shared logic: creates a DoctorLeave row, cancels any conflicting
    appointments on that date, and queues patient notifications.
    Used by BOTH the admin's direct 'Add Leave Day' action and by
    approving a doctor's leave request -- so both paths behave
    identically. Returns the number of appointments affected.
    """
    leave = DoctorLeave(doctor_id=doctor.id, leave_date=leave_date, reason=reason)
    db.session.add(leave)

    conflicting_appointments = Appointment.query.filter(
        Appointment.doctor_id == doctor.id,
        Appointment.appointment_date == leave_date,
        Appointment.status.in_(["held", "booked"]),
    ).all()

    affected_count = 0
    for appt in conflicting_appointments:
        appt.status = "cancelled"
        affected_count += 1

        patient = User.query.get(appt.patient_id)
        notification = NotificationLog(
            recipient_email=patient.email,
            notification_type="leave_cancellation",
            related_appointment_id=appt.id,
            status="pending",
        )
        db.session.add(notification)

    return affected_count


@admin_bp.route("/doctors/<int:doctor_id>/leave", methods=["POST"])
@roles_required("admin")
def add_leave(doctor_id):
    """
    Admin directly marks a doctor unavailable on a date (not via a
    doctor's request -- this is the original, always-available path).
    """
    doctor = DoctorProfile.query.get_or_404(doctor_id)
    form = AddLeaveForm()

    if not form.validate_on_submit():
        flash("Please provide a valid leave date.", "error")
        return redirect(url_for("admin.doctor_detail", doctor_id=doctor_id))

    existing = DoctorLeave.query.filter_by(doctor_id=doctor.id, leave_date=form.leave_date.data).first()
    if existing:
        flash("This leave date is already recorded.", "error")
        return redirect(url_for("admin.doctor_detail", doctor_id=doctor_id))

    affected_count = _create_leave_and_cancel_conflicts(doctor, form.leave_date.data, form.reason.data)
    db.session.commit()

    if affected_count > 0:
        flash(
            f"Leave day added. {affected_count} existing appointment(s) were cancelled "
            f"and queued for patient notification.",
            "success"
        )
    else:
        flash("Leave day added. No existing appointments were affected.", "success")

    return redirect(url_for("admin.doctor_detail", doctor_id=doctor_id))

@admin_bp.route("/leave-requests")
@roles_required("admin")
def leave_requests():
    pending = (
        LeaveRequest.query.filter_by(status="pending")
        .order_by(LeaveRequest.requested_at)
        .all()
    )
    decided = (
        LeaveRequest.query.filter(LeaveRequest.status != "pending")
        .order_by(LeaveRequest.decided_at.desc())
        .limit(20)
        .all()
    )
    return render_template("admin/leave_requests.html", pending=pending, decided=decided)


@admin_bp.route("/leave-requests/<int:request_id>/approve", methods=["POST"])
@roles_required("admin")
def approve_leave_request(request_id):
    leave_req = LeaveRequest.query.get_or_404(request_id)

    if leave_req.status != "pending":
        flash("This request has already been decided.", "error")
        return redirect(url_for("admin.leave_requests"))

    existing = DoctorLeave.query.filter_by(
        doctor_id=leave_req.doctor_id, leave_date=leave_req.leave_date
    ).first()
    if existing:
        flash("This date is already marked as a leave day for this doctor.", "error")
        leave_req.status = "declined"
        leave_req.decided_at = datetime.utcnow()
        db.session.commit()
        return redirect(url_for("admin.leave_requests"))

    affected_count = _create_leave_and_cancel_conflicts(
        leave_req.doctor, leave_req.leave_date, leave_req.reason
    )
    leave_req.status = "approved"
    leave_req.decided_at = datetime.utcnow()
    db.session.commit()

    flash(
        f"Approved. {leave_req.doctor.user.name}'s leave on {leave_req.leave_date.strftime('%d %b %Y')} "
        f"is recorded. {affected_count} appointment(s) cancelled and queued for notification.",
        "success"
    )
    return redirect(url_for("admin.leave_requests"))


@admin_bp.route("/leave-requests/<int:request_id>/decline", methods=["POST"])
@roles_required("admin")
def decline_leave_request(request_id):
    leave_req = LeaveRequest.query.get_or_404(request_id)

    if leave_req.status != "pending":
        flash("This request has already been decided.", "error")
        return redirect(url_for("admin.leave_requests"))

    leave_req.status = "declined"
    leave_req.decided_at = datetime.utcnow()
    db.session.commit()

    flash(f"Declined {leave_req.doctor.user.name}'s leave request.", "success")
    return redirect(url_for("admin.leave_requests"))