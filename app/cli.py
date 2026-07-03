import click
from app.models import db, User


def register_cli_commands(app):
    """
    Registers custom 'flask' terminal commands onto our app.
    Why a CLI command instead of a web form for creating admins?
    Because creating an admin account should require access to the
    SERVER ITSELF (terminal access), not just a web browser -- this is
    a standard real-world security boundary.
    """

    @app.cli.command("create-admin")
    @click.option("--name", prompt="Admin name")
    @click.option("--email", prompt="Admin email")
    @click.option("--password", prompt="Admin password", hide_input=True, confirmation_prompt=True)
    def create_admin(name, email, password):
        """Usage: flask create-admin"""
        email = email.lower().strip()

        existing = User.query.filter_by(email=email).first()
        if existing:
            click.echo(f"Error: a user with email {email} already exists.")
            return

        admin = User(name=name, email=email, role="admin")
        admin.set_password(password)
        db.session.add(admin)
        db.session.commit()

        click.echo(f"Admin account created: {email}")
