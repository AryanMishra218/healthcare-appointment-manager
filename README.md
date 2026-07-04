# ⚕ HealthConnect — Healthcare Appointment & Follow-up Manager

A full-stack clinic management platform with AI-powered visit summaries,
email notifications, Google Calendar integration, and background reminder jobs.

**Live demo:** https://healthcare-appointment-manager-ywtv.onrender.com/

## 🔑 Demo Credentials

| Role | Email / ID | Password |
|---|---|---|
| Admin | demo.admin@healthconnect.com | Demo@1234 |
| Patient | Register your own account (takes 10 seconds), or use: `patient.demo@healthconnect.com` | Demo@1234 |
| Doctor | Log in as Admin → **Manage Doctors** to see all doctor IDs and create/reset one | *(temp password shown on creation)* |

---

## Table of Contents

1. [Features](#features)
2. [Tech Stack](#tech-stack)
3. [Quick Start (Local)](#quick-start-local)
4. [Environment Variables](#environment-variables)
5. [Database Schema](#database-schema)
6. [API Reference](#api-reference)
7. [LLM Prompts](#llm-prompts)
8. [Google Calendar Setup](#google-calendar-setup)
9. [Deploy to Render](#deploy-to-render)
10. [Running Tests](#running-tests)

---

## Features

| Feature | Details |
|---|---|
| **3-role auth** | Patient, Doctor, Admin — each with their own portal |
| **Booking engine** | Slot generation, 5-minute holds, double-booking prevention at DB level |
| **AI pre-visit summary** | Gemini analyzes symptoms → urgency level + chief complaint + 3 questions for doctor |
| **AI post-visit summary** | Gemini converts clinical notes into patient-friendly language |
| **Email notifications** | Booking confirmation, cancellation, reminders via Gmail SMTP |
| **Google Calendar** | Events created for both patient and doctor on booking; deleted on cancellation |
| **Leave management** | Admin marks doctor leave → conflicting bookings auto-cancelled + patients notified |
| **Background jobs** | Appointment reminders (8 AM daily), medication reminders (hourly), email retry (every 30 min) |
| **Notification audit log** | Every email attempt logged with status + error for full traceability |

---

## Tech Stack

- **Backend:** Python 3.11+, Flask 3.0, SQLAlchemy, Flask-Login, Flask-WTF
- **Database:** PostgreSQL (production) / SQLite (local development)
- **AI:** Google Gemini 1.5 Flash
- **Email:** Gmail SMTP
- **Calendar:** Google Calendar API v3 with OAuth 2.0
- **Background jobs:** APScheduler
- **Deployment:** Render

---

## Quick Start (Local)

### Prerequisites
- Python 3.11+
- Git

### Steps

```bash
# 1. Clone the repository
git clone https://github.com/YOUR_USERNAME/healthcare-appointment-manager.git
cd healthcare-appointment-manager

# 2. Create and activate a virtual environment
python3 -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate

# 3. Install dependencies
pip install -r requirements.txt

# 4. Create your .env file
cp .env.example .env
# Edit .env and fill in at minimum: SECRET_KEY
# Leave DATABASE_URL blank to use a local SQLite file

# 5. Set up the database
export FLASK_APP=run.py
flask db init
flask db migrate -m "initial"
flask db upgrade

# 6. Create the first admin account
flask create-admin

# 7. Start the development server
python run.py
```

Visit **http://localhost:5000** — you'll be redirected to the login page.

**First steps after starting:**
1. Log in as admin → **Manage Doctors** → add a doctor
2. Open a new browser tab → register a patient account → book an appointment
3. Log in as the doctor → view the patient's AI-generated symptom summary → complete the visit

---

## Environment Variables

Copy `.env.example` to `.env` and fill in the values below.

| Variable | Required | Description |
|---|---|---|
| `SECRET_KEY` | ✅ Yes | Any long random string. Generate with: `python -c "import secrets; print(secrets.token_hex(32))"` |
| `DATABASE_URL` | Production only | PostgreSQL URL from Render. Leave blank locally (uses SQLite). |
| `GEMINI_API_KEY` | Optional | Free key from [aistudio.google.com](https://aistudio.google.com/app/apikey). Without it, AI summaries are skipped gracefully. |
| `GMAIL_ADDRESS` | Optional | The Gmail address emails will be sent from. Without it, emails are logged as failed but booking works. |
| `GMAIL_APP_PASSWORD` | Optional | A Gmail App Password (not your normal password) — generate one at [myaccount.google.com/apppasswords](https://myaccount.google.com/apppasswords). |
| `GOOGLE_CLIENT_ID` | Optional | From Google Cloud Console (see Google Calendar Setup). |
| `GOOGLE_CLIENT_SECRET` | Optional | From Google Cloud Console. |

> **Note:** All external services (Gemini, Gmail, Google Calendar) are optional for local development.
> The core booking and visit flow works without any of them.

---

## Database Schema

```
users
  id, name, email, password_hash, role (patient|doctor|admin), created_at

doctor_profiles
  id, user_id→users, specialization, working_start, working_end,
  slot_duration_minutes

doctor_leaves
  id, doctor_id→doctor_profiles, leave_date, reason
  UNIQUE(doctor_id, leave_date)

appointments
  id, patient_id→users, doctor_id→doctor_profiles,
  appointment_date, start_time, end_time,
  status (held|booked|completed|cancelled),
  hold_expires_at, google_calendar_event_id, created_at
  PARTIAL UNIQUE INDEX on (doctor_id, appointment_date, start_time)
  WHERE status != 'cancelled'

symptom_forms
  id, appointment_id→appointments,
  symptoms_text, ai_urgency_level, ai_chief_complaint,
  ai_suggested_questions (JSON), ai_summary_failed, created_at

visit_notes
  id, appointment_id→appointments,
  clinical_notes, prescription,
  ai_patient_summary, ai_summary_failed, created_at

notifications_log
  id, recipient_email, notification_type, related_appointment_id→appointments,
  status (pending|sent|failed|retrying), retry_count, error_message,
  created_at, sent_at

google_oauth_tokens
  id, refresh_token, access_token, token_expiry, created_at
```

---

## API Reference

All routes return HTML (server-rendered). Role restrictions are enforced server-side.

### Auth
| Method | URL | Role | Description |
|---|---|---|---|
| GET/POST | `/auth/register` | Public | Patient self-registration |
| GET/POST | `/auth/login` | Public | Login for all roles |
| GET | `/auth/logout` | Any | Logout |

### Patient
| Method | URL | Role | Description |
|---|---|---|---|
| GET | `/patient/doctors` | Patient | Search doctors by specialization |
| GET/POST | `/patient/doctors/<id>/book` | Patient | View available slots for a doctor |
| POST | `/patient/doctors/<id>/hold` | Patient | Hold a slot (creates 5-minute hold) |
| GET/POST | `/patient/appointments/<id>/symptoms` | Patient | Submit symptom form |
| GET/POST | `/patient/appointments/<id>/confirm` | Patient | Confirm a held booking |
| GET | `/patient/appointments` | Patient | List all appointments |
| GET | `/patient/appointments/<id>/summary` | Patient | View post-visit AI summary |
| POST | `/patient/appointments/<id>/cancel` | Patient | Cancel a booked appointment |

### Doctor
| Method | URL | Role | Description |
|---|---|---|---|
| GET | `/doctor/appointments` | Doctor | List upcoming + completed appointments |
| GET/POST | `/doctor/appointments/<id>` | Doctor | View pre-visit AI summary; submit visit notes |

### Admin
| Method | URL | Role | Description |
|---|---|---|---|
| GET | `/admin/doctors` | Admin | List all doctors |
| GET/POST | `/admin/doctors/new` | Admin | Create a new doctor account |
| GET | `/admin/doctors/<id>` | Admin | View doctor detail + manage leaves |
| POST | `/admin/doctors/<id>/leave` | Admin | Add a leave day |
| GET | `/calendar/status` | Admin | Google Calendar connection status |
| GET | `/calendar/authorize` | Admin | Start Google OAuth flow |
| GET | `/calendar/callback` | Admin | OAuth callback (set as redirect URI in Google Console) |
| POST | `/calendar/disconnect` | Admin | Remove Google Calendar integration |

### System
| Method | URL | Role | Description |
|---|---|---|---|
| GET | `/health` | Public | Health check + scheduler status (JSON) |

---

## LLM Prompts

### Pre-Visit Symptom Summary (Gemini)

```
Analyse these symptoms and return: urgency level (Low / Medium / High),
chief complaint, and three suggested questions for the doctor.
Symptoms: {symptoms_text}

Respond with ONLY valid JSON in exactly this shape, no markdown formatting,
no extra commentary:
{
  "urgency_level": "Low",
  "chief_complaint": "one short sentence",
  "suggested_questions": ["question 1", "question 2", "question 3"]
}
```

**Model:** `gemini-1.5-flash` | **Temperature:** 0.3 | **Max tokens:** 300

**Failure handling:** if Gemini returns an error, malformed JSON, or a
missing key, `ai_summary_failed` is set to `True` and the doctor sees
the patient's raw symptom text instead. The booking flow continues normally.

### Post-Visit Patient Summary (Gemini)

```
Convert these clinical notes into a patient-friendly summary with
medication schedule and follow-up steps:
Clinical notes: {clinical_notes}
Prescription: {prescription}

Write in plain, reassuring language a patient with no medical background
can understand. Keep it under 200 words. Respond with plain text only,
no markdown formatting.
```

**Model:** `gemini-1.5-flash` | **Temperature:** 0.4 | **Max tokens:** 400

**Failure handling:** if Gemini fails, `ai_summary_failed` is set to `True`.
The patient sees the raw clinical notes instead. The visit is still marked complete.

---

## Google Calendar Setup

1. Go to [console.cloud.google.com](https://console.cloud.google.com)
2. Create a new project (e.g. "HealthConnect")
3. Go to **APIs & Services → Library** → search "Google Calendar API" → **Enable**
4. Go to **APIs & Services → Credentials → Create Credentials → OAuth 2.0 Client ID**
5. Choose **Web application**
6. Under **Authorised redirect URIs**, add:
   - `http://localhost:5000/calendar/callback` (for local development)
   - `https://your-app.onrender.com/calendar/callback` (for production)
7. Click **Create** → copy the **Client ID** and **Client Secret**
8. Add them to your `.env` file as `GOOGLE_CLIENT_ID` and `GOOGLE_CLIENT_SECRET`
9. Go to **APIs & Services → OAuth consent screen**:
   - Choose **External**
   - Fill in App name and support email
   - Add the scope: `https://www.googleapis.com/auth/calendar.events`
   - Add your own email as a **Test user** (required while app is in Testing mode)
10. In the running app, log in as admin → go to **/calendar/status** → click **Connect Google Calendar**

> **Note:** While the OAuth app is in "Testing" mode, only emails added as Test Users can authorize it.
> For production, submit the app for Google's verification.

---

## Deploy to Render

### First-time setup

1. Push your code to GitHub (see below)
2. Go to [render.com](https://render.com) → **New → Web Service**
3. Connect your GitHub repository
4. Fill in:
   - **Build Command:** `pip install -r requirements.txt`
   - **Start Command:** `gunicorn run:app`
   - **Environment:** Python 3
5. Click **New → PostgreSQL** → create a free database
6. Copy the **Internal Database URL** and set it as `DATABASE_URL` in your web service's Environment tab
7. Add all other environment variables from your `.env` file
8. Click **Deploy**

### Run database migrations on Render

In the Render dashboard → your web service → **Shell**:
```bash
flask db upgrade
flask create-admin
```

### Subsequent deploys

Every `git push origin main` automatically triggers a new deploy on Render.

---

## Running Tests

```bash
# Run all test files
PYTHONPATH=. python3 tests/test_phase7.py
PYTHONPATH=. python3 tests/test_phase8.py
PYTHONPATH=. python3 tests/test_phase9.py
```

Tests use mocking for all external APIs (Gemini, Gmail SMTP, Google Calendar)
so they run instantly without real credentials.

---

## Project Structure

```
healthcare-appointment-manager/
├── app/
│   ├── __init__.py          # App factory, blueprint registration, scheduler startup
│   ├── config.py            # All settings (reads from .env)
│   ├── models.py            # Database tables (SQLAlchemy)
│   ├── forms.py             # Form definitions (Flask-WTF)
│   ├── utils.py             # roles_required decorator, helpers
│   ├── cli.py               # flask create-admin command
│   ├── routes/
│   │   ├── auth.py          # Register, login, logout
│   │   ├── dashboard.py     # Role-based home routing, health check
│   │   ├── admin.py         # Doctor management, leave days
│   │   ├── patient.py       # Booking flow, symptom form, appointments
│   │   ├── doctor.py        # Visit detail, post-visit notes
│   │   └── calendar_oauth.py# Google OAuth flow
│   ├── services/
│   │   ├── scheduling.py    # Slot generation, hold expiry
│   │   ├── llm_service.py   # Gemini AI integration
│   │   ├── email_service.py # Gmail SMTP integration, retry logic
│   │   ├── calendar_service.py # Google Calendar API
│   │   ├── reminder_service.py # Prescription parsing, reminder logic
│   │   └── scheduler.py     # APScheduler background jobs
│   ├── templates/           # Jinja2 HTML templates
│   └── static/              # CSS
├── tests/
│   ├── test_phase7.py       # Email notification tests
│   ├── test_phase8.py       # Google Calendar tests
│   └── test_phase9.py       # Background job + parsing tests
├── .env.example             # Template for environment variables
├── .gitignore
├── requirements.txt
├── run.py                   # Entry point
├── SYSTEM_DESIGN.md         # Design decisions write-up
└── README.md
```
