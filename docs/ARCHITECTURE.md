# Architecture — SahyogCare

## 1. System Shape

SahyogCare is a mobile-first PWA with an offline-capable client, a REST API, and a relational database.

```text
┌──────────────────────────────┐
│ ASHA / ANM / Facility PWA    │
│ React + TypeScript            │
│ IndexedDB + Service Worker    │
└──────────────┬───────────────┘
               │ HTTPS / JSON
               ▼
┌──────────────────────────────┐
│ FastAPI                       │
│ Auth + RBAC                   │
│ Referral workflow             │
│ Sync / conflict handling      │
│ Audit events                  │
└──────────────┬───────────────┘
               │ SQL
               ▼
┌──────────────────────────────┐
│ PostgreSQL                    │
│ Patients / Encounters         │
│ Referrals / Facilities        │
│ Follow-ups / Events           │
└──────────────┬───────────────┘
               │
      ┌────────┴─────────┐
      ▼                  ▼
 Facility/service     Optional external
 availability         public-health integrations
```

## 2. Major Components

### Client — React + TypeScript PWA
Chosen for a responsive mobile workflow and a single frontend codebase. The service worker caches the application shell and IndexedDB stores queued writes.

### API — FastAPI
Chosen for explicit typed request/response models, straightforward REST endpoints and validation.

### Database — PostgreSQL
Chosen because the domain has strong relationships: one patient can have many encounters; an encounter can create referrals; referrals have state transitions and events; follow-ups belong to referrals/cases.

### Authentication — JWT + RBAC
Chosen for a simple authenticated MVP with clear role and facility boundaries. The four application roles are exactly: `WORKER`, `FACILITY_STAFF`, `DOCTOR`, and `COORDINATOR`.

### Offline Sync
Writes made offline receive a client-generated idempotency key and local status. On reconnect, the client submits the queued operation. The server returns the canonical record and sync state.

### Hosting — Vercel (frontend) + Render (API) + managed PostgreSQL
Chosen for a low-ops prototype deployment: the frontend can deploy as a PWA, the FastAPI service can run as a managed web service, and PostgreSQL remains a managed relational database rather than a server the team operates manually.

## 3. Data Flow

### Online request

```text
Browser
  → JWT
  → POST /referrals
  → FastAPI validates role + payload
  → PostgreSQL transaction
  → referral_event appended
  → JSON response
  → UI updates
```

### Offline request

```text
User action
  → IndexedDB queue
  → "Pending sync" UI
  → Connectivity returns
  → sync endpoint
  → idempotency check
  → server transaction
  → canonical record
  → local record marked synced
```

## 4. Core Entities

```text
User
 └── belongs to Facility

Patient
 └── has many Encounters

Encounter
 └── may create Referral

Referral
 ├── source Facility
 ├── destination Facility
 ├── requested Service
 ├── many ReferralEvents
 └── may create FollowUp tasks

Facility
 └── has many Services

FollowUp
 └── assigned to User
```

## 5. Referral State Machine

```text
CREATED
   │
   ├── rejected → REJECTED
   │
   ▼
ACCEPTED
   │
   ▼
ARRIVAL_RECORDED
   │
   ▼
CONSULTED
   │
   ├── service pending → PENDING
   │
   ▼
OUTCOME_RECORDED
   │
   ▼
FOLLOW_UP_DUE
   │
   ├── missed → OVERDUE → ESCALATED
   │
   ▼
CLOSED
```

Role permissions for these transitions are defined in `API_SPEC.md` and use the same four application roles listed above.

## 6. Security Boundaries

- HTTPS in transit.
- Passwords never stored directly; use a password hashing algorithm if local credentials are used.
- JWT access tokens with short expiry.
- Role and facility checks on every protected endpoint.
- Audit event for sensitive workflow actions.
- Minimum necessary patient fields.
- No patient information in analytics URLs or client logs.
- Production deployment must add appropriate secrets management, backups, monitoring and privacy/compliance review before real patient use.

## 7. Integration Boundary

External government systems are treated as integration boundaries, not dependencies of the MVP.

Potential future adapters:

```text
SahyogCare
   ├── Teleconsultation adapter
   ├── Health-record / interoperability adapter
   └── Program-specific referral adapter
```

The first version stores a clear external-reference field where required rather than pretending to have a live integration.

## 8. Reliability

The system should prefer explicit failure over silent failure.

Examples:
- If facility availability is stale, show `Last updated: ...`.
- If sync fails, show `Sync failed — retry`.
- If a duplicate operation is received, idempotency prevents a second referral.
- If a state transition is invalid, API returns a structured validation error.
