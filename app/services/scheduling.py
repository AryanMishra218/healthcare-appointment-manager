from datetime import datetime, date as date_cls, timedelta

from app.models import db, Appointment, DoctorLeave

# How long a slot stays "held" before it's released back to the pool.
HOLD_DURATION_MINUTES = 5


def release_expired_holds(doctor_id, appointment_date):
    """
    'Lazy cleanup': run this right before we need accurate slot
    availability. Any 'held' appointment whose hold has expired gets
    flipped to 'cancelled', freeing that slot for someone else.

    Why not a background job for this? Because we only need this data
    to be accurate AT THE MOMENT someone is looking at available slots
    -- doing it lazily, on-demand, is simpler and just as correct as a
    timer running every few seconds.
    """
    now = datetime.utcnow()
    expired = Appointment.query.filter(
        Appointment.doctor_id == doctor_id,
        Appointment.appointment_date == appointment_date,
        Appointment.status == "held",
        Appointment.hold_expires_at < now,
    ).all()

    for appt in expired:
        appt.status = "cancelled"

    if expired:
        db.session.commit()


def get_available_slots(doctor, appointment_date):
    """
    Returns a list of available time objects for a given doctor and date.

    Steps:
    1. Release any expired holds first, so our availability check is accurate.
    2. If the doctor is on leave that day, return an empty list immediately.
    3. Generate every possible slot from working_start to working_end.
    4. Remove slots that already have an active appointment (booked, or
       held with time still remaining).
    """
    release_expired_holds(doctor.id, appointment_date)

    is_on_leave = DoctorLeave.query.filter_by(
        doctor_id=doctor.id, leave_date=appointment_date
    ).first() is not None
    if is_on_leave:
        return []

    # Generate all possible slots using a dummy date (date_cls.min) just
    # to do clean time arithmetic -- we only care about the TIME part.
    slot_duration = timedelta(minutes=doctor.slot_duration_minutes)
    current = datetime.combine(date_cls.min, doctor.working_start)
    end = datetime.combine(date_cls.min, doctor.working_end)

    all_slots = []
    while current + slot_duration <= end:
        all_slots.append(current.time())
        current += slot_duration

    # Find times that are already taken (booked, or actively held)
    taken_appointments = Appointment.query.filter(
        Appointment.doctor_id == doctor.id,
        Appointment.appointment_date == appointment_date,
        Appointment.status.in_(["booked", "held"]),
    ).all()
    taken_times = {appt.start_time for appt in taken_appointments}

    # If the requested date is today, also remove slots already in the past
    available = []
    now_time = datetime.utcnow().time()
    is_today = appointment_date == date_cls.today()

    for slot_time in all_slots:
        if slot_time in taken_times:
            continue
        if is_today and slot_time <= now_time:
            continue
        available.append(slot_time)

    return available


def calculate_end_time(start_time, slot_duration_minutes):
    """Given a start time and duration, returns the end time."""
    start_dt = datetime.combine(date_cls.min, start_time)
    end_dt = start_dt + timedelta(minutes=slot_duration_minutes)
    return end_dt.time()
