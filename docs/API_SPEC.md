# API Specification — SahyogCare

## Conventions

- Base path: `/api/v1`
- JSON request/response bodies.
- Protected endpoints require `Authorization: Bearer <token>`.
- IDs are UUIDs.
- Timestamps are ISO-8601 UTC.
- Mutating offline-capable requests accept `Idempotency-Key`.
- Application roles are exactly: `WORKER`, `FACILITY_STAFF`, `DOCTOR`, `COORDINATOR`.
- `Authorised` means the API also checks the user's facility scope and resource access, not only the role.
- Patients have no account; they use the public lookup below.
- The workflow and business rules behind these endpoints are in `WORKFLOW.md`.

## Health

| Method | Route | Role | Purpose |
|---|---|---|---|
| GET | `/health` | Public | Service and database check |

## Auth

| Method | Route | Role | Purpose |
|---|---|---|---|
| POST | `/auth/otp/request` | Public | Send a one-time code to a pre-registered email |
| POST | `/auth/otp/verify` | Public | Exchange email + code for access and refresh tokens |
| POST | `/auth/refresh` | Public (needs refresh token in body) | `{"refresh_token": "..."}` → new access and refresh tokens |
| GET | `/me` | Authenticated | Current user and role |

## Patients

| Method | Route | Role | Purpose |
|---|---|---|---|
| POST | `/patients` | WORKER | Create patient (consent required; warns on likely duplicate) |
| GET | `/patients?q=` | Authenticated | Search patients within authorised scope |
| GET | `/patients/{patient_id}` | WORKER / FACILITY_STAFF / DOCTOR / COORDINATOR | Patient summary within authorised scope |
| POST | `/patients/{patient_id}/encounters` | WORKER | Create encounter (reason, triage, optional vitals and medicines) |
| GET | `/patients/{patient_id}/encounters` | WORKER / FACILITY_STAFF / DOCTOR / COORDINATOR | Encounter history within authorised scope |

### Create patient

`POST /api/v1/patients`

```json
{
  "name": "Savitri",
  "age": 42,
  "sex": "F",
  "phone": "9876543210",
  "consent_given": true
}
```

Response: `201 Created`, with `possible_duplicate_of` set when this ASHA already has a patient with the same name and phone.

### Create encounter

`POST /api/v1/patients/{patient_id}/encounters`

```json
{
  "reason": "Fever for 4 days",
  "triage": "PRIORITY",
  "vitals": {"systolic": 118, "diastolic": 76, "spo2": 97},
  "medicines": [{"name": "Paracetamol", "dose": "500 mg", "frequency": "Thrice a day"}]
}
```

Vitals outside plausible ranges return `VALIDATION_ERROR` with the fields. The response may include `triage_suggestion` (a hint only; the ASHA decides).

## Facilities

| Method | Route | Role | Purpose |
|---|---|---|---|
| GET | `/facilities` | WORKER / FACILITY_STAFF / DOCTOR / COORDINATOR | Search facilities |
| GET | `/facilities/{facility_id}` | WORKER / FACILITY_STAFF / DOCTOR / COORDINATOR | Facility details |
| GET | `/facilities/{facility_id}/services` | WORKER / FACILITY_STAFF / DOCTOR / COORDINATOR | Listed services |

Query example:

`GET /facilities?service=CBC&district=Satara`

Availability responses must include `updated_at`.

## Referrals

| Method | Route | Role | Purpose |
|---|---|---|---|
| POST | `/referrals` | WORKER | Create referral |
| GET | `/referrals/{referral_id}` | WORKER / FACILITY_STAFF / DOCTOR / COORDINATOR | Referral detail within authorised scope |
| GET | `/referrals?open=true&status=&triage=` | WORKER / FACILITY_STAFF / DOCTOR / COORDINATOR | Referral queue within authorised scope, most urgent first |
| POST | `/referrals/{referral_id}/accept` | FACILITY_STAFF | Accept incoming referral |
| POST | `/referrals/{referral_id}/reject` | FACILITY_STAFF | Reject with reason |
| POST | `/referrals/{referral_id}/arrival` | FACILITY_STAFF | Record patient arrival |
| POST | `/referrals/{referral_id}/consultation` | DOCTOR | Record consultation |
| POST | `/referrals/{referral_id}/outcome` | DOCTOR | Record outcome `{"note": "...", "follow_up_days": 7}`; the server then creates the ASHA's follow-up and moves the referral to `FOLLOW_UP_DUE` |
| POST | `/referrals/{referral_id}/close` | WORKER / DOCTOR / FACILITY_STAFF / COORDINATOR | Close completed case |
| GET | `/referrals/{referral_id}/pass` | WORKER | Signed QR referral pass |
| POST | `/referral-passes/verify` | FACILITY_STAFF | Scan a pass; records arrival (offline scans sync with their scan time) |
| GET | `/referral-rejection-reasons` | Authenticated | Fixed list of rejection reasons |

`POST /referrals/{id}/reject` takes `{"reason": "SERVICE_UNAVAILABLE", "note": "..."}`. Reasons `SERVICE_UNAVAILABLE` and `NO_DOCTOR_AVAILABLE` mark the requested service unavailable at that facility.

## Public patient lookup

| Method | Route | Role | Purpose |
|---|---|---|---|
| POST | `/public/referral-status` | Public, rate-limited | `{"code": "SC-7K3M9Q", "phone_last4": "4821"}` → status timeline, facility name, checklist |

Never returns vitals, symptoms or other patients' data. Both values must match.

