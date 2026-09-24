# Requirements — SahyogCare

## Functional Requirements

### Patient & Encounter
- FR-01: The system shall allow an authorised worker to create a patient record.
- FR-02: The system shall allow an authorised worker to create an encounter for a patient.
- FR-03: The system shall show only fields required for the current workflow.
- FR-04: The system shall show relevant previous encounters to authorised users.

### Referral
- FR-05: The system shall allow an authorised worker to create a referral.
- FR-06: Every referral shall receive a unique identifier.
- FR-07: A referral shall contain source facility, destination facility, requested service, reason and priority.
- FR-08: The system shall record referral status changes as timestamped events.
- FR-09: Receiving staff shall be able to accept or reject an incoming referral.
- FR-10: Authorised facility staff shall be able to record arrival, consultation and outcome.
- FR-11: The system shall prevent invalid referral state transitions.
- FR-12: The system shall show the current referral state and last recorded action.

### Facility & Service
- FR-13: Users shall be able to search facilities by service.
- FR-14: Facility service records shall include a freshness/update timestamp.
- FR-15: The system shall distinguish listed availability from confirmed real-time availability.

### Follow-up
- FR-16: An authorised user shall be able to create a follow-up task.
- FR-17: Each follow-up shall have a due date and responsible user/role.
- FR-18: Users shall be able to mark follow-up complete or missed.
- FR-19: Missed/overdue follow-ups shall appear in the relevant queue.
- FR-20: Authorised coordinators shall be able to escalate overdue cases.

### Offline
- FR-21: Core screens shall remain usable when connectivity is unavailable.
- FR-22: Offline-created operations shall be stored locally until sync.
- FR-23: The client shall show pending, syncing, synced and failed states.
- FR-24: Synchronisation shall be idempotent.
- FR-25: Sync conflicts shall be surfaced rather than silently overwritten.

### Dashboards
- FR-26: Workers shall see assigned patients, referrals and follow-ups.
- FR-27: Receiving facilities shall see incoming referrals requiring action.
- FR-28: Coordinators shall see aggregate referral and follow-up counts.
- FR-29: Dashboard views shall respect role and facility scope.

### Audit
- FR-30: Sensitive workflow actions shall create audit events.
- FR-31: Audit events shall identify actor, action, target and timestamp.

## Non-Functional Requirements

### Performance
- NFR-01: Core screens should render from local cache without network dependency after first load.
- NFR-02: Online API requests should target a p95 response time under 500 ms for simple reads in the prototype environment.
- NFR-03: Referral creation should require no more than one primary submission action.

### Reliability
- NFR-04: Offline writes must not be silently discarded.
- NFR-05: Duplicate sync operations must not create duplicate referrals.
- NFR-06: Failed sync attempts must be retryable.

### Security & Privacy
- NFR-07: Protected endpoints require authentication.
- NFR-08: Every protected endpoint performs authorisation checks.
- NFR-09: Sensitive traffic uses HTTPS in deployed environments.
- NFR-10: Secrets must not be committed to the repository.
- NFR-11: Logs must not contain unnecessary patient-identifying information.
- NFR-12: Production use requires a formal privacy/security review before handling real patient data.

### Accessibility & Usability
- NFR-13: Primary workflows should be usable on small mobile screens.
- NFR-14: Touch targets should be comfortable for frontline use.
- NFR-15: Status should not rely on colour alone.
- NFR-16: Core actions should use plain, localisable language.
- NFR-17: Critical states should be understandable without technical terminology.

## Assumptions

- Users have Android-capable phones or equivalent browsers.
- Connectivity may be intermittent.
- Facility/service availability data may be delayed.
- The prototype can use seeded facility and patient data.
- Clinical protocols and escalation rules are supplied by qualified stakeholders before any real deployment.

## Constraints

- Level 1 does not require production deployment.
- The project must remain small enough to evolve through Kenshi → Samurai → Shogun.
- The system must not claim live government-system integration unless an actual integration exists.
- AI must not make autonomous clinical decisions.
- Real patient data must not be used in the prototype without appropriate approvals and safeguards.

## Explicitly Not Required for Level 1

- Production authentication provider integration.
- Live government APIs.
- Real-time hospital inventory.
- Clinical-grade decision support.
- Full hospital EMR.
- Payments.
- Ambulance logistics.
