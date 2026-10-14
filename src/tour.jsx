import React, { useEffect, useState } from "react";
import { useLanguage } from "./i18n.jsx";

/* ---------- Guided app tour (UI only: spotlights existing elements via data-tour) ---------- */
// Each step names i18n keys (see i18n.jsx: tour.*), so the tour speaks the chosen language.
const step = (target, key) => ({ target, title: `tour.${key}.t`, body: `tour.${key}.b` });
const replay = step("help", "replay");
export const TOURS = {
  auth: [step(null, "welcome"), step("doors", "doors"), step("language", "language")],
  asha: [step("stats", "ashaStats"), step("intake", "ashaIntake"), step("continuity", "ashaContinuity"), step("vitals", "ashaVitals"), replay],
  patient: [step("sos", "patientSos"), step("journey", "patientJourney"), step("consult", "patientConsult"), replay],
  coordinator: [step("requests", "coordRequests"), step("people", "coordPeople"), step("beds", "coordBeds"), replay],
  medical: [step("stats", "medStats"), step("filters", "medFilters"), step("queue", "medQueue"), replay],
};

export function Tour({ steps, open, onClose }) {
  const { t } = useLanguage();
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
    <div className="tour" role="dialog" aria-modal="true" aria-label={t("appTour")}>
      {spot ? <div className="tour-spot" style={spot} /> : <div className="tour-dim" />}
      <div className={`tour-card ${spot ? "" : "centered"}`} style={pos} key={i}>
        <div className="tour-top">
          <span>
            {i + 1} / {steps.length}
          </span>
          <button className="link-btn" onClick={onClose}>
            {t("tourSkip")}
          </button>
        </div>
        <h4>{t(step.title)}</h4>
        <p>{t(step.body)}</p>
        <div className="tour-foot">
          <div className="tour-dots">
            {steps.map((_, k) => (
              <i key={k} className={k === i ? "on" : k < i ? "done" : ""} />
            ))}
          </div>
          <div className="tour-actions">
            {i > 0 && (
              <button className="secondary-btn" onClick={() => setI(i - 1)} aria-label={t("back")}>
                ←
              </button>
            )}
            <button className="primary-btn" onClick={() => (last ? onClose() : setI(i + 1))}>
              {last ? t("tourDone") : `${t("next")} →`}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
