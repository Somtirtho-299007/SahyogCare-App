# Workflow & Backend Logic — SahyogCare

This document is the agreed plan for the Samurai (full-stack) milestone. It reconciles the original Ronin plan (`ARCHITECTURE.md`, `API_SPEC.md`) with the frontend built in Kenshi and with desk research on rural referral care in India.

## 1. Positioning

Government systems such as the CPHC NCD application already track referrals between ANM, PHC Medical Officer and higher facilities, but the ASHA who started the journey is left outside that loop and still works from paper registers. Research in rural Rajasthan found that ASHAs often do not know which patients missed their referral.

**SahyogCare closes the loop for the ASHA:** every referral comes back to her with an answer, and any referral that goes silent is flagged.

SahyogCare coordinates existing workflows. It does not diagnose, replace hospital systems, or compete with eSanjeevani (it links to it).

## 2. Roles

| Application role | Shown in the app as | Can do |
|---|---|---|
| `WORKER` | ASHA / ANM | Create patients, encounters and referrals; see only her own; complete follow-ups |
| `FACILITY_STAFF` | Medical Team | Accept / reject, record arrival, scan referral passes, close |
| `DOCTOR` | Medical Team | Record consultation and outcome, close |
| `COORDINATOR` | (later screen) | District totals, escalate overdue follow-ups, bottleneck view |

Patients have **no account**. They view one referral with the referral code plus the last 4 digits of their phone number.

Staff accounts are created in advance. Nobody can self-register as Medical Team.

## 3. End-to-end workflow

```text
ASHA logs in (email OTP)
  → Create patient (or find existing)            consent recorded
  → Encounter: reason, triage, vitals (optional)
  → Search facility by service                   unavailable services flagged
  → Create referral → code (SC-7K3M9Q) + signed QR referral pass
        │
FACILITY_STAFF:  Accept ── or ── Reject (reason from fixed list)
                    │                 └→ service marked unavailable; ASHA picks another facility
  → Patient arrives: scan pass (works offline) or record Arrival
DOCTOR:  Consultation → Outcome (+ follow-up after N days)
  → Server creates follow-up task for the ASHA → FOLLOW_UP_DUE
ASHA:  follow-up Complete → CLOSED
       Missed / deadline passed → OVERDUE → COORDINATOR escalates → CLOSED

Watchdog: any referral that goes silent alerts the ASHA, then the Coordinator.
Patient: code + last 4 phone digits → own referral status.
```

## 4. Referral state machine

| From | To | Who |
|---|---|---|
| `CREATED` | `ACCEPTED`, `REJECTED` | FACILITY_STAFF |
| `ACCEPTED` | `ARRIVAL_RECORDED` | FACILITY_STAFF |
| `ARRIVAL_RECORDED` | `CONSULTED` | DOCTOR |
| `CONSULTED` | `OUTCOME_RECORDED` | DOCTOR |
| `OUTCOME_RECORDED` | `FOLLOW_UP_DUE` | System |
| `FOLLOW_UP_DUE` | `CLOSED` | WORKER, DOCTOR, FACILITY_STAFF, COORDINATOR |
| `FOLLOW_UP_DUE` | `OVERDUE` | System (due date passed), WORKER (visit missed) |
| `OVERDUE` | `CLOSED` | WORKER, COORDINATOR (a late visit still completes) |
| `OVERDUE` | `ESCALATED` | COORDINATOR |
| `ESCALATED` | `CLOSED` | COORDINATOR |

- Any other transition returns `INVALID_STATE_TRANSITION`.
- `REJECTED` requires a reason from the fixed list.
- A status change and its `referral_event` row are written in one database transaction.
- "Open" always means: not `CLOSED` and not `REJECTED`. Every dashboard count uses this one definition.

## 5. Backend logic

### Login

The start screen asks one thing: **who are you?** Three big doors:

| Door | Who | How they get in |
|---|---|---|
| Patient | Anyone | Straight in. Health ID or referral code + last 4 digits of the phone; no account. |
| Health worker | ASHA, hospital staff, doctor | Email (or mobile, when SMS is on) → 6-digit code → **personal code** |
| District office | Coordinators | Same as health worker; the first time, the area's office passphrase instead of a request |

**First time (health worker):** sign in with the emailed code → fill one short form
(name, role, area, hospital for staff/doctors, selfie, optional ID note) → "Request sent"
→ the page checks every 30 seconds → the district office approves → the person's
**personal code** appears on their screen once ("write it down") → their dashboard.

**First time (district office):** sign in with the emailed code → name, area, office
passphrase → in at once, and their own personal code is shown.

**Every later sign-in:** email/SMS code → personal code → dashboard. An email that is
already verified and approved never sees the request form again; only the code is asked.

**Personal codes** (`backend/app/staffcode.py`):
- One per approved person (ASHA, staff, doctor, coordinator), 8 characters shown as `XXXX-XXXX`, from an alphabet without look-alikes; unique across everyone.
- Stored only as a keyed hash (HMAC-SHA256 with the server secret) with a unique index, so no two people can share one and nobody can read it from the database.
- Shown in plain text once, on approval or after a reset; it is forgotten as soon as the person taps "I have written it down".
- Permanent: it does not expire. Only the district office can replace it (People → Reset code), and the new one is shown at that person's next sign-in.
- Wrong codes: 5 tries per 10 minutes per person, each wrong try is audited. Typing someone else's code fails, because the code is checked against the account that just proved its email.
- The step between the email code and the personal code is a 10-minute "code-step" token; it opens nothing else.

