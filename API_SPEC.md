# API Specification — SahyogCare

## Conventions

- Base path: `/api/v1`
- JSON request/response bodies.
- Protected endpoints require `Authorization: Bearer <token>`.
- IDs are UUIDs.
- Timestamps are ISO-8601 UTC.
- Mutating offline-capable requests accept `Idempotency-Key`.

## Auth

| Method | Route | Role | Purpose |
|---|---|---|---|
| POST | `/auth/login` | Public | Authenticate |
| POST | `/auth/refresh` | Authenticated | Refresh access token |
| GET | `/me` | Authenticated | Current user and role |

## Patients

| Method | Route | Role | Purpose |
|---|---|---|---|
| POST | `/patients` | WORKER+ | Create patient |
| GET | `/patients/{patient_id}` | Authorised | Patient summary |
| POST | `/patients/{patient_id}/encounters` | WORKER+ | Create encounter |
| GET | `/patients/{patient_id}/encounters` | Authorised | Encounter history |

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
| GET | `/facilities` | Authenticated | Search facilities |
| GET | `/facilities/{facility_id}` | Authenticated | Facility details |
| GET | `/facilities/{facility_id}/services` | Authenticated | Listed services |

Query example:

`GET /facilities?service=CBC&district=Satara`

Availability responses must include `updated_at`.

## Referrals

| Method | Route | Role | Purpose |
|---|---|---|---|
| POST | `/referrals` | WORKER+ | Create referral |
| GET | `/referrals/{referral_id}` | Authorised | Referral detail |
| GET | `/referrals` | Authorised | Filter referral queue |
| POST | `/referrals/{referral_id}/accept` | RECEIVING FACILITY | Accept |
| POST | `/referrals/{referral_id}/reject` | RECEIVING FACILITY | Reject with reason |
| POST | `/referrals/{referral_id}/arrival` | RECEIVING FACILITY | Record arrival |
| POST | `/referrals/{referral_id}/consultation` | DOCTOR/FACILITY | Record consultation |
| POST | `/referrals/{referral_id}/outcome` | DOCTOR/FACILITY | Record outcome |
| POST | `/referrals/{referral_id}/close` | Authorised | Close case |

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
| GET | `/follow-ups` | WORKER/COORDINATOR | Queue |
| POST | `/follow-ups/{id}/complete` | Assigned/authorised | Complete |
| POST | `/follow-ups/{id}/miss` | Assigned/authorised | Mark missed |
| POST | `/follow-ups/{id}/escalate` | COORDINATOR | Escalate |

## Sync

| Method | Route | Role | Purpose |
|---|---|---|---|
| POST | `/sync/batch` | Authenticated | Upload queued operations |
| GET | `/sync/changes?cursor=...` | Authenticated | Pull changes |

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
| GET | `/dashboard/facility` | FACILITY/DOCTOR | Referral queue |
| GET | `/dashboard/coordinator` | COORDINATOR | Aggregate metrics |

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
