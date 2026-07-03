from flask import Flask
from flask_login import LoginManager
from flask_migrate import Migrate
from flask_wtf.csrf import CSRFProtect
#CSRFProtect is a Flask extension that adds Cross-Site Request Forgery protection to our app. It helps prevent malicious attacks where a user is tricked into performing actions they didn't intend to.

from app.config import Config
from app.models import db, User

# Extensions are created here but NOT attached to an app yet.
# We attach them inside create_app(). This pattern (Application Factory)
# is the professional standard because it lets us create multiple
# instances of the app later (e.g. one for testing, one for production)
# without them interfering with each other.
login_manager = LoginManager()
migrate = Migrate()
csrf = CSRFProtect()


def create_app():
    app = Flask(__name__)
    app.config.from_object(Config)

    # Attach our extensions to this specific app instance
    db.init_app(app)
    login_manager.init_app(app)
    migrate.init_app(app, db)
    csrf.init_app(app)

    # Flask-Login needs to know: "given a user id, how do I load that user?"
    @login_manager.user_loader
    def load_user(user_id):
        return db.session.get(User, int(user_id))

    # Where Flask-Login redirects people who try to access a protected
    # page without being logged in
    login_manager.login_view = "auth.login"

    # Register our route blueprints
    from app.routes.auth import auth_bp
    from app.routes.dashboard import dashboard_bp
    from app.routes.admin import admin_bp
    from app.routes.patient import patient_bp
    from app.routes.doctor import doctor_bp
    from app.routes.calendar_oauth import calendar_oauth_bp
    app.register_blueprint(auth_bp)
    app.register_blueprint(dashboard_bp)
    app.register_blueprint(admin_bp)
    app.register_blueprint(patient_bp)
    app.register_blueprint(doctor_bp)
    app.register_blueprint(calendar_oauth_bp)

    # Register our custom "flask create-admin" terminal command
    from app.cli import register_cli_commands
    register_cli_commands(app)

    # Process any pending leave_cancellation notifications from Phase 3
    # on each first request (not on startup, which is too early for the DB).
    _startup_done = {'done': False}

    @app.before_request
    def process_pending_emails_once():
        if not _startup_done['done']:
            _startup_done['done'] = True
            try:
                from app.services.email_service import process_pending_leave_cancellations
                process_pending_leave_cancellations()
            except Exception as e:
                import logging
                logging.getLogger(__name__).error(f"Startup email processing error: {e}")

    # Start the background job scheduler.
    # The scheduler itself guards against double-starts in debug mode.
    from app.services.scheduler import start_scheduler
    start_scheduler(app)

    return app