**Email/SMS code:** 6 digits, stored hashed, expires after 5 minutes, locked after 5 wrong tries, 60 seconds before a resend. Requests per IP per minute: 30 by default (many phones share one school Wi-Fi on a test day); `SAHYOG_LOGIN_CODES_PER_MINUTE` changes it.

**Tokens:** access token 15 minutes, refresh token 7 days.

**No group invite codes.** Everybody joins by request and approval, or (offices only) by the area passphrase.

### People (district office)
- The People list shows everyone approved in the district, whether they have a personal code, and two buttons: **Reset code** and **Switch off / on**.
- Switching someone off ends their sign-ins; their records stay.

### Two people acting at once
- Moving a referral (accept, reject, arrival, consultation, outcome, close, escalate, re-route, ambulance steps) locks that referral's row first, so two staff tapping Accept together get one success and one "already moved" answer.
- The last bed in a ward is booked under a lock on that ward: two ASHAs, one bed, one booking.
- Tests for both run on PostgreSQL (`backend/tests/test_concurrency.py`).

### Access control
Every request checks the role **and** the scope:
- WORKER: only records she created.
- FACILITY_STAFF / DOCTOR: only referrals whose destination is their facility.
- COORDINATOR: records in their district.

### Patients and encounters
- Required for a referral: name, age (0–120), phone (10 digits), reason, triage. Vitals are optional.
- Same name + phone already present → warning, not a block.
- Vitals outside plausible ranges are rejected as typing errors (ranges in `backend/app/rules.py`).
- Readings are never overwritten; each visit is a new encounter.
- Consent: the ASHA confirms the patient agreed; the time is stored on the patient.

### Triage
The ASHA decides. The server may suggest using explicit rules (e.g. SpO₂ < 90 → "consider Emergency"). No AI diagnosis.

### Creating a referral
- One open referral per patient per destination facility.
- Code: `SC-` + 6 characters from an alphabet without 0/O/1/I; unique.
- Every create carries an `Idempotency-Key`; a repeat returns the first result.
- The receiving facility sees reason, triage and vitals before arrival.

### Time rules (watchdog)
| Silence | Threshold | Alert |
|---|---|---|
| Not accepted | Emergency 1 h, Priority 6 h, Routine 48 h | ASHA; Coordinator at 2× |
| Accepted but no arrival | Emergency 6 h, Priority 24 h, Routine 72 h | ASHA ("not arrived yet") |
| Follow-up past due | due date | Mark `OVERDUE`; Coordinator |

Alerts are deduplicated: one alert per referral per kind.

### Patient lookup
- Code and last 4 phone digits must both match.
- More than 5 attempts per minute from one IP are blocked.
- Returns status timeline, facility name and checklist only; never vitals or symptoms.

### Audit and privacy
- Every write logs actor, action, target and time.
- Logs carry IDs only, never names or phone numbers.
- The DPDP Rules' core obligations apply from 13 May 2027; the design anticipates consent records, retention limits, encryption and breach handling.
- Prototype uses fake data only.

### Offline and low bandwidth
- Small responses; slow networks are the default assumption.
- Offline actions queue on the device and sync later; idempotency keys stop duplicates.
- If the server state changed meanwhile, the server returns `SYNC_CONFLICT` with the current state.

## 6. Signature features

### 6.1 Offline referral pass
The patient receives a QR pass containing the referral code, destination, triage and a server signature. The facility scans it at the desk; arrival is recorded even without network and synced later. The signature prevents forged passes.

### 6.2 Referral watchdog
A scheduled job treats *nothing happening* as a signal (see time rules above) and walks an escalation ladder: ASHA alert → facility phone shown → Coordinator alert.

### 6.3 Learning from rejections
Rejection reasons come from a fixed list. Reasons such as "service unavailable" or "no doctor available" immediately mark that service unavailable at that facility (with a timestamp), so the next ASHA searching is warned and pointed elsewhere. Availability older than 24 hours is shown as stale.

### 6.4 ASHA monthly activity summary
Referrals made, completed and follow-ups done per month — a record of her work she can show her ANM. It is not an official incentive claim.

### Roadmap (not in Samurai)
Voice input for symptoms in Bengali; missed-call → SMS status for patients; Coordinator bottleneck map; ABDM integration (ABHA number and HFR ID fields exist already).

## 7. Database tables

`users`, `facilities`, `facility_services`, `patients`, `encounters`, `medicines`, `referrals`, `referral_events`, `follow_ups`, `notifications`, `otp_codes`, `idempotency_keys`, `audit_log`.

## 8. Build order

1. **Foundation** — FastAPI skeleton, tables, rules, seed data, health check. *(done)*
2. **Login and roles** — OTP, tokens, role checks. *(done; scope checks arrive with each endpoint in step 3)*
3. **Core workflow** — patients, encounters, referrals, state machine, referral pass, patient lookup, notifications. *(done)*
4. **Watchdog, follow-ups, escalation, activity summary, dashboard counts.** *(done)*
5. **Offline sync** — batch upload of queued actions and pulling changes. *(done)*
6. **Connect the frontend** — every screen now uses the API: OTP login, ASHA referrals with QR pass and alerts, medical queue with role-based actions, reject reasons and pass scanning, patient lookup. *(done; offline queueing in the browser is still to do — the backend side is ready)*

## 9. Placeholder values

Vital ranges, the SpO₂ suggestion threshold and all watchdog times are placeholders chosen by the team, not clinical rules. They live in `backend/app/rules.py` and must be reviewed by a doctor or public-health professional before any real use.
