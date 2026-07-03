from flask import Blueprint, render_template, redirect, url_for, flash
from flask_login import login_user, logout_user, login_required, current_user

from app.models import db, User
from app.forms import RegisterForm, LoginForm

# A "Blueprint" groups related routes together (all auth-related URLs
# live in this one file). We register this blueprint in app/__init__.py.
auth_bp = Blueprint("auth", __name__, url_prefix="/auth")


@auth_bp.route("/register", methods=["GET", "POST"])
def register():
    # If someone is already logged in, sending them back to register
    # makes no sense -- redirect them to their dashboard instead.
    if current_user.is_authenticated:
        return redirect(url_for("dashboard.home"))

    form = RegisterForm()

    # form.validate_on_submit() does THREE things at once:
    # 1. Checks this is a POST request (form was submitted)
    # 2. Checks the CSRF token is valid (protects against attacks)
    # 3. Runs all the validators we defined in forms.py (email format, etc.)
    if form.validate_on_submit():
        # Check this email isn't already registered
        existing_user = User.query.filter_by(email=form.email.data.lower()).first()
        if existing_user:
            flash("An account with this email already exists. Please log in instead.", "error")
            return redirect(url_for("auth.register"))

        # Role is hardcoded here -- this form can ONLY ever create patients
        new_user = User(
            name=form.name.data.strip(),
            email=form.email.data.lower().strip(),
            role="patient"
        )
        new_user.set_password(form.password.data)

        db.session.add(new_user)
        db.session.commit()

        flash("Account created successfully! Please log in.", "success")
        return redirect(url_for("auth.login"))

    return render_template("auth/register.html", form=form)


@auth_bp.route("/login", methods=["GET", "POST"])
def login():
    if current_user.is_authenticated:
        return redirect(url_for("dashboard.home"))

    form = LoginForm()

    if form.validate_on_submit():
        user = User.query.filter_by(email=form.email.data.lower().strip()).first()

        # IMPORTANT: we check "user exists AND password matches" together,
        # and show the SAME error message either way. If we said
        # "no account with that email" vs "wrong password" separately,
        # an attacker could use that to figure out which emails are
        # registered in our system -- a real security leak.
        if user is None or not user.check_password(form.password.data):
            flash("Invalid email or password.", "error")
            return redirect(url_for("auth.login"))

        login_user(user)
        flash(f"Welcome back, {user.name}!", "success")
        return redirect(url_for("dashboard.home"))

    return render_template("auth/login.html", form=form)


@auth_bp.route("/logout")
@login_required
def logout():
    logout_user()
    flash("You have been logged out.", "success")
    return redirect(url_for("auth.login"))
