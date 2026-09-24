# SahyogCare

> A rural healthcare coordination system that helps ASHA/ANM workers move patients from first assessment through referral, care, and follow-up without losing the case between facilities.

## The Idea

Rural patients often move through several levels of care, but the referral can become a dead end once the patient leaves the originating facility. SahyogCare gives ASHA/ANM workers and authorised facility staff one lightweight workflow for creating a patient case, routing a referral, tracking its status, recording diagnostics/treatment, and closing the loop with follow-up. It is designed offline-first for intermittent connectivity and is intended to coordinate existing public-health workflows rather than replace government clinical or telemedicine systems. The first version focuses on visibility and continuity, not autonomous diagnosis or prescription.

## Sketch

[View the live Excalidraw board](https://excalidraw.com/#json=LPlhT7WLNyTjtrGa0ChFl,QaXOR13Xe2c9NlBotpV83w)

## Documents

- [Product Requirements](./docs/PRD.md)
- [Architecture](./docs/ARCHITECTURE.md)
- [API Spec](./docs/API_SPEC.md)
- [Roadmap](./docs/ROADMAP.md)
- [Requirements](./docs/REQUIREMENTS.md)

## Planned Stack

| Layer | Technology | Why |
|---|---|---|
| Framework | React + TypeScript + PWA | Mobile-first workflow with offline support |
| Backend | Python + FastAPI | Small, explicit REST API and easy validation |
| Database | PostgreSQL | Relational model fits patients, referrals, facilities and events |
| Auth | JWT + role-based access | Simple authenticated MVP with facility/role boundaries |
| Offline | IndexedDB + service worker | Queue writes and cache core screens during connectivity gaps |
| Hosting | Vercel (frontend) + Render (API) + managed PostgreSQL | Low-ops prototype deployment |

## What I'm Building Toward

**Kenshi (frontend):** A usable mobile-first prototype with patient intake, referral creation, referral status tracking, facility lookup, follow-up tasks, and a district/facility summary screen. The core journey can be demonstrated with seeded data without a backend.

**Samurai (full-stack):** Add authentication, PostgreSQL persistence, real referral state transitions, offline sync, facility/diagnostic availability data, audit events, and role-aware dashboards. A referral created on one device should become visible to an authorised receiving facility and return a recorded outcome.

**Shogun (production):** A controlled pilot with real users, measured referral completion and follow-up rates, secure handling of health information, operational monitoring, accessibility/local-language support, and integration boundaries for existing public-health systems. "Done" means the workflow is actually used and its value can be measured, not simply that the interface is deployed.

---

*Submitted to Journey to Mastery — Level 1: Ronin*
