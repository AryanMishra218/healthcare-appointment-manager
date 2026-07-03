"""
scheduler.py

Sets up and starts the APScheduler background job runner.

HOW IT WORKS:
APScheduler runs in a background thread inside the same Python process
as your Flask app. You register functions with it and tell it how often
to run them. It takes care of the rest.

IMPORTANT -- THE DOUBLE-START PROBLEM:
Flask's debug mode (python run.py) actually starts your app TWICE:
  - Process 1: file watcher (watches for code changes, restarts on save)
  - Process 2: actual web server

If we start the scheduler in both, every job runs twice simultaneously.
The fix: only start the scheduler when we're in the REAL server process.
Werkzeug (Flask's server) sets an environment variable 'WERKZEUG_RUN_MAIN'
to 'true' only in the real server process. We check for that.

On Render (production), there's only one process, so the scheduler
always starts exactly once.
"""

import os
import logging

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

logger = logging.getLogger(__name__)

# Global scheduler instance -- created once, shared across the app
_scheduler = None


def start_scheduler(app):
    """
    Creates and starts the background scheduler with all three jobs.
    Should only be called ONCE -- it guards against double-starts itself.
    """
    global _scheduler

    # THE DOUBLE-START GUARD:
    # In debug mode: WERKZEUG_RUN_MAIN is only 'true' in the real server process
    # In production (Render): this env var doesn't exist, so condition is True → scheduler starts
    is_debug_reloader = os.environ.get("WERKZEUG_RUN_MAIN") == "true"
    is_production = not app.debug

    if not is_debug_reloader and not is_production:
        logger.info("Scheduler skipped: running in Werkzeug file-watcher process.")
        return

    if _scheduler and _scheduler.running:
        logger.info("Scheduler already running — skipping duplicate start.")
        return

    _scheduler = BackgroundScheduler(daemon=True)
    # daemon=True means the scheduler thread is automatically killed
    # when the main Flask process exits (no zombie threads)

    # ── JOB 1: Appointment Reminders ───────────────────────────────────
    # Runs every morning at 8:00 AM.
    # "cron" trigger = runs at a specific time, like a traditional cron job.
    from app.services.reminder_service import send_appointment_reminders
    _scheduler.add_job(
        func=lambda: send_appointment_reminders(app),
        trigger=CronTrigger(hour=8, minute=0),
        id="appointment_reminders",
        name="Send appointment reminders for tomorrow",
        replace_existing=True,
        misfire_grace_time=3600,  # if server was down at 8am, run within 1hr of restart
    )

    # ── JOB 2: Medication Reminders ─────────────────────────────────────
    # Runs every hour at :00 (e.g. 8:00, 9:00, 10:00...).
    # Our reminder_service.py checks whether it's the right HOUR for each
    # prescription's frequency -- so running hourly is correct.
    from app.services.reminder_service import send_medication_reminders
    _scheduler.add_job(
        func=lambda: send_medication_reminders(app),
        trigger=CronTrigger(minute=0),  # top of every hour
        id="medication_reminders",
        name="Send medication reminders",
        replace_existing=True,
        misfire_grace_time=1800,
    )

    # ── JOB 3: Email Retry ───────────────────────────────────────────────
    # Runs every 30 minutes.
    # "interval" trigger = runs repeatedly on a fixed interval.
    # Scans notifications_log for status='failed' rows and retries them.
    from app.services.email_service import retry_failed_notifications
    _scheduler.add_job(
        func=lambda: _retry_with_context(app, retry_failed_notifications),
        trigger=IntervalTrigger(minutes=30),
        id="email_retry",
        name="Retry failed email notifications",
        replace_existing=True,
        misfire_grace_time=600,
    )

    _scheduler.start()
    logger.info(
        "Background scheduler started with 3 jobs: "
        "appointment reminders (8AM daily), "
        "medication reminders (hourly), "
        "email retry (every 30 min)."
    )


def _retry_with_context(app, func):
    """
    APScheduler runs jobs outside of a Flask request context, so
    functions that use the database (db.session, etc.) need to be
    wrapped in app.app_context(). This helper does that for the retry job.

    Note: reminder_service functions already handle their own app_context
    internally. The email retry function doesn't, so we wrap it here.
    """
    with app.app_context():
        func()


def get_scheduler_status():
    """
    Returns a dict with the current status of the scheduler and all jobs.
    Useful for a health-check endpoint (added in this phase).
    """
    if not _scheduler or not _scheduler.running:
        return {"running": False, "jobs": []}

    jobs = []
    for job in _scheduler.get_jobs():
        jobs.append({
            "id": job.id,
            "name": job.name,
            "next_run": str(job.next_run_time) if job.next_run_time else "N/A",
        })

    return {"running": True, "jobs": jobs}
