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
| POST | `/patients` | WORKER | Create patient |
| GET | `/patients/{patient_id}` | WORKER / FACILITY_STAFF / DOCTOR / COORDINATOR | Patient summary within authorised scope |
| POST | `/patients/{patient_id}/encounters` | WORKER / DOCTOR | Create encounter |
| GET | `/patients/{patient_id}/encounters` | WORKER / FACILITY_STAFF / DOCTOR / COORDINATOR | Encounter history within authorised scope |

### Create patient

`POST /api/v1/patients`

```json
{
  "local_reference": "ASHA-1042",
  "name": "Savitri",
  "age": 42,
  "sex": "F"
}
```

Response: `201 Created`

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
| GET | `/referrals` | WORKER / FACILITY_STAFF / DOCTOR / COORDINATOR | Filter referral queue within authorised scope |
| POST | `/referrals/{referral_id}/accept` | FACILITY_STAFF | Accept incoming referral |
| POST | `/referrals/{referral_id}/reject` | FACILITY_STAFF | Reject with reason |
| POST | `/referrals/{referral_id}/arrival` | FACILITY_STAFF | Record patient arrival |
| POST | `/referrals/{referral_id}/consultation` | DOCTOR | Record consultation |
| POST | `/referrals/{referral_id}/outcome` | DOCTOR | Record clinical outcome |
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
  "requested_service": "CBC",
  "reason": "Diagnostic assessment",
  "priority": "HIGH",
  "follow_up_days": 7
}
```

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
| GET | `/follow-ups` | WORKER / COORDINATOR | Queue |
| POST | `/follow-ups/{id}/complete` | WORKER / COORDINATOR | Complete assigned follow-up |
| POST | `/follow-ups/{id}/miss` | WORKER / COORDINATOR | Mark assigned follow-up missed |
| POST | `/follow-ups/{id}/escalate` | COORDINATOR | Escalate missed follow-up |

## Sync

| Method | Route | Role | Purpose |
|---|---|---|---|
| POST | `/sync/batch` | WORKER / FACILITY_STAFF / DOCTOR / COORDINATOR | Upload queued operations |
| GET | `/sync/changes?cursor=...` | WORKER / FACILITY_STAFF / DOCTOR / COORDINATOR | Pull authorised changes |

Example batch:

```json
{
  "operations": [
    {
      "idempotency_key": "device-123-op-88",
      "type": "CREATE_REFERRAL",
      "payload": {}
    }
  ]
}
```

## Dashboard

| Method | Route | Role | Purpose |
|---|---|---|---|
| GET | `/dashboard/worker` | WORKER | Assigned workload |
| GET | `/dashboard/facility` | FACILITY_STAFF / DOCTOR | Facility referral queue |
| GET | `/dashboard/coordinator` | COORDINATOR | Aggregate district metrics |
| GET | `/me/activity-summary?month=2026-10` | WORKER | Referrals made, completed, follow-ups done |

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
