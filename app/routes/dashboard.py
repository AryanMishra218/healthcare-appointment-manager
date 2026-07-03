from datetime import date as date_cls
from flask import Blueprint, render_template, redirect, url_for, jsonify
from flask_login import login_required, current_user

from app.utils import roles_required
from app.models import DoctorProfile, Appointment

dashboard_bp = Blueprint("dashboard", __name__)


@dashboard_bp.route("/")
def index():
    """The site's homepage. Sends logged-in users to their dashboard,
    and everyone else to the login page."""
    if current_user.is_authenticated:
        return redirect(url_for("dashboard.home"))
    return redirect(url_for("auth.login"))


@dashboard_bp.route("/home")
@login_required
def home():
    """
    One smart 'home' URL that sends each role to ITS OWN dashboard.
    This means our login route never needs to know about roles --
    it just sends everyone here, and this function figures out the rest.
    """
    if current_user.role == "patient":
        return redirect(url_for("dashboard.patient_dashboard"))
    elif current_user.role == "doctor":
        return redirect(url_for("dashboard.doctor_dashboard"))
    elif current_user.role == "admin":
        return redirect(url_for("dashboard.admin_dashboard"))


@dashboard_bp.route("/patient/dashboard")
@roles_required("patient")
def patient_dashboard():
    upcoming = (
        Appointment.query.filter_by(patient_id=current_user.id, status="booked")
        .order_by(Appointment.appointment_date, Appointment.start_time)
        .all()
    )
    next_appointment = upcoming[0] if upcoming else None
    completed_count = Appointment.query.filter_by(
        patient_id=current_user.id, status="completed"
    ).count()

    return render_template(
        "dashboard/patient.html",
        next_appointment=next_appointment,
        upcoming_count=len(upcoming),
        completed_count=completed_count,
    )


@dashboard_bp.route("/doctor/dashboard")
@roles_required("doctor")
def doctor_dashboard():
    doctor = current_user.doctor_profile
    today = date_cls.today()

    today_appointments = Appointment.query.filter_by(
        doctor_id=doctor.id, status="booked", appointment_date=today
    ).count()
    upcoming_total = Appointment.query.filter_by(
        doctor_id=doctor.id, status="booked"
    ).count()
    completed_total = Appointment.query.filter_by(
        doctor_id=doctor.id, status="completed"
    ).count()

    return render_template(
        "dashboard/doctor.html",
        today_appointments=today_appointments,
        upcoming_total=upcoming_total,
        completed_total=completed_total,
    )


@dashboard_bp.route("/admin/dashboard")
@roles_required("admin")
def admin_dashboard():
    doctor_count = DoctorProfile.query.count()
    today = date_cls.today()
    todays_appointments = Appointment.query.filter_by(
        appointment_date=today, status="booked"
    ).count()

    return render_template(
        "dashboard/admin.html",
        doctor_count=doctor_count,
        todays_appointments=todays_appointments,
    )


@dashboard_bp.route("/health")
def health_check():
    """
    Public health-check endpoint.
    Render and other hosting services ping this to verify the app is alive.
    Also shows scheduler status so you can confirm background jobs are running.
    """
    from app.services.scheduler import get_scheduler_status
    scheduler_info = get_scheduler_status()
    return jsonify({
        "status": "ok",
        "scheduler": scheduler_info,
    }), 200