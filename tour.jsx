import React, { useEffect, useState } from "react";

/* ---------- Guided app tour (UI only: spotlights existing elements via data-tour) ---------- */
export const TOURS = {
  auth: [
    {
      title: "Welcome to SahyogCare",
      body: "One referral, one visible journey — from the ASHA worker's doorstep to the hospital and back.",
    },
    {
      target: "roles",
      title: "Pick your role",
      body: "ASHA / ANM, Patient or Medical Team. Each role opens its own dashboard.",
    },
    {
      target: "email",
      title: "Verify with a code",
      body: "Enter your email and send a verification code. In this demo the code is shown on screen. Patients just continue without logging in.",
    },
    { target: "language", title: "Your language", body: "Switch between 23 Indian languages any time from this tab." },
  ],
  asha: [
    {
      target: "stats",
      title: "Your day at a glance",
      body: "Cases created today, open referrals and new alerts about your patients.",
    },
    {
      target: "intake",
      title: "Intake → facility → referral",
      body: "Record the patient, pick a receiving facility and service, then create the referral and give the patient its code and QR pass.",
    },
    {
      target: "continuity",
      title: "Referral continuity",
      body: "New alerts and every referral you create, with its latest status. Tap one to see its journey.",
    },
    {
      target: "vitals",
      title: "Vitals & medicines",
      body: "Update blood pressure, other vitals and ongoing medicines for the latest patient.",
    },
    { target: "help", title: "Replay anytime", body: "Tap ? to see this tour again." },
  ],
  patient: [
    {
      target: "token",
      title: "Enter your token",
      body: "Type the referral code your ASHA worker gave you, like SC-7K3M9Q, and the last 4 digits of your phone.",
    },
    {
      target: "journey",
      title: "Your journey",
      body: "See which steps are done, where you are now and what comes next.",
    },
    { target: "consult", title: "Talk to a doctor", body: "Start an eSanjeevani teleconsultation from here." },
    { target: "help", title: "Replay anytime", body: "Tap ? to see this tour again." },
  ],
  coordinator: [
    { target: "requests", title: "Who wants to join", body: "People who signed up with their email ask for a role here. Approve or reject in one tap." },
    { target: "beds", title: "Beds in the district", body: "Free beds in every ward of every hospital, as their staff last reported." },
    { target: "help", title: "Replay anytime", body: "Tap ? to see this tour again." },
  ],
  medical: [
    {
      target: "stats",
      title: "Queue overview",
      body: "Incoming referrals, priority cases and emergencies needing escalation.",
    },
    {
      target: "filters",
      title: "Filter by triage",
      body: "Show all open referrals, one triage level, or the closed ones.",
    },
    {
      target: "queue",
      title: "Move each referral forward",
      body: "Accept or reject, record arrival (or scan the patient's pass), then the doctor records consultation and outcome.",
    },
    { target: "help", title: "Replay anytime", body: "Tap ? to see this tour again." },
  ],
};
export function Tour({ steps, open, onClose }) {
  const [i, setI] = useState(0);
  const [rect, setRect] = useState(null);
  const step = steps?.[i];
  useEffect(() => {
    if (open) setI(0);
  }, [open]);
  const measure = () => {
    const el = step?.target && document.querySelector(`[data-tour="${step.target}"]`);
    if (!el) {
      setRect(null);
      return;
    }
    const r = el.getBoundingClientRect();
    setRect(r.width ? { top: r.top, left: r.left, width: r.width, height: r.height } : null);
  };
  useEffect(() => {
    if (!open || !step) return;
    setRect(null);
    const el = step.target && document.querySelector(`[data-tour="${step.target}"]`);
    if (el)
      el.scrollIntoView({
        block: el.offsetHeight > window.innerHeight * 0.55 ? "start" : "center",
        behavior: "smooth",
      });
    const x = setTimeout(measure, 380);
    return () => clearTimeout(x);
  }, [open, i]);
  useEffect(() => {
    if (!open) return;
    const k = (e) => {
      if (e.key === "Escape") onClose();
      if (e.key === "ArrowRight") setI((x) => Math.min(x + 1, steps.length - 1));
      if (e.key === "ArrowLeft") setI((x) => Math.max(0, x - 1));
    };
    window.addEventListener("resize", measure);
    window.addEventListener("scroll", measure, true);
    window.addEventListener("keydown", k);
    return () => {
      window.removeEventListener("resize", measure);
      window.removeEventListener("scroll", measure, true);
      window.removeEventListener("keydown", k);
    };
  });
  if (!open || !step) return null;
  const last = i === steps.length - 1,
    vw = window.innerWidth,
    vh = window.innerHeight,
    pad = 8,
    gap = 14,
    w = Math.min(330, vw - 32);
  let spot = null,
    pos = { width: w };
  if (rect) {
    const top = Math.max(rect.top - pad, 6),
      bottom = Math.min(rect.top + rect.height + pad, vh - 6);
    spot = {
      top,
      left: Math.max(rect.left - pad, 6),
      width: Math.min(rect.width + pad * 2, vw - 12),
      height: Math.max(bottom - top, 0),
    };
    const left = Math.min(Math.max(16, rect.left + rect.width / 2 - w / 2), vw - w - 16);
    if (vh - (top + spot.height) - gap >= 220) pos = { ...pos, top: top + spot.height + gap, left };
    else if (top - gap >= 220) pos = { ...pos, bottom: vh - top + gap, left };
    else pos = { ...pos, bottom: 16, left: (vw - w) / 2 };
  }
  return (
    <div className="tour" role="dialog" aria-modal="true" aria-label="App tour">
      {spot ? <div className="tour-spot" style={spot} /> : <div className="tour-dim" />}
      <div className={`tour-card ${spot ? "" : "centered"}`} style={pos} key={i}>
        <div className="tour-top">
          <span>
            {i + 1} / {steps.length}
          </span>
          <button className="link-btn" onClick={onClose}>
            Skip
          </button>
        </div>
        <h4>{step.title}</h4>
        <p>{step.body}</p>
        <div className="tour-foot">
          <div className="tour-dots">
            {steps.map((_, k) => (
              <i key={k} className={k === i ? "on" : k < i ? "done" : ""} />
            ))}
          </div>
          <div className="tour-actions">
            {i > 0 && (
              <button className="secondary-btn" onClick={() => setI(i - 1)} aria-label="Previous">
                ←
              </button>
            )}
            <button className="primary-btn" onClick={() => (last ? onClose() : setI(i + 1))}>
              {last ? "Got it" : "Next →"}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
