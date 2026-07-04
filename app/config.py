import os
from dotenv import load_dotenv

# load_dotenv() reads the .env file and makes its values available
# via os.environ.get(). This keeps secrets OUT of our code.
load_dotenv()


class Config:
    """
    All app settings live here. Why one central place?
    If we ever need to change a setting (e.g. switch databases),
    we change it in ONE file instead of hunting through the whole project.
    """

    # SECRET_KEY is used by Flask to securely sign session cookies
    # (e.g. to know a logged-in user's session hasn't been tampered with)
    SECRET_KEY = os.environ.get("SECRET_KEY", "dev-secret-key-change-this")

    # Database connection string. Render will give us a real PostgreSQL
    # URL in production; locally we fall back to a simple SQLite file
    # so you can run this WITHOUT installing PostgreSQL first.
    SQLALCHEMY_DATABASE_URI = os.environ.get(
        "DATABASE_URL", "sqlite:///healthcare.db"
    )

    SQLALCHEMY_TRACK_MODIFICATIONS = False

    # API keys for our external services
    GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
    SENDGRID_API_KEY = os.environ.get("SENDGRID_API_KEY")
    SENDGRID_FROM_EMAIL = os.environ.get("SENDGRID_FROM_EMAIL")

    # Google Calendar OAuth credentials
    GOOGLE_CLIENT_ID = os.environ.get("GOOGLE_CLIENT_ID")
    GOOGLE_CLIENT_SECRET = os.environ.get("GOOGLE_CLIENT_SECRET")

    GMAIL_ADDRESS = os.environ.get("GMAIL_ADDRESS")
    GMAIL_APP_PASSWORD = os.environ.get("GMAIL_APP_PASSWORD")
    BREVO_API_KEY = os.environ.get("BREVO_API_KEY")
