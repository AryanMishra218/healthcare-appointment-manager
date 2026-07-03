import secrets
import string
from functools import wraps
from flask import abort
from flask_login import current_user


def generate_temp_password(length=10):
    """
    Generates a random, secure temporary password for newly created
    doctor accounts. The admin will see this ONCE on screen after
    creating the doctor, and is expected to share it with them
    (Phase 7 will instead email it automatically).
    """
    alphabet = string.ascii_letters + string.digits
    return "".join(secrets.choice(alphabet) for _ in range(length))


def roles_required(*allowed_roles):
    """
    A decorator we put on top of any route to restrict it to certain roles.

    WHY this matters: without it, a logged-in patient could simply type
    the URL for the admin dashboard into their browser and see it. This
    decorator checks the current user's role on EVERY request to a
    protected page, server-side -- never trust the frontend alone to
    hide things, since a user can always view page source or call the
    API directly.

    Usage:
        @roles_required("admin")
        def admin_only_page(): ...

        @roles_required("doctor", "admin")
        def doctor_or_admin_page(): ...
    """
    def decorator(view_func):
        @wraps(view_func)
        def wrapped(*args, **kwargs):
            if not current_user.is_authenticated:
                abort(401)  # Unauthorized -- not logged in at all
            if current_user.role not in allowed_roles:
                abort(403)  # Forbidden -- logged in, but wrong role
            return view_func(*args, **kwargs)
        return wrapped
    return decorator
