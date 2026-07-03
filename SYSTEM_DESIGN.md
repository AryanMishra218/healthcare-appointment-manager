# System Design Write-up
## HealthConnect — Healthcare Appointment & Follow-up Manager

---

### 1. Double-Booking Prevention

The core challenge is a race condition: two patients clicking the same
slot at the same millisecond. A naive code-level check ("if slot is
free, book it") fails here because both requests can pass the check
before either one writes to the database.

**Our solution: a partial unique index at the database level.**

We define a `UNIQUE` constraint on `(doctor_id, appointment_date,
start_time)` in the `appointments` table, but only for rows where
`status != 'cancelled'`. This is called a *partial unique index*.

When two concurrent booking requests arrive:
- The database processes them serially (it locks the row)
- The first request succeeds and commits
- The second request hits the constraint and raises an `IntegrityError`
- Our Flask route catches that error and returns a friendly message:
  "Someone just booked that slot — please choose another"

This means double-booking is physically impossible, regardless of how
many concurrent users hit the system. Code-level checks alone cannot
make this guarantee; only a database constraint can.

We also use a `held` status for slots in-flight (during the symptom
form step), so active holds count against the uniqueness constraint.
This prevents a race between "filling the form" and "booking the slot."

---

### 2. Doctor Leave Conflict Handling

When an admin marks a doctor unavailable on a date that already has
bookings, the system must:

1. **Detect** all affected appointments (status `booked` or `held`)
2. **Auto-cancel** them (freeing those slots for other patients)
3. **Notify** each affected patient

Step 3 is the tricky one, because the email service may not be
available at the moment the admin clicks "Add Leave". We solve this
with a **write-ahead notification queue**.

When the leave is saved, we immediately write a `NotificationLog` row
for each affected patient with `status='pending'`. This write always
succeeds (it's just our own database). A `before_request` hook on the
first incoming request then processes all `pending` rows and attempts
to send the emails.

If sending fails (SendGrid down), the row stays `failed`. A background
job (APScheduler, every 30 minutes) retries failed rows up to 3 times.
After 3 failures, the row is left as `failed` for manual review.

This design ensures:
- The admin action is never blocked by email availability
- No patient notification is silently lost
- Every attempt is auditable in the `notifications_log` table

---

### 3. Slot Hold Mechanism

When a patient selects a slot, they must fill a symptom form before
confirming. During that time, the slot must be unavailable to others,
but must be released if the patient abandons the form.

**Our approach: time-limited `held` status.**

On slot selection, an `Appointment` row is created with:
- `status = 'held'`
- `hold_expires_at = now + 5 minutes`

Because `held` rows are included in the partial unique index, the slot
is invisible to other patients immediately.

We use **lazy expiry** instead of a background timer: every time
`get_available_slots()` is called, it first cancels any holds whose
`hold_expires_at` has passed. This is accurate exactly when it matters
(when someone is looking at available slots) and requires no polling.

If the patient submits the symptom form and confirms within 5 minutes,
status changes to `booked`. If they abandon or exceed the timer, the
hold is cleaned up on the next availability check, and the slot
reappears for other patients.

The frontend also shows a countdown timer (JavaScript), but this is
UX-only — the real enforcement is server-side.

---

### 4. Notification Failure Handling

Every email attempt in the system follows the same four-step pattern:

1. Create a `NotificationLog` row with `status='pending'` (always saved)
2. Attempt to send via SendGrid
3. On success → update to `status='sent'`, record `sent_at`
4. On failure → update to `status='failed'`, record `error_message`

This means the database always reflects the true state of every email
attempt. No failure is ever silent.

A background job (APScheduler, `IntervalTrigger` every 30 minutes)
calls `retry_failed_notifications()`, which:
- Finds all rows where `status='failed'` AND `retry_count < 3`
- Attempts to resend
- Increments `retry_count` on each attempt
- Stops after 3 failures (prevents spam to a bad address)

The LLM integration uses the same philosophy. Symptom text and visit
notes are always saved to the database *before* calling Gemini. If
Gemini fails (timeout, API down, malformed response), the raw data is
preserved and the doctor sees it directly. The system never breaks
because an external AI service is unavailable.

Calendar events follow the same pattern: event creation is attempted
after booking is confirmed and committed. A `None` return from the
calendar service is logged but does not roll back the booking.

**Summary:** every external dependency (SendGrid, Gemini, Google
Calendar) is treated as unreliable by default. The core booking and
visit flow never depends on their availability.
