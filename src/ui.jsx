import React, { useEffect, useState } from "react";
import { useLanguage } from "./i18n.jsx";

function useCountUp(v) {
  const [n, setN] = useState(typeof v === "number" ? 0 : v);
  useEffect(() => {
    if (typeof v !== "number" || window.matchMedia?.("(prefers-reduced-motion: reduce)").matches) {
      setN(v);
      return;
    }
    let raf, start;
    const from = 0;
    const tick = (ts) => {
      start ??= ts;
      const p = Math.min(1, (ts - start) / 500);
      setN(Math.round(from + (v - from) * (1 - Math.pow(1 - p, 3))));
      if (p < 1) raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, [v]);
  return n;
}
export function Stat({ label, value, meta, tour }) {
  const shown = useCountUp(value);
  return (
    <div className="stat-card" data-tour={tour}>
      <span>{label}</span>
      <strong>{shown}</strong>
      <small>{meta}</small>
    </div>
  );
}
export function Dashboard({ title, subtitle, children }) {
  const { t } = useLanguage();
  return (
    <>
      <div className="hero">
        <div>
          <p className="eyebrow">{t("workspace")}</p>
          <h1>{title}</h1>
          <p>{subtitle}</p>
        </div>
        <div className="hero-mark">✚</div>
      </div>
      {children}
    </>
  );
}
export function Field({ label, children, full }) {
  return (
    <label className={full ? "field full" : "field"}>
      <span>{label}</span>
      {children}
    </label>
  );
}
export function Empty({ title, text }) {
  return (
    <div className="empty">
      <div>○</div>
      <h4>{title}</h4>
      <p>{text}</p>
    </div>
  );
}
export function Skeleton() {
  return (
    <div className="skeleton-list">
      <div></div>
      <div></div>
      <div></div>
    </div>
  );
}
export function VitalInput({ label, value, set, unit }) {
  return (
    <label className="vital-field">
      <span>{label}</span>
      <div>
        <input
          type="number"
          min="0"
          inputMode="decimal"
          value={value}
          onChange={(e) => set(e.target.value)}
          placeholder="—"
        />
        <small>{unit}</small>
      </div>
    </label>
  );
}
