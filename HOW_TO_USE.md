# HealthConnect — How To Use
## Complete Step-by-Step Guide for Admin, Doctor & Patient

---

## FIRST TIME SETUP (Do this once before anything else)

### Step 1 — Start the app
Open terminal in the project folder and run:
```bash
python run.py
```
You should see:
```
* Running on http://127.0.0.1:5000
```

### Step 2 — Create the Admin account (one time only)
Open a NEW terminal window (keep the first one running) and run:
```bash
flask create-admin
```
It will ask you:
```
Admin name:     Aryan Mishra
Admin email:    youremail@gmail.com
Admin password: (type any password, min 8 characters)
```
Output you should see:
```
Admin account created: youremail@gmail.com
```
**Important:** Write down this email and password. This is the master
account for the entire clinic. There is no "forgot password" for admin.

---

## LOGGING IN / REGISTERING

Every role signs in on the same page: `http://127.0.0.1:5000`. The
login and signup pages now show a **HealthConnect brand banner** on
the side with a quick summary of what the platform does — this is
just visual, it doesn't change how you log in.

On any inner page (appointments, booking flow, doctor management,
etc.) you'll see a **← Back** link near the top-left. Click it to
return to the previous screen instead of using your browser's back
button.

---

## ADMIN GUIDE

### How to Log In as Admin

1. Open browser → go to `http://127.0.0.1:5000`
2. You will be redirected to the login page automatically
3. Enter your admin email and password
4. You will land on the **Admin Dashboard**

The dashboard now shows:
- **Stat cards** at the top — Total Doctors and Today's Appointments, updated live
- **Action cards** below — **Manage Doctors** and **Google Calendar**, click either to open that section

---

### How to Create a Doctor Account

1. Click the **Manage Doctors** card
2. Click the **+ Add Doctor** button (top right)
3. Fill in the form:

| Field | Example |
|---|---|
| Doctor's Full Name | Dr. Priya Sharma |
| Email | priya.sharma@clinic.com |
| Specialization | Cardiology |
| Working Hours Start | 09:00 |
| Working Hours End | 17:00 |
| Slot Duration (minutes) | 30 |

4. Click **Create Doctor Profile**

**What happens next:**
A green message appears at the top:
```
Doctor profile created for Dr. Priya Sharma.
Temporary login password: xK9mP2qR7t (share this securely — it won't be shown again)
```

