# Roadmap — SahyogCare

## Milestone 1 — Kenshi / Frontend

**Goal:** prove the workflow visually and interactively before adding backend complexity.

### Ship
1. Mobile-first shell.
2. Worker dashboard.
3. Patient search/create.
4. Encounter form.
5. Triage/priority display using explicit non-diagnostic rules.
6. Facility/service selection.
7. Referral creation.
8. Referral timeline.
9. Follow-up queue.
10. Coordinator summary.
11. Offline-state indicators using mocked/local data.

### Exit criteria
- A seeded patient can complete the entire referral journey in the UI.
- The UI clearly distinguishes `CREATED`, `ACCEPTED`, `ARRIVAL`, `CONSULTED`, `OUTCOME`, `FOLLOW-UP`, `CLOSED`.
- Screens in the sketch map directly to implemented frontend screens.

## Milestone 2 — Samurai / Full Stack

**Goal:** turn the prototype into a persistent multi-user workflow.

### Add
1. FastAPI backend.
2. PostgreSQL schema.
3. JWT authentication.
4. Role-based access control.
5. Patient/encounter persistence.
6. Referral state machine.
7. Referral event/audit log.
8. Facility/service records.
9. Follow-up persistence.
10. Offline queue and sync.
11. Idempotency handling.
12. Structured API errors.

### Validation
- Two test accounts can act as originating and receiving facilities.
- A referral created by one user appears in the authorised receiving queue.
- Invalid state transitions are rejected.
- Offline-created referrals sync exactly once.

## Milestone 3 — Shogun / Production Readiness

**Goal:** validate that the workflow can operate with real users and appropriate safeguards.

### Add
1. Production identity/security review.
2. Encryption and secrets management.
3. Backups and recovery.
4. Monitoring and audit review.
5. Accessibility/local-language validation.
6. Facility-data freshness rules.
7. Integration adapters where formally available.
8. Pilot onboarding and training.
9. User feedback loop.
10. Measured success metrics.

### Pilot exit criteria
- ≥25 real users have completed the workflow.
- Core workflow completion and follow-up metrics are measured.
- No unresolved critical security/privacy issue.
- Offline sync failures are observable and recoverable.
- Operational ownership exists for support and data quality.

## Rough Timeline

| Week | Focus | Milestone |
|---|---|---|
| 1 | Screens + workflow | Kenshi |
| 2 | Frontend polish + test data | Kenshi |
| 3 | API + database | Samurai |
| 4 | Auth + referral state machine | Samurai |
| 5 | Offline sync + dashboards | Samurai |
| 6+ | Pilot hardening/integration | Shogun |
