# SahyogCare

> **A patient-centred rural healthcare coordination platform that makes the patient's referral journey visible from the first point of contact to hospital care and follow-up.**

---

## Idea

SahyogCare connects the key points of a rural healthcare journey:

**Patient → ASHA/ANM → Doctor/Hospital**

The **patient is the primary beneficiary** and receives a mobile account to understand and track their referral journey.

The **ASHA/ANM worker is the first point of contact and mediator**, helping with basic registration, information collection and referral initiation.

The **doctor/hospital is the receiving end of the referral**, where consultation, diagnostics and treatment take place.

SahyogCare does not replace existing hospitals, doctors, telemedicine platforms or government healthcare systems. It provides a coordination and transparency layer between them.

### Core Question

> **What happened to the patient after the referral?**

---

## Problem Statement

In rural healthcare, a patient may be referred from one facility to another without having clear visibility into what happens afterwards.

A patient may not know:

- Whether the referral was accepted
- Where they need to go
- Whether the hospital received the referral
- Whether they reached the facility
- Whether the doctor consulted them
- Whether the required diagnostic or treatment was completed
- When the next follow-up is due

This can lead to delayed care, repeated visits, unnecessary travel, missed diagnostics, fragmented information and missed follow-ups.

---

## Proposed Solution

SahyogCare creates a **closed-loop referral and patient-transparency system**.

```text
Patient
   ↓
ASHA / ANM
   ↓
Assessment
   ↓
Referral
   ↓
Receiving Hospital
   ↓
Doctor / Care
   ↓
Diagnostics / Treatment
   ↓
Follow-up
   ↓
Case Closed


##Targeted Audience 

Patients — Primary beneficiaries who need visibility into their referral, care and follow-up.
ASHA / ANM — Grassroots first point of contact who registers patients, records basic information and facilitates referrals.
Doctors / Hospitals — Receiving end that accepts referrals and continues patient care.

##Key Features

1.Patient mobile account with referral-status visibility

2.Patient registration and basic assessment

3.ASHA/ANM-assisted referral creation

4.Closed-loop referral tracking

5.Hospital/referral acceptance status

6.Doctor and care-status updates

7.Diagnostic and treatment status
8.Follow-up dates and reminders

9.Overdue referral/follow-up alerts

10.Offline-first data entry and synchronisation

11.Multilingual interface

12.Role-based access and secure patient data

## *Patient Transparency*

Referral Created       ✓
Referral Accepted      ✓
Patient Arrived        ✓
Doctor Consultation    ✓
Diagnostic / Treatment ⏳
Follow-up              ○

The patient should know where their referral stands and what happens next.

## *Product Approach*

Patient-first — The patient remains the primary beneficiary.

Closed-loop — A referral is tracked from creation through care and follow-up.

Offline-first — Core grassroots workflows should continue during network interruptions.

Interoperable — Designed to work alongside existing healthcare infrastructure rather than replace it.

Clinician-led — The platform supports coordination; diagnosis and treatment remain with healthcare professionals.

## *Technology Stack*
 **Mobile App:-
React Native + Expo
Language:-
TypeScript
Backend:-
Python + FastAPI
Database:-
PostgreSQL
Offline Storage:-
SQLite
Authentication:-
JWT
Notifications:-
Firebase Cloud Messaging
Cache / Jobs:-
Redis
AI Services:-
Python
API:-
REST
Deployment:-
Hosting Platform 
Version Control:-
Git + GitHub**

## *System Flow*

Patient Mobile App
        ↕
SahyogCare Backend
        ↕
ASHA / ANM App
        ↕
Referral System
        ↕
Doctor / Hospital


Patient-facing status remains connected to the referral lifecycle:
Created → Accepted → Arrived → Consulted → Care → Follow-up → Closed

## *AI*
AI is an optional supporting layer, not the decision-maker.
Potential uses:
Voice-to-text for ASHA/ANM notes
Structured case summarisation
Administrative prioritisation of pending referrals
AI will not diagnose patients, prescribe medicines or replace doctors.

## *Existing Healthcare* Ecosystem
SahyogCare is intended to complement existing systems such as ABDM and eSanjeevani, where appropriate integrations and APIs are available.

Existing Healthcare Systems
          ↓
      SahyogCare
          ↓
Patient Referral Transparency
          ↓
Care → Follow-up → Closure

## *MVP*
MVP

The MVP focuses on one complete journey:

Patient Registration
        ↓
Basic Assessment
        ↓
Referral Creation
        ↓
Referral Acceptance
        ↓
Hospital / Doctor Care
        ↓
Follow-up
        ↓
Patient Sees Status
        ↓
Case Closed

## *Contributors*
Contributors
 1.Somtirtho Banerjee
 2.Arghanil Mukherjee

Team: Stack Overflow