⚠️ **VERY IMPORTANT:**
- This password is shown **ONLY ONCE**
- Copy it immediately and share it with the doctor (WhatsApp, email, etc.)
- If you miss it, you don't need to delete and recreate the doctor anymore —
  the doctor can log in once you reset their credentials, or you can
  edit their email and have them use "Change Password" once logged in
  (see **How to Edit a Doctor's Details** below)
- The doctor should log in and change this password immediately using
  the **Change Password** option in their own dashboard

---

### How to Edit a Doctor's Details

1. Click the **Manage Doctors** card
2. Find the doctor → click **Manage →**
3. On the doctor's detail page, click **Edit Details** (top right, next to their name)
4. Update any of the following:

| Field | Notes |
|---|---|
| Email | Their login email. Must not already belong to another account. |
| Specialization | e.g. Cardiology, Dermatology |
| Working Hours Start / End | Start must be earlier than end |
| Slot Duration (minutes) | How long each appointment slot is |

5. Click **Save Changes**

You'll see a confirmation message:
```
Dr. Priya Sharma's profile has been updated.
```

Note: this does **not** change the doctor's password. Passwords are
only ever changed by the doctor themselves, from their own dashboard.

---

### How to Add a Leave Day for a Doctor

1. Click the **Manage Doctors** card
2. Find the doctor → click **Manage →**
3. You will see the doctor's detail page
4. Under **"Mark a leave day"** section:
   - Pick the date from the calendar picker
   - Add a reason (optional, e.g. "Personal leave")
5. Click **Add Leave Day**

**What happens automatically:**
- If that doctor had any existing bookings on that date → they are **automatically cancelled**
- Each affected patient gets a **notification queued** to inform them
- You will see a message like:
```
Leave day added. 2 existing appointment(s) were cancelled
and queued for patient notification.
```
- If no bookings were affected:
```
Leave day added. No existing appointments were affected.
```

The **Upcoming leave days** table at the bottom of the page will update.

---

### How to Connect Google Calendar (Optional)

1. From Admin Dashboard → click the **Google Calendar** card
2. If not connected, click **Connect Google Calendar →**
3. You will be redirected to Google's login page
4. Sign in with your Google account → click **Allow**
5. You will be redirected back and see:
```
✓ Connected
Google Calendar is connected. New appointments will
automatically create calendar events.
```
From this point, every booking creates a Google Calendar event
and invites both the patient and doctor automatically.

---

## DOCTOR GUIDE

### How to Log In

1. Go to `http://127.0.0.1:5000`
2. Enter the email and temporary password shared by the admin
3. You will land on the **Doctor Dashboard**

The dashboard now shows:
- **Stat cards** at the top — Today's Appointments, Total Upcoming, and Completed Visits
- **Action cards** below — **My Appointments** and **Change Password**

### How to Change Your Password

Since your account was created with a temporary password by the
admin, you should change it the first time you log in:

1. From the Doctor Dashboard, click the **Change Password** card
2. Enter:
   - **Current Password** — the temporary one the admin gave you
   - **New Password** — minimum 8 characters
   - **Confirm New Password** — must match
3. Click **Update Password**

You'll see:
```
Password updated successfully.
```
Use your new password the next time you log in. If you entered the
wrong current password, you'll see an error and can try again — your
password won't change until it succeeds.

---

### What the Doctor Sees

Click the **My Appointments** card. On the appointments list, each
upcoming patient shows:

| Column | What it means |
|---|---|
| Patient | Patient's name |
| Date | Appointment date |
| Time | Appointment time |
| Urgency | AI-generated: Low / Medium / High |
| Chief Complaint | AI one-line summary of symptoms |

Click **View →** to open the full appointment detail.

---

### What the Doctor Sees on the Detail Page

**Pre-Visit Summary (generated by AI):**
```
🔴 High urgency

Chief complaint: Severe chest pain radiating to left arm

Suggested questions:
  1. When did the pain start exactly?
  2. Any shortness of breath or sweating?
  3. Family history of heart disease?

Patient-reported symptoms:
  "I have had sharp chest pain since this morning..."
```

If AI was unavailable, the doctor sees the raw symptoms the
patient typed — the appointment is never blocked by AI failure.

---

### How to Complete a Visit

After seeing the patient, scroll down to **"Complete This Visit"**:

1. Fill in **Clinical Notes** (what you found, diagnosis)
   ```
   Example: ECG normal. Likely musculoskeletal chest pain.
   No cardiac involvement detected.
   ```

2. Fill in **Prescription** (medication, dosage, frequency, duration)
   ```
   Example: Ibuprofen 400mg, twice daily, after meals, for 5 days
   ```

3. Click **Complete Visit & Generate Summary**

**What happens automatically:**
- Visit is marked as completed
- AI generates a patient-friendly summary from your notes
- Patient receives an email: "Your visit summary is ready"
- Medication reminders will be sent to the patient based on frequency

---

## PATIENT GUIDE

### How to Create an Account

1. Go to `http://127.0.0.1:5000`
2. Click **"New patient? Create an account"** link on the login page
3. Fill in the form:

| Field | Example |
|---|---|
| Full Name | Riya Shah |
| Email | riya.shah@gmail.com |
| Password | (min 8 characters) |
| Confirm Password | (same as above) |

4. Click **Register**
5. You will see:
```
Account created successfully! Please log in.
```
6. Log in with your email and password

---

### Your Dashboard

After logging in, you'll land on the **Patient Dashboard**, which now shows:

- A **highlighted card** for your next upcoming appointment (if you have one), with the doctor's name, specialization, date, and time
- **Stat cards** — Upcoming Appointments and Completed Visits
- **Action cards** — **Find a Doctor & Book** and **My Appointments**

---

### How to Book an Appointment

**Step 1 — Find a doctor**
1. From Patient Dashboard → click the **Find a Doctor & Book** card
2. You will see a list of all available doctors
3. Use the **Filter by specialization** dropdown to narrow down
   (e.g. Cardiology, Dermatology)
4. Click **View Slots →** next to the doctor you want

**Step 2 — Pick a date and time**
1. Use the **← Prev day / Next day →** arrows to browse dates
2. Available time slots appear as buttons:
   ```
   [ 09:00 AM ]  [ 09:30 AM ]  [ 10:00 AM ]  [ 10:30 AM ]
   ```
3. Click any slot to hold it

**Step 3 — Fill in your symptoms**
After clicking a slot, you have **5 minutes** to fill the symptom form.
A countdown timer shows how much time you have.

Write how you are feeling:
```
Example: I have had a headache and mild fever for 2 days.
         It gets worse in the evenings. No vomiting.
```
Click **Submit Symptoms**

**What the AI does with your symptoms:**
- Decides urgency level (Low / Medium / High)
- Finds the main complaint
- Suggests 3 questions for the doctor to ask you
- The doctor sees this before meeting you

**Step 4 — Confirm your booking**
Review the appointment details:
```
Doctor:  Dr. Priya Sharma (Cardiology)
Date:    Monday, 14 July 2025
Time:    10:00 AM – 10:30 AM
```
Click **Confirm Appointment**

You will see:
```
Appointment confirmed! A confirmation email has been sent.
```
You will also receive a confirmation email in your inbox.

---

### How to View Your Appointments

From Patient Dashboard → click the **My Appointments** card

You will see a table with all your appointments:

| Status | Meaning |
|---|---|
| 🟢 booked | Confirmed, upcoming |
| 🟡 completed | Visit done |
| 🔴 cancelled | Cancelled |

For **completed** appointments → click **View Summary →** to read
the AI-generated patient-friendly summary of your visit including
your medication schedule and follow-up steps.

---

### How to Cancel an Appointment

1. Go to the **My Appointments** card
2. Find the appointment with status **booked**
3. Click the red **Cancel** button
4. A confirmation popup appears: "Cancel this appointment?"
5. Click OK
6. You will see:
```
Appointment cancelled.
```
A cancellation email will be sent to you automatically.

---

### Medication Reminders

After a completed visit with a prescription, you will automatically
receive reminder emails based on the prescription frequency:

| Prescription says | You get reminders at |
|---|---|
| Once daily | 8:00 AM every day |
| Twice daily | 8:00 AM and 8:00 PM every day |
| Three times daily | 8:00 AM, 2:00 PM, and 8:00 PM every day |

Reminders stop automatically after the prescription duration ends
(e.g. "for 5 days" → reminders stop after 5 days).

---

## QUICK REFERENCE — WHO CAN DO WHAT

| Action | Patient | Doctor | Admin |
|---|---|---|---|
| Register account | ✅ Self | ❌ Admin creates | ❌ Terminal only |
| Log in | ✅ | ✅ | ✅ |
| Change own password | ❌ | ✅ | ❌ |
| Search doctors | ✅ | ❌ | ❌ |
| Book appointment | ✅ | ❌ | ❌ |
| Fill symptom form | ✅ | ❌ | ❌ |
| Cancel appointment | ✅ | ❌ | ❌ |
| View visit summary | ✅ | ❌ | ❌ |
| View patients | ❌ | ✅ (own only) | ❌ |
| Complete visit | ❌ | ✅ | ❌ |
| Create doctor accounts | ❌ | ❌ | ✅ |
| Edit doctor details | ❌ | ❌ | ✅ |
| Add leave days | ❌ | ❌ | ✅ |
| Connect Google Calendar | ❌ | ❌ | ✅ |

---

## COMMON QUESTIONS

**Q: I missed the doctor's temporary password. What do I do?**
Go to **Manage Doctors → Manage → Edit Details** and confirm the
doctor's email is correct, then have them try logging in. If they've
genuinely lost the password and never logged in to change it, ask a
developer to reset it manually in the database — there is currently
no "forgot password" flow for doctor accounts, only a "change
password" flow for doctors who are already logged in.

**Q: The AI summary says "unavailable". Is something broken?**
No. This means the GEMINI_API_KEY is not set in the .env file,
or the Gemini API had a temporary issue. The appointment still
works perfectly — the doctor sees the raw symptoms instead.

**Q: I didn't receive the confirmation email.**
Check your spam folder first. If still missing, the email failed —
the system retries automatically every 30 minutes.

**Q: Can a patient book the same slot as another patient?**
No. The system prevents this at the database level. If two patients
try to book the same slot at the same time, one will succeed and
the other will see: "Someone just booked that slot — please choose another."

**Q: What happens if I leave the symptom form without submitting?**
Your slot hold expires after 5 minutes and the slot becomes
available for other patients to book.
