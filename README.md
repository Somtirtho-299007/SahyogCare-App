# SahyogCare

> A patient-centred rural healthcare coordination platform that helps patients and ASHA/ANM workers maintain visibility across the referral, care, and follow-up journey.

[![Live Demo](https://img.shields.io/badge/Live-Demo-blue?style=for-the-badge)](https://sahyogcare-app.onrender.com)
[![GitHub Repo](https://img.shields.io/badge/GitHub-Repo-black?style=for-the-badge&logo=github)](https://github.com/Somtirtho-299007/SahyogCare-App)

---

## Preview

### Patient Dashboard

| Desktop | Mobile |
| :--- | :--- |
| ![SahyogCare Patient Dashboard](./screenshots/patient-desktop.png) | ![SahyogCare Patient Dashboard Mobile](./screenshots/patient-mobile.jpeg) |

### More Screens

#### Login / Entry

| Desktop | Mobile |
| :--- | :--- |
| ![SahyogCare Login Desktop](./screenshots/login-desktop.png) | ![SahyogCare Login Mobile](./screenshots/login-mobile.jpeg) |

#### ASHA / ANM Workflow

| Desktop | Mobile |
| :--- | :--- |
| ![SahyogCare ASHA Desktop](./screenshots/asha-desktop.png) | ![SahyogCare ASHA Mobile](./screenshots/asha-mobile.jpeg) |

---

## What It Does

SahyogCare is a patient-centred rural healthcare coordination prototype focused on continuity across the referral journey.

It provides role-based interfaces for patients and ASHA/ANM workers to support patient intake, referral visibility, care coordination, and follow-up.

The prototype addresses a specific gap identified during the Ronin phase: a referral should not become the end of a patient's visible journey. Instead, SahyogCare is designed around the question:

> **"What happened to the patient after the referral?"**

The current frontend prototype demonstrates how a patient case can move through different stages of the healthcare journey while keeping important information visible to the relevant users.

SahyogCare is intended to coordinate existing healthcare workflows rather than replace hospitals, government healthcare systems, clinical decision-making, or telemedicine services.

---

## Features

- **Role-based experience** — Dedicated interfaces for patients and ASHA/ANM healthcare workers.
- **Referral journey visibility** — Makes the patient's referral journey visible through clearly defined stages such as Created, Accepted, Arrival, Consulted, Outcome, Follow-up Due, and Closed.
- **Patient follow-up** — Keeps the post-referral stage visible instead of treating referral as the end of the workflow.
- **Patient intake and triage** — Allows ASHA/ANM workers to capture patient information and initial triage details.
- **Facility-oriented referral flow** — Connects a patient case with the intended healthcare facility during the referral process.
- **Case status visibility** — Uses clear referral states and journey stages to communicate the current position of a case.
- **Multilingual interface** — Provides a centralized language-selection sidebar with multiple Indian language options.
- **Responsive design** — Adapts the core workflow for desktop and mobile screen sizes.
- **Patient checklist** — Presents relevant actions and information to help patients understand their current journey.
- **Interactive frontend workflow** — User interactions update the interface without requiring a backend for the current prototype.
- **Consistent UI system** — Uses a common visual language, spacing, typography, cards, controls, and navigation patterns across the application.

---

## Planning Docs

These documents continue the planning work established during the Level 1 Ronin submission.

- [Product Requirements](./docs/PRD.md)
- [Architecture](./docs/ARCHITECTURE.md)
- [Roadmap](./docs/ROADMAP.md)
- [API Specification](./docs/API_SPEC.md)
- [Requirements](./docs/REQUIREMENTS.md)

### Deviations from the Plan

The original Ronin plan described a complete full-stack healthcare coordination system with authentication, backend APIs, database persistence, offline synchronization, and facility-level data.

For Kenshi, the implementation intentionally focuses on completing and validating the frontend workflow before introducing the full backend architecture planned for Samurai.

The Kenshi version therefore demonstrates the core user experience and referral workflow without claiming backend capabilities that have not yet been implemented.

During frontend development, the interface was also refined with:

- A centralized language-selection system
- Multiple Indian language options
- Responsive patient and ASHA/ANM experiences
- Improved referral journey visibility
- Mobile-focused layout adjustments
- Clearer role-based workflows

The backend, authentication, persistent database storage, real cross-device referral synchronization, offline write synchronization, and live healthcare data remain future milestones.

---

## Tech Stack

| Technology | Purpose |
| :--- | :--- |
| **React** | Component-based frontend application |
| **JavaScript** | Application logic and interactions |
| **HTML** | Application structure |
| **CSS** | Responsive layouts and visual styling |
| **Vite** | Frontend development and build tooling |
| **Render** | Live deployment |

---

## Run Locally

### 1. Clone the repository

```bash
git clone [https://github.com/Somtirtho-299007/SahyogCare-App.git](https://github.com/Somtirtho-299007/SahyogCare-App.git)
```

### 2. Move into the project directory

```bash
cd SahyogCare-App
```

### 3. Install dependencies

```bash
npm install
```

### 4. Start the development server

```bash
npm run dev
```

Vite will display the local development URL in the terminal. It is typically:

```text
http://localhost:5173
```

Open the displayed URL in your browser to run SahyogCare locally.

---

## Environment Variables

The current Kenshi frontend prototype does not require any secret environment variables to run locally.

No API keys, database credentials, authentication secrets, or other sensitive environment variables are required by the current frontend implementation.

Future backend milestones may introduce environment variables for services such as authentication, databases, APIs, or external healthcare data sources.

Secret values should never be committed to the repository.

---

## What I Learned

Building SahyogCare during Kenshi taught me how to turn the workflow defined during Ronin into an actual responsive frontend instead of treating the product as a collection of independent screens.

One of the harder parts was maintaining a consistent experience across different user roles while keeping the patient referral journey understandable.

I also learned that responsive design is not simply about shrinking a desktop interface. Information hierarchy, spacing, navigation, and component layout often need to be reconsidered for smaller screens.

Another important challenge was implementing centralized language selection so that users can change the application language from one place rather than managing language changes separately across individual screens.

Working on the project also helped me understand how frontend state and user interactions can be used to demonstrate a complete product workflow even before a backend is introduced.

The design decision I am most proud of is the referral journey representation because it keeps the product focused on the original problem identified during Ronin:

> **Making the patient's journey visible beyond the initial referral.**

---

## What Comes Next

### Samurai — Full-Stack

The next milestone builds on the Kenshi frontend prototype by introducing the backend capabilities defined during Ronin:

- Authentication and role-based access
- PostgreSQL persistence
- Real referral state transitions
- Facility and diagnostic availability data
- Audit events
- Offline synchronization
- Authorised referral visibility between facilities
- Recorded referral outcomes and follow-up events
- Backend APIs connecting the patient and healthcare-worker workflows

The goal is to move from a frontend prototype to a functioning multi-user coordination system.

### Shogun — Controlled Pilot

The longer-term goal is a controlled pilot with real users, measured referral completion and follow-up rates, secure handling of health information, operational monitoring, accessibility and local-language support, and appropriate integration boundaries with existing public-health systems.

The final objective is not simply to deploy the interface, but to validate whether the workflow improves visibility and continuity across the referral journey.

---

## Journey to Mastery

SahyogCare is being developed as part of the Journey to Mastery progression:

- **Level 1 — Ronin:** Problem discovery, product planning, architecture, requirements, and roadmap.
- **Level 2 — Kenshi:** Responsive frontend implementation and validation of the core user journey.
- **Level 3 — Samurai:** Full-stack implementation with authentication, persistence, APIs, and synchronization.
- **Level 4 — Shogun:** Controlled pilot, measurement, security, accessibility, and production-oriented refinement.

---

*Submitted to Journey to Mastery — Level 2: Kenshi*
