# Product Requirements Document — SahyogCare

## 1. Problem Statement

A rural patient may be assessed at one public-health facility and then sent elsewhere for diagnostics, specialist consultation, treatment, or follow-up. The operational handoff can be difficult to track: the originating worker may not know whether the receiving facility accepted the referral, whether the patient arrived, whether the required service happened, or whether follow-up was completed. This creates avoidable uncertainty for the people coordinating care.

The problem is specifically a **care-coordination and referral-continuity problem**, not a claim that rural healthcare has no digital systems. SahyogCare is intended to connect the steps around a case so that a referral has a visible lifecycle from creation to closure.

## 2. Target Users

### Primary — ASHA / ANM / frontline health worker
Needs to:
- create or find a patient case quickly;
- record a small set of assessment details;
- identify the next facility/service;
- create and monitor a referral;
- see overdue follow-ups;
- work when connectivity is unreliable.

### Secondary — receiving facility staff / doctor
Needs to:
- see authorised incoming referrals;
- accept or reject a referral with a reason;
- record arrival, consultation, diagnostic result, treatment/outcome;
- send the case back into follow-up.

### Tertiary — facility/district coordinator
Needs to:
- see referral volumes and bottlenecks;
- identify overdue cases;
- monitor completion and follow-up;
- avoid exposing unnecessary patient detail.

## 3. Core User Journey

1. Frontline worker creates/selects patient.
2. Worker records basic encounter information.
3. System presents a clinician-approved urgency category.
4. Worker selects destination facility/service.
5. Referral is created.
6. Receiving facility accepts/rejects it.
7. Patient arrival and care are recorded.
8. Diagnostics/treatment outcome is recorded.
9. Follow-up task is scheduled.
10. Follow-up is completed or marked missed.
11. Case is closed or escalated.

## 4. MVP Features

### F1 — Patient and encounter
- Create patient profile with minimum necessary fields.
- Create an encounter linked to the patient.
- Record symptoms/vitals as structured fields.
- Display previous relevant encounters to authorised users.

### F2 — Referral
- Create referral with source, destination, reason, priority and requested service.
- Generate a unique referral ID.
- Show referral lifecycle and timestamps.
- Allow receiving facility to accept/reject.
- Allow status updates for arrival, consultation, diagnostic completion and outcome.

### F3 — Facility/service lookup
- Search facilities by service.
- Show whether a required service is currently listed as available.
- Show last-updated timestamp.
- Do not imply real-time availability unless the source actually provides it.

### F4 — Follow-up
- Create a follow-up date and responsible worker.
- Show due, completed and missed tasks.
- Escalate overdue cases according to configured rules.

### F5 — Offline-first workflow
- Cache core app shell and essential screens.
- Allow creation of queued records while offline.
- Sync queued records when connectivity returns.
- Display sync state clearly.
- Prevent silent data loss.

### F6 — Role-aware dashboards
- Worker: assigned patients/referrals/follow-ups.
- Facility: incoming/outgoing referrals and pending actions.
- Coordinator: aggregate operational metrics.

## 5. Success Metrics

Initial pilot targets are behavioural, not clinical outcome claims:

- ≥25 real users can complete the core referral workflow.
- ≥80% of test referrals move from creation to a recorded outcome.
- ≥90% of offline-created records eventually sync without manual re-entry.
- Median time to create a referral is ≤3 minutes in usability testing.
- ≥80% of users can identify the current status of a referral without assistance.
- Follow-up tasks have an explicit owner and due date in ≥95% of created cases.

These are product targets for validation, not claims about health outcomes.

## 6. Out of Scope

- Autonomous diagnosis.
- Autonomous prescribing or medication substitution.
- Emergency clinical decision-making by AI.
- Replacing eSanjeevani or any government clinical platform.
- Building a new national health-ID ecosystem.
- Full hospital EMR functionality.
- Billing/insurance workflows.
- Ambulance dispatch.
- Claims that facility inventory is real-time unless an authoritative feed exists.
- Storing more health information than the workflow requires.

## 7. Key Product Principles

1. **Closed loop:** a referral is not complete when it is sent; it is complete when an outcome/follow-up is recorded.
2. **Offline first:** connectivity gaps must not erase the workflow.
3. **Human decision authority:** AI may assist with transcription/summarisation, but clinical decisions remain with authorised professionals.
4. **Minimum necessary data:** collect only what the workflow needs.
5. **Visible uncertainty:** stale facility availability must be labelled as stale.
6. **Existing-system friendly:** integrate or link to existing public-health systems where appropriate rather than recreate them.

## 8. Representative Scenario

Savitri, 42, is assessed by an ASHA worker. The worker records fever and elevated blood pressure. A referral is created because a diagnostic assessment is needed. The originating facility can see whether the receiving facility accepted it. The receiving facility records arrival, consultation and test outcome. A seven-day follow-up is created. If the follow-up is missed, it appears as overdue for the responsible worker and coordinator.

## 9. MVP Acceptance Criteria

A demo case must be able to move through:

`Patient → Encounter → Referral Created → Accepted → Arrived → Consulted → Diagnostic/Outcome → Follow-up Due → Follow-up Completed → Closed`

The UI must show the current state and the actor/action that caused the last state change.
