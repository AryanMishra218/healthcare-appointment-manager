from datetime import datetime
from flask import Blueprint, render_template, redirect, url_for, flash, request
from flask_login import login_required

from app.models import db, User, DoctorProfile, DoctorLeave, Appointment, NotificationLog
from app.forms import CreateDoctorForm, AddLeaveForm, EditDoctorForm
from app.utils import roles_required, generate_temp_password

admin_bp = Blueprint("admin", __name__, url_prefix="/admin")


@admin_bp.route("/doctors")
@roles_required("admin")
def list_doctors():
    doctors = DoctorProfile.query.join(User).order_by(User.name).all()
    return render_template("admin/doctors_list.html", doctors=doctors)


@admin_bp.route("/doctors/new", methods=["GET", "POST"])
@roles_required("admin")
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

        # We show the temp password ONCE -- in Phase 7 this will be emailed
        # automatically instead, and this flash message will be removed.
        flash(
            f"Doctor profile created for {doctor_user.name}. "
            f"Temporary login password: {temp_password} (share this securely — it won't be shown again)",
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

@admin_bp.route("/doctors/<int:doctor_id>/leave", methods=["POST"])
@roles_required("admin")
def add_leave(doctor_id):
    """
    THIS IS THE LEAVE-CONFLICT REQUIREMENT FROM THE ASSIGNMENT:
    'When a doctor is marked on leave for a date with existing bookings,
    affected patients must be notified.'

    Our approach, step by step:
    1. Save the leave day.
    2. Find every appointment for this doctor on that date that is
       still active ('held' or 'booked') -- these can no longer happen.
    3. Cancel each of those appointments (status='cancelled'), which
       ALSO frees the slot back up in our double-booking system.
    4. Create a NotificationLog row for each affected patient with
       status='pending'. We don't send the actual email yet (that's
       Phase 7) -- but the record of "this needs to be sent" is
       created the moment the conflict happens, not forgotten.
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

    leave = DoctorLeave(doctor_id=doctor.id, leave_date=form.leave_date.data, reason=form.reason.data)
    db.session.add(leave)

    # Find appointments that conflict with this new leave day
    conflicting_appointments = Appointment.query.filter(
        Appointment.doctor_id == doctor.id,
        Appointment.appointment_date == form.leave_date.data,
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