### Create referral

`POST /api/v1/referrals`

```json
{
  "patient_id": "uuid",
  "encounter_id": "uuid",
  "destination_facility_id": "uuid",
  "requested_service": "Diagnostics"
}
```

Reason and triage come from the encounter. Send an `Idempotency-Key` header so a retry returns the first referral instead of creating another. Errors: `SERVICE_NOT_LISTED`, `DUPLICATE_REFERRAL` (an open referral to the same facility already exists).

Response:

```json
{
  "id": "uuid",
  "status": "CREATED",
  "referral_code": "SC-10492"
}
```

## Follow-ups

| Method | Route | Role | Purpose |
|---|---|---|---|
| GET | `/follow-ups?pending=true` | WORKER / COORDINATOR | Own follow-ups (WORKER) or the district's (COORDINATOR), earliest due first; `is_late` flags missed due dates |
| POST | `/follow-ups/{id}/complete` | WORKER / COORDINATOR | Visit done: closes the referral (late visits count too) |
| POST | `/follow-ups/{id}/miss` | WORKER | Visit could not happen: referral becomes `OVERDUE` |
| POST | `/referrals/{id}/escalate` | COORDINATOR | Take over an overdue follow-up (`ESCALATED`) |

## Watchdog

Runs by itself every 5 minutes (turn off with `SAHYOG_WATCHDOG_ENABLED=false`). Alerts are sent once per referral per kind.

| Method | Route | Role | Purpose |
|---|---|---|---|
| POST | `/watchdog/run` | COORDINATOR | Run it now; returns how many alerts or changes it made |

Alert kinds in `/notifications`: `WATCH_NOT_ACCEPTED`, `WATCH_NOT_ARRIVED`, `WATCH_FOLLOW_UP_OVERDUE`, plus `STATUS_<status>` for every status change made by someone else.

## Sync

| Method | Route | Role | Purpose |
|---|---|---|---|
| POST | `/sync/batch` | WORKER / FACILITY_STAFF / DOCTOR / COORDINATOR | Upload queued operations |
| GET | `/sync/changes?since=<cursor>` | WORKER / FACILITY_STAFF / DOCTOR / COORDINATOR | Referrals in scope and own alerts changed since the last `cursor` |

Operation types: `CREATE_PATIENT`, `CREATE_ENCOUNTER`, `CREATE_REFERRAL`, `SCAN_PASS`, `ACCEPT`, `REJECT`, `ARRIVAL`, `CONSULTATION`, `OUTCOME`, `CLOSE`, `ESCALATE`, `COMPLETE_FOLLOW_UP`, `MISS_FOLLOW_UP`. Each runs through exactly the same rules as its normal endpoint. Payloads are the normal request bodies plus `patient_id`, `referral_id` or `follow_up_id` where the endpoint has one in its path.

Example batch (a patient, visit and referral created offline; `$ref:<key>` means "the id created by that earlier action"):

```json
{
  "operations": [
    {"idempotency_key": "phone7-p1", "type": "CREATE_PATIENT",
     "payload": {"name": "Savitri", "age": 42, "phone": "9876543210", "consent_given": true}},
    {"idempotency_key": "phone7-e1", "type": "CREATE_ENCOUNTER",
     "payload": {"patient_id": "$ref:phone7-p1", "reason": "Chest pain", "triage": "EMERGENCY"}},
    {"idempotency_key": "phone7-r1", "type": "CREATE_REFERRAL",
     "payload": {"patient_id": "$ref:phone7-p1", "encounter_id": "$ref:phone7-e1",
                 "destination_facility_id": "uuid", "requested_service": "Emergency"}}
  ]
}
```

Response: one result per operation, in order: `{"idempotency_key", "status": "ok" | "error", "replayed", "result", "error"}`. One failure does not stop the others. Re-sending an operation that already succeeded returns the first result with `"replayed": true`. A status change that no longer fits (e.g. the referral was rejected while the phone was offline) returns `SYNC_CONFLICT` with `current_status`.

## Dashboard

| Method | Route | Role | Purpose |
|---|---|---|---|
| GET | `/dashboard/summary` | Authenticated | Counts within the user's scope: open (by triage), awaiting acceptance, follow-ups due, overdue, closed this month, unread alerts. COORDINATOR also gets per-facility performance (received, accepted, rejected, waiting, average hours to accept, rejection rate), most stuck first |
| GET | `/me/activity-summary?month=2026-10` | WORKER | Referrals created, completed, rejected; follow-ups completed; open now |

## Notifications

| Method | Route | Role | Purpose |
|---|---|---|---|
| GET | `/notifications` | Authenticated | Own alerts (status changes, watchdog alerts) |
| POST | `/notifications/{id}/read` | Authenticated | Mark as read |

## Standard Error Shape

All errors use:

```json
{
  "error": {
    "code": "VALIDATION_ERROR",
    "message": "Requested service is required",
    "details": {
      "field": "requested_service"
    },
    "request_id": "uuid"
  }
}
```

Common codes:

`AUTH_REQUIRED`, `FORBIDDEN`, `NOT_FOUND`, `VALIDATION_ERROR`, `INVALID_STATE_TRANSITION`, `DUPLICATE_OPERATION`, `SYNC_CONFLICT`, `RATE_LIMITED`, `INTERNAL_ERROR`.

## Auth Strategy

JWT access token + refresh token for the prototype. Every protected resource performs role and facility-scope checks. The production version should replace prototype auth assumptions with the chosen deployment's approved identity and security controls.
