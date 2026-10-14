// The patient's health record: register, history, care chart, prescriptions, photos,
// vitals with normal ranges, recording a death — and the patient's own portal with
// the night emergency button.
import React, { useCallback, useEffect, useState } from "react";
import { api, patientApi, patientLogin, patientLogout, patientToken, photoUrl, uploadPhoto } from "./api.js";
import { useLanguage } from "./i18n.jsx";
import { Empty, Field, Skeleton } from "./ui.jsx";

const pretty = (s) => (s || "").replaceAll("_", " ").toLowerCase().replace(/^./, (c) => c.toUpperCase());
const day = (d) => (d ? new Date(d).toLocaleDateString(undefined, { day: "numeric", month: "short", year: "numeric" }) : "—");
const when = (d) => (d ? new Date(d).toLocaleString(undefined, { day: "numeric", month: "short", hour: "numeric", minute: "2-digit" }) : "—");

export const VITALS = [
  { key: "systolic", label: "BP (upper)", unit: "mmHg" },
  { key: "diastolic", label: "BP (lower)", unit: "mmHg" },
  { key: "pulse", label: "Pulse", unit: "/min" },
  { key: "temperature_c", label: "Temperature", unit: "°C" },
  { key: "spo2", label: "Oxygen (SpO₂)", unit: "%" },
  { key: "respiratory_rate", label: "Breathing rate", unit: "/min" },
  { key: "glucose_mg_dl", label: "Blood sugar", unit: "mg/dL" },
  { key: "weight_kg", label: "Weight", unit: "kg" },
];
const TIMINGS = [
  ["MORNING", "Morning"],
  ["NOON", "Afternoon"],
  ["EVENING", "Evening"],
  ["NIGHT", "Night"],
];
// Column heads of the medicine timetable (short enough for a phone).
const TIMING_HEAD = { MORNING: ["☀", "Morn"], NOON: ["🌤", "Noon"], EVENING: ["🌇", "Eve"], NIGHT: ["🌙", "Night"] };
const FOOD = { BEFORE: "Before food", AFTER: "After food", WITH: "With food", ANY: "" };
const CATEGORIES = [
  ["GENERAL", "General"],
  ["PREGNANCY", "Pregnancy"],
  ["AFTER_SURGERY", "After surgery"],
  ["CHRONIC", "Long-term illness"],
  ["CHILD", "Child"],
  ["OTHER", "Other"],
];
const LANGS = [
  ["bn", "বাংলা (Bengali)"],
  ["hi", "हिन्दी (Hindi)"],
  ["en", "English"],
];

// ---------- vitals with normal ranges ----------

let rangesCache = null;
export function useVitalRanges() {
  const [ranges, setRanges] = useState(rangesCache || {});
  useEffect(() => {
    if (rangesCache) return;
    patientApi
      .get("/vital-ranges")
      .then((list) => {
        rangesCache = Object.fromEntries(list.map((r) => [r.field, r]));
        setRanges(rangesCache);
      })
      .catch(() => {});
  }, []);
  return ranges;
}

export function flagOf(range, value) {
  if (!range || value === "" || value === null || value === undefined || Number.isNaN(Number(value))) return null;
  const v = Number(value);
  return v < range.low ? "LOW" : v > range.high ? "HIGH" : "NORMAL";
}

export function FlagChip({ flag }) {
  if (!flag) return null;
  return <span className={`flag flag-${flag.toLowerCase()}`}>{flag === "NORMAL" ? "Normal" : flag === "LOW" ? "Low" : "High"}</span>;
}

export function VitalsGrid({ values, onChange, ranges }) {
  return (
    <div className="vitals-grid">
      {VITALS.map((v) => {
        const range = ranges[v.key];
        return (
          <label className="vital-field" key={v.key}>
            <span>
              {v.label} <FlagChip flag={flagOf(range, values[v.key])} />
            </span>
            <div>
              <input
                type="number"
                inputMode="decimal"
                min="0"
                value={values[v.key] ?? ""}
                onChange={(e) => onChange({ ...values, [v.key]: e.target.value })}
                placeholder="—"
              />
              <small>{v.unit}</small>
            </div>
            <em className="range-note">{range ? `Normal ${range.label}` : " "}</em>
          </label>
        );
      })}
    </div>
  );
}

export function VitalsReadout({ vitals, flags = {}, ranges = {} }) {
  const shown = VITALS.filter((v) => vitals?.[v.key] !== null && vitals?.[v.key] !== undefined);
  if (!shown.length) return <p className="muted">No readings.</p>;
  return (
    <div className="vitals-readout">
      {shown.map((v) => (
        <div key={v.key}>
          <span>{v.label}</span>
          <b>
            {vitals[v.key]} <small>{v.unit}</small>
          </b>
          <FlagChip flag={flags[v.key] || flagOf(ranges[v.key], vitals[v.key])} />
          {ranges[v.key] && <em>Normal {ranges[v.key].label}</em>}
        </div>
      ))}
    </div>
  );
}

const vitalsBody = (values) =>
  Object.fromEntries(VITALS.filter((v) => values[v.key] !== "" && values[v.key] !== undefined).map((v) => [v.key, Number(values[v.key])]));
const fieldErrors = (e) =>
  e.details?.fields ? `${e.message} ${Object.entries(e.details.fields).map(([k, m]) => `${k}: ${m}`).join(" · ")}` : e.message;

// ---------- photos ----------

export function PhotoView({ id, asPatient = false, alt = "Photo", className = "photo-thumb" }) {
  const [url, setUrl] = useState("");
  useEffect(() => {
    if (!id) return;
    let alive = true,
      made = "";
    photoUrl(id, asPatient)
      .then((u) => {
        made = u;
        if (alive) setUrl(u);
      })
      .catch(() => {});
    return () => {
      alive = false;
      if (made) URL.revokeObjectURL(made);
    };
  }, [id, asPatient]);
  if (!id) return <div className={`${className} photo-empty`}>👤</div>;
  return url ? <img className={className} src={url} alt={alt} /> : <div className={`${className} photo-empty`}>…</div>;
}

// Two buttons: take a photo with the camera, or pick one from the gallery.
export function PhotoPicker({ label = "Photo", onFile, busy }) {
  const pick = (e) => {
    const f = e.target.files?.[0];
    e.target.value = "";
    if (f) onFile(f);
  };
  return (
    <div className="photo-picker">
      <label className={`secondary-btn ${busy ? "is-busy" : ""}`}>
        📷 {label}
        <input type="file" accept="image/*" capture="environment" onChange={pick} hidden disabled={busy} />
      </label>
      <label className={`link-btn ${busy ? "is-busy" : ""}`}>
        Choose from gallery
        <input type="file" accept="image/*" onChange={pick} hidden disabled={busy} />
      </label>
    </div>
  );
}

// ---------- care chart ----------

export function CareChart({ items, onEnd, empty = "Nothing on the chart." }) {
  if (!items.length) return <p className="muted">{empty}</p>;
  const medicines = items.filter((i) => i.kind === "MEDICINE");
  const practices = items.filter((i) => i.kind === "PRACTICE");
  return (
    <div className="care-chart">
      {medicines.length > 0 && (
        <div className="dose-table" role="table" aria-label="Medicine timings">
          <div className="dose-row dose-head" role="row">
            <span>Medicine</span>
            {TIMINGS.map(([k, label]) => (
              <span key={k} className="dose-slot-head" title={label}>
                <i aria-hidden="true">{TIMING_HEAD[k][0]}</i>
                {TIMING_HEAD[k][1]}
              </span>
            ))}
          </div>
          {medicines.map((m) => (
            <div className="dose-row" role="row" key={m.id}>
              <div className="dose-name">
                <b>{m.name}</b>
                <small>
                  {[m.dose, FOOD[m.food], m.quantity && `Qty ${m.quantity}`].filter(Boolean).join(" · ")}
                  {m.days_left !== null && m.days_left !== undefined ? ` · ${m.days_left} day${m.days_left === 1 ? "" : "s"} left` : m.duration_days ? "" : " · until stopped"}
                </small>
                {m.instructions && <small>{m.instructions}</small>}
                {onEnd && (
                  <span className="care-actions">
                    <button className="link-btn" onClick={() => onEnd(m, "COMPLETED")}>
                      ✓ Course done
                    </button>
                    <button className="link-btn danger-link" onClick={() => onEnd(m, "STOPPED")}>
                      Stop
                    </button>
                  </span>
                )}
              </div>
              {TIMINGS.map(([k, label]) => (
                <span key={k} className={`dose-cell ${m.timings.includes(k) ? "on" : ""}`} aria-label={`${label}: ${m.timings.includes(k) ? "yes" : "no"}`}>
                  {m.timings.includes(k) ? "●" : ""}
                </span>
              ))}
            </div>
          ))}
        </div>
      )}
      {practices.length > 0 && (
        <ul className="practice-list">
          {practices.map((p) => (
            <li key={p.id}>
              <span className="chip">{pretty(p.category)}</span>
              <b>{p.name}</b>
              {p.timings.length > 0 && <small> · {p.timings.map((x) => pretty(x)).join(", ")}</small>}
              {p.instructions && <small> — {p.instructions}</small>}
              {onEnd && (
                <button className="link-btn" onClick={() => onEnd(p, "COMPLETED")}>
                  ✓ Done
                </button>
              )}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

const EMPTY_ITEM = { kind: "MEDICINE", category: "GENERAL", name: "", dose: "", quantity: "", timings: [], food: "ANY", duration_days: "", instructions: "" };
const itemBody = (it) => ({
  kind: it.kind,
  category: it.category,
  name: it.name.trim(),
  dose: it.dose.trim() || null,
  quantity: it.quantity.trim() || null,
  timings: it.timings,
  food: it.food,
  duration_days: it.duration_days ? Number(it.duration_days) : null,
  instructions: it.instructions.trim() || null,
});

function CareItemFields({ item, setItem, onRemove }) {
  const toggle = (k) => setItem({ ...item, timings: item.timings.includes(k) ? item.timings.filter((x) => x !== k) : [...item.timings, k] });
  const med = item.kind === "MEDICINE";
  return (
    <div className="care-item-form">
      <div className="segmented" role="group" aria-label="Type">
        {[
          ["MEDICINE", "💊 Medicine"],
          ["PRACTICE", "✔ Practice / advice"],
        ].map(([k, l]) => (
          <button key={k} type="button" className={item.kind === k ? "seg active" : "seg"} onClick={() => setItem({ ...item, kind: k })}>
            {l}
          </button>
        ))}
        {onRemove && (
          <button type="button" className="link-btn danger-link" onClick={onRemove}>
            Remove
          </button>
        )}
      </div>
      <div className="form-grid">
        <Field label={med ? "Medicine name *" : "What to do *"} full>
          <input value={item.name} onChange={(e) => setItem({ ...item, name: e.target.value })} placeholder={med ? "e.g. Iron Folic Acid" : "e.g. Rest, no heavy lifting"} />
        </Field>
        <Field label="Category">
          <select value={item.category} onChange={(e) => setItem({ ...item, category: e.target.value })}>
            {CATEGORIES.map(([k, l]) => (
              <option key={k} value={k}>
                {l}
              </option>
            ))}
          </select>
        </Field>
        {med && (
          <>
            <Field label="Dose">
              <input value={item.dose} onChange={(e) => setItem({ ...item, dose: e.target.value })} placeholder="e.g. 1 tablet / 5 ml" />
            </Field>
            <Field label="Quantity">
              <input value={item.quantity} onChange={(e) => setItem({ ...item, quantity: e.target.value })} placeholder="e.g. 30 tablets" />
            </Field>
            <Field label="Food">
              <select value={item.food} onChange={(e) => setItem({ ...item, food: e.target.value })}>
                <option value="ANY">Any time</option>
                <option value="BEFORE">Before food</option>
                <option value="AFTER">After food</option>
                <option value="WITH">With food</option>
              </select>
            </Field>
          </>
        )}
        <Field label="Course (days)">
          <input inputMode="numeric" value={item.duration_days} onChange={(e) => setItem({ ...item, duration_days: e.target.value.replace(/\D/g, "").slice(0, 4) })} placeholder="empty = until stopped" />
        </Field>
        <div className="field full">
          <span>Times of day</span>
          <div className="timing-picks">
            {TIMINGS.map(([k, l]) => (
              <button key={k} type="button" className={item.timings.includes(k) ? "chip-btn on" : "chip-btn"} onClick={() => toggle(k)}>
                {l}
              </button>
            ))}
          </div>
        </div>
        <Field label="Notes" full>
          <input value={item.instructions} onChange={(e) => setItem({ ...item, instructions: e.target.value })} placeholder="optional" />
        </Field>
      </div>
    </div>
  );
}

// ---------- forms used on the record ----------

function CareItemForm({ patientId, onSaved, onCancel, toast }) {
  const [item, setItem] = useState(EMPTY_ITEM);
  const [busy, setBusy] = useState(false);
  const save = async () => {
    if (!item.name.trim() || busy) return;
    setBusy(true);
    try {
      await api.post(`/patients/${patientId}/care-items`, itemBody(item));
      toast("Added to the care chart");
      onSaved();
    } catch (e) {
      toast(fieldErrors(e));
    } finally {
      setBusy(false);
    }
  };
  return (
    <div className="sub-form reveal">
      <CareItemFields item={item} setItem={setItem} />
      <div className="action-row">
        <button className="primary-btn" disabled={!item.name.trim() || busy} onClick={save}>
          Add to chart
        </button>
        <button className="link-btn" onClick={onCancel}>
          Cancel
        </button>
      </div>
    </div>
  );
}

function PrescriptionForm({ patientId, referrals, onSaved, onCancel, toast }) {
  const [rx, setRx] = useState({ doctor_name: "", facility_name: "", prescribed_on: new Date().toISOString().slice(0, 10), diagnosis: "", notes: "", referral_id: "" });
  const [items, setItems] = useState([{ ...EMPTY_ITEM, timings: ["MORNING"] }]);
  const [photo, setPhoto] = useState(null);
  const [busy, setBusy] = useState(false);
  const save = async () => {
    if (busy) return;
    setBusy(true);
    try {
      const saved = await api.post(`/patients/${patientId}/prescriptions`, {
        doctor_name: rx.doctor_name.trim() || null,
        facility_name: rx.facility_name.trim() || null,
        prescribed_on: rx.prescribed_on || null,
        diagnosis: rx.diagnosis.trim() || null,
        notes: rx.notes.trim() || null,
        referral_id: rx.referral_id || null,
        items: items.filter((i) => i.name.trim()).map(itemBody),
      });
      if (photo) await uploadPhoto(photo, "prescription", saved.id);
      toast("Prescription saved · medicines added to the chart");
      onSaved();
    } catch (e) {
      toast(fieldErrors(e));
    } finally {
      setBusy(false);
    }
  };
  return (
    <div className="sub-form reveal">
      <p className="muted">Copy the doctor's paper prescription. A photo of the paper is kept with it.</p>
      <div className="form-grid">
        <Field label="Doctor">
          <input value={rx.doctor_name} onChange={(e) => setRx({ ...rx, doctor_name: e.target.value })} placeholder="Dr. …" />
        </Field>
        <Field label="Hospital / clinic">
          <input value={rx.facility_name} onChange={(e) => setRx({ ...rx, facility_name: e.target.value })} />
        </Field>
        <Field label="Date">
          <input type="date" value={rx.prescribed_on} onChange={(e) => setRx({ ...rx, prescribed_on: e.target.value })} />
        </Field>
        <Field label="For referral">
          <select value={rx.referral_id} onChange={(e) => setRx({ ...rx, referral_id: e.target.value })}>
            <option value="">—</option>
            {referrals.map((r) => (
              <option key={r.id} value={r.id}>
                {r.code} · {r.facility_name}
              </option>
            ))}
          </select>
        </Field>
        <Field label="Diagnosis" full>
          <input value={rx.diagnosis} onChange={(e) => setRx({ ...rx, diagnosis: e.target.value })} placeholder="as written by the doctor" />
        </Field>
        <Field label="Other notes" full>
          <textarea value={rx.notes} onChange={(e) => setRx({ ...rx, notes: e.target.value })} placeholder="tests, advice, next visit…" />
        </Field>
      </div>
      <h4 className="sub-title">Medicines and advice</h4>
      {items.map((it, i) => (
        <CareItemFields key={i} item={it} setItem={(x) => setItems(items.map((y, j) => (j === i ? x : y)))} onRemove={items.length > 1 ? () => setItems(items.filter((_, j) => j !== i)) : null} />
      ))}
      <button className="secondary-btn" onClick={() => setItems([...items, { ...EMPTY_ITEM }])}>
        ＋ Another medicine / advice
      </button>
      <div className="photo-line">
        <PhotoPicker label={photo ? "Retake photo" : "Photo of the prescription"} onFile={setPhoto} busy={busy} />
        {photo && <span className="chip bed-held">✓ Photo ready</span>}
      </div>
      <div className="action-row">
        <button className="primary-btn" disabled={busy} onClick={save}>
          {busy ? "Saving…" : "Save prescription"}
        </button>
        <button className="link-btn" onClick={onCancel}>
          Cancel
        </button>
      </div>
    </div>
  );
}

function VitalsForm({ patientId, kind, referralId, onSaved, onCancel, toast, reasonDefault }) {
  const ranges = useVitalRanges();
  const [values, setValues] = useState({});
  const [reason, setReason] = useState(reasonDefault);
  const [busy, setBusy] = useState(false);
  const save = async () => {
    if (busy) return;
    const vitals = vitalsBody(values);
    if (kind === "VITALS_UPDATE" && !Object.keys(vitals).length) return toast("Enter at least one reading.");
    setBusy(true);
    try {
      const enc = await api.post(`/patients/${patientId}/encounters`, {
        reason: reason.trim() || reasonDefault,
        kind,
        referral_id: referralId || null,
        vitals,
      });
      toast(enc.triage_suggestion || (kind === "HOME_VISIT" ? "Visit recorded" : "Readings saved"));
      onSaved();
    } catch (e) {
      toast(fieldErrors(e));
    } finally {
      setBusy(false);
    }
  };
  return (
    <div className="sub-form reveal">
      <Field label={kind === "HOME_VISIT" ? "How is the patient?" : "Note"} full>
        <input value={reason} onChange={(e) => setReason(e.target.value)} />
      </Field>
      <VitalsGrid values={values} onChange={setValues} ranges={ranges} />
      <div className="action-row">
        <button className="primary-btn" disabled={busy} onClick={save}>
          {kind === "HOME_VISIT" ? "Save visit" : "Save readings"}
        </button>
        <button className="link-btn" onClick={onCancel}>
          Cancel
        </button>
      </div>
    </div>
  );
}

export function DeathForm({ patient, onDone, onCancel, toast }) {
  const now = new Date(Date.now() - new Date().getTimezoneOffset() * 60000).toISOString().slice(0, 16);
  const [cause, setCause] = useState("");
  const [at, setAt] = useState(now);
  const [busy, setBusy] = useState(false);
  const save = async () => {
    if (cause.trim().length < 2 || !at || busy) return;
    if (!window.confirm(`Record the death of ${patient.name}? Every open referral will be stopped.`)) return;
    setBusy(true);
    try {
      await api.post(`/patients/${patient.id}/deceased`, { cause: cause.trim(), died_at: new Date(at).toISOString() });
      toast("Recorded. The referral is stopped and the bed and ambulance released.");
      onDone();
    } catch (e) {
      toast(fieldErrors(e));
    } finally {
      setBusy(false);
    }
  };
  return (
    <div className="sub-form death-form reveal">
      <p>
        <b>Patient died — stop the referral</b>
      </p>
      <div className="form-grid">
        <Field label="Cause of death *" full>
          <input value={cause} onChange={(e) => setCause(e.target.value)} placeholder="as told by the doctor / family" />
        </Field>
        <Field label="Time of death *">
          <input type="datetime-local" value={at} max={now} onChange={(e) => setAt(e.target.value)} />
        </Field>
      </div>
      <div className="action-row">
        <button className="danger-btn" disabled={busy || cause.trim().length < 2} onClick={save}>
          Stop referral · record death
        </button>
        <button className="link-btn" onClick={onCancel}>
          Cancel
        </button>
      </div>
    </div>
  );
}

function ConditionList({ conditions, canEdit, patientId, onChange, toast }) {
  const [adding, setAdding] = useState(false);
  const [name, setName] = useState("");
  const [status, setStatus] = useState("ACTIVE");
  const add = async () => {
    if (!name.trim()) return;
    try {
      await api.post(`/patients/${patientId}/conditions`, { name: name.trim(), status });
      setName("");
      setAdding(false);
      onChange();
    } catch (e) {
      toast(e.message);
    }
  };
  const update = async (c, next) => {
    const note = next === "RESOLVED" ? window.prompt("Note (optional), e.g. 'cured, ultrasound normal'") : "";
    if (note === null) return;
    try {
      await api.patch(`/conditions/${c.id}`, { status: next, note: note || null });
      onChange();
    } catch (e) {
      toast(e.message);
    }
  };
  return (
    <div>
      {conditions.length === 0 && <p className="muted">No illnesses recorded yet.</p>}
      <ul className="condition-list">
        {conditions.map((c) => (
          <li key={c.id} className={`cond cond-${c.status.toLowerCase()}`}>
            <div>
              <b>{c.name}</b> <span className="chip">{c.status === "RESOLVED" ? "Cured / resolved" : pretty(c.status)}</span>
              <small className="cond-trail">
                {c.history.map((h, i) => (
                  <span key={i}>
                    {i > 0 && " → "}
                    {h.status === "RESOLVED" ? "cured" : h.status.toLowerCase()} ({day(h.at)}){h.note ? `: ${h.note}` : ""}
                  </span>
                ))}
              </small>
            </div>
            {canEdit && (
              <span className="care-actions">
                {c.status !== "RESOLVED" && (
                  <button className="link-btn" onClick={() => update(c, "RESOLVED")}>
                    Mark cured
                  </button>
                )}
                {c.status === "RESOLVED" && (
                  <button className="link-btn" onClick={() => update(c, "ACTIVE")}>
                    Came back
                  </button>
                )}
                {c.status === "ACTIVE" && (
                  <button className="link-btn" onClick={() => update(c, "CHRONIC")}>
                    Long-term
                  </button>
                )}
              </span>
            )}
          </li>
        ))}
      </ul>
      {canEdit &&
        (adding ? (
          <div className="inline-form">
            <input value={name} onChange={(e) => setName(e.target.value)} placeholder="e.g. Fatty liver, Diabetes, Anaemia" />
            <select value={status} onChange={(e) => setStatus(e.target.value)}>
              <option value="ACTIVE">Current</option>
              <option value="CHRONIC">Long-term</option>
              <option value="RESOLVED">Had it before (cured)</option>
            </select>
            <button className="primary-btn" onClick={add} disabled={!name.trim()}>
              Add
            </button>
            <button className="link-btn" onClick={() => setAdding(false)}>
              Cancel
            </button>
          </div>
        ) : (
          <button className="secondary-btn" onClick={() => setAdding(true)}>
            ＋ Add illness / condition
          </button>
        ))}
    </div>
  );
}

function PatientDetailsForm({ patient, onSaved, onCancel, toast }) {
  const [f, setF] = useState({
    phone: patient.phone,
    email: patient.email || "",
    address: patient.address || "",
    language: patient.language || "bn",
    reminders: patient.reminders,
  });
  const save = async () => {
    try {
      await api.patch(`/patients/${patient.id}`, {
        phone: f.phone,
        email: f.email.trim() || null,
        address: f.address.trim() || null,
        language: f.language,
        reminders: f.reminders,
      });
      toast("Details saved");
      onSaved();
    } catch (e) {
      toast(fieldErrors(e));
    }
  };
  return (
    <div className="sub-form reveal">
      <div className="form-grid">
        <Field label="Phone">
          <input inputMode="tel" value={f.phone} onChange={(e) => setF({ ...f, phone: e.target.value.replace(/\D/g, "").slice(0, 10) })} />
        </Field>
        <Field label="Email (for reminders, optional)">
          <input type="email" value={f.email} onChange={(e) => setF({ ...f, email: e.target.value })} />
        </Field>
        <Field label="Village / address" full>
          <input value={f.address} onChange={(e) => setF({ ...f, address: e.target.value })} placeholder="para, landmark — also used as ambulance pickup" />
        </Field>
        <Field label="Language for messages">
          <select value={f.language} onChange={(e) => setF({ ...f, language: e.target.value })}>
            {LANGS.map(([k, l]) => (
              <option key={k} value={k}>
                {l}
              </option>
            ))}
          </select>
        </Field>
        <label className="field check-field">
          <input type="checkbox" checked={f.reminders} onChange={(e) => setF({ ...f, reminders: e.target.checked })} />
          <span>Send medicine reminders at dose times</span>
        </label>
      </div>
      <div className="action-row">
        <button className="primary-btn" onClick={save}>
          Save
        </button>
        <button className="link-btn" onClick={onCancel}>
          Cancel
        </button>
      </div>
    </div>
  );
}

// ---------- the whole record ----------

const TABS = [
  ["care", "Medicines & care"],
  ["history", "History"],
  ["vitals", "Vitals"],
  ["referrals", "Referrals"],
];

/** role: WORKER | DOCTOR | FACILITY_STAFF | COORDINATOR | PATIENT */
export function PatientRecordView({ record, role, reload, toast, onReferral, onClose, referralId }) {
  const ranges = useVitalRanges();
  const [tab, setTab] = useState("care");
  const [open, setOpen] = useState(""); // which form is open
  const [busy, setBusy] = useState(false);
  const p = record.patient;
  const asha = role === "WORKER";
  const hospital = role === "DOCTOR" || role === "FACILITY_STAFF";
  const asPatient = role === "PATIENT";
  const alive = !p.deceased_at;
  const latest = record.vitals_history.find((e) => Object.values(e.vitals).some((x) => x !== null));
  const done = () => {
    setOpen("");
    reload();
  };
  const endCare = async (item, status) => {
    const label = status === "COMPLETED" ? "course done" : "stopped";
    if (!window.confirm(`Mark "${item.name}" as ${label}? It leaves the chart and stays in the history.`)) return;
    try {
      await api.post(`/care-items/${item.id}/end`, { status });
      toast(status === "COMPLETED" ? "Course completed" : "Stopped");
      reload();
    } catch (e) {
      toast(e.message);
    }
  };
  const addPhoto = async (file) => {
    setBusy(true);
    try {
      await uploadPhoto(file, "patient", p.id);
      toast("Photo saved");
      reload();
    } catch (e) {
      toast(e.message);
    } finally {
      setBusy(false);
    }
  };
  return (
    <div className="record">
      <div className="record-head">
        <PhotoView id={p.photo_id} asPatient={asPatient} alt={p.name} className="photo-face" />
        <div className="record-id">
          <h3>
            {p.name} {!alive && <span className="chip deceased-chip">Died {day(p.deceased_at)}</span>}
          </h3>
          <p className="muted">
            {p.age} y{p.sex ? ` · ${p.sex}` : ""} · 📞 {p.phone}
            {p.address ? ` · ${p.address}` : ""}
          </p>
          <p className="health-id">
            Health ID <b>{p.health_id}</b>
            {asha && <small> — give this to the patient for the "My health" page</small>}
          </p>
          {record.asha_name && !asha && <p className="muted">ASHA: {record.asha_name}</p>}
          {!alive && <p className="death-note">Cause: {p.death_cause}</p>}
        </div>
        {onClose && (
          <button className="consult-close" onClick={onClose} aria-label="Close">
            ×
          </button>
        )}
      </div>

      {alive && (asha || hospital) && (
        <div className="record-actions">
          {asha && (
            <>
              <button className="primary-btn" onClick={() => onReferral?.(p)}>
                ➜ Make referral
              </button>
              <button className="secondary-btn" onClick={() => setOpen(open === "visit" ? "" : "visit")}>
                🏠 Home visit
              </button>
              <button className="secondary-btn" onClick={() => setOpen(open === "rx" ? "" : "rx")}>
                📝 Prescription
              </button>
              <button className="secondary-btn" onClick={() => setOpen(open === "care" ? "" : "care")}>
                💊 Add medicine / practice
              </button>
            </>
          )}
          <button className="secondary-btn" onClick={() => setOpen(open === "vitals" ? "" : "vitals")}>
            ♥ New readings
          </button>
        </div>
      )}
      {alive && (asha || hospital) && (
        <div className="record-links">
          {asha && (
            <>
              <button className="link-btn" onClick={() => setOpen(open === "details" ? "" : "details")}>
                ✎ Edit details
              </button>
              <PhotoPicker label={p.photo_id ? "New photo" : "Add photo"} onFile={addPhoto} busy={busy} />
            </>
          )}
          <button className="link-btn danger-link" onClick={() => setOpen(open === "death" ? "" : "death")}>
            ✝ Patient died
          </button>
        </div>
      )}
      {open === "visit" && <VitalsForm patientId={p.id} kind="HOME_VISIT" reasonDefault="Routine visit — all OK" onSaved={done} onCancel={() => setOpen("")} toast={toast} />}
      {open === "vitals" && (
        <VitalsForm patientId={p.id} kind="VITALS_UPDATE" referralId={referralId} reasonDefault={hospital ? "After checkup" : "New readings"} onSaved={done} onCancel={() => setOpen("")} toast={toast} />
      )}
      {open === "rx" && <PrescriptionForm patientId={p.id} referrals={record.referrals} onSaved={done} onCancel={() => setOpen("")} toast={toast} />}
      {open === "care" && <CareItemForm patientId={p.id} onSaved={done} onCancel={() => setOpen("")} toast={toast} />}
      {open === "details" && <PatientDetailsForm patient={p} onSaved={done} onCancel={() => setOpen("")} toast={toast} />}
      {open === "death" && <DeathForm patient={p} onDone={done} onCancel={() => setOpen("")} toast={toast} />}

      {latest && (
        <div className="latest-vitals">
          <p className="eyebrow">Latest readings · {when(latest.created_at)}</p>
          <VitalsReadout vitals={latest.vitals} flags={latest.flags} ranges={ranges} />
        </div>
      )}

      <div className="tabs" role="tablist">
        {TABS.map(([k, l]) => (
          <button key={k} role="tab" aria-selected={tab === k} className={tab === k ? "tab active" : "tab"} onClick={() => setTab(k)}>
            {l}
          </button>
        ))}
      </div>

      {tab === "care" && (
        <div className="tab-body">
          <CareChart items={record.care_chart} onEnd={asha && alive ? endCare : null} empty="No medicines or advice on the chart right now." />
          {record.finished_care.length > 0 && (
            <details className="finished">
              <summary>Finished ({record.finished_care.length})</summary>
              <ul>
                {record.finished_care.map((i) => (
                  <li key={i.id}>
                    {i.name} — {i.end_reason?.toLowerCase()} {day(i.ended_at)}
                  </li>
                ))}
              </ul>
            </details>
          )}
        </div>
      )}
      {tab === "history" && (
        <div className="tab-body">
          <h4 className="sub-title">Illnesses and conditions</h4>
          <ConditionList conditions={record.conditions} canEdit={(asha || role === "DOCTOR") && alive} patientId={p.id} onChange={reload} toast={toast} />
          <h4 className="sub-title">Prescriptions</h4>
          {record.prescriptions.length === 0 && <p className="muted">No prescriptions entered yet.</p>}
          {record.prescriptions.map((rx) => (
            <div className="rx-card" key={rx.id}>
              <div>
                <b>{day(rx.prescribed_on)}</b> · {rx.doctor_name || "Doctor"}
                {rx.facility_name ? ` · ${rx.facility_name}` : ""}
                {rx.diagnosis && <p>Diagnosis: {rx.diagnosis}</p>}
                {rx.notes && <p className="muted">{rx.notes}</p>}
                {rx.items.length > 0 && <p className="muted">{rx.items.map((i) => i.name).join(", ")}</p>}
              </div>
              {rx.photo_id && <PhotoView id={rx.photo_id} asPatient={asPatient} alt="Prescription" className="photo-rx" />}
            </div>
          ))}
        </div>
      )}
      {tab === "vitals" && (
        <div className="tab-body">
          {record.vitals_history.filter((e) => Object.values(e.vitals).some((x) => x !== null)).length === 0 && <p className="muted">No readings yet.</p>}
          {record.vitals_history
            .filter((e) => Object.values(e.vitals).some((x) => x !== null))
            .map((e) => (
              <div className="vitals-entry" key={e.id}>
                <p className="muted">
                  {when(e.created_at)} · {pretty(e.kind)}
                  {e.recorded_by_role ? ` · by ${e.recorded_by_role === "WORKER" ? "ASHA" : pretty(e.recorded_by_role)}` : ""} · {e.reason}
                </p>
                <VitalsReadout vitals={e.vitals} flags={e.flags} ranges={ranges} />
              </div>
            ))}
        </div>
      )}
      {tab === "referrals" && (
        <div className="tab-body">
          {record.referrals.length === 0 && <p className="muted">No referrals. Visits with "all OK" need none.</p>}
          {record.referrals.map((r) => (
            <div className="mini-ref" key={r.id}>
              <b>{r.code}</b>
              <span>
                {r.facility_name} · {r.requested_service}
                {r.origin === "PATIENT_EMERGENCY" ? " · 🚨 booked by patient" : ""}
                <br />
                <small>{r.reason}</small>
              </span>
              <small>
                {pretty(r.status)}
                <br />
                {day(r.created_at)}
              </small>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

export function PatientRecord({ patientId, role, toast, onReferral, onClose, referralId }) {
  const [record, setRecord] = useState(null);
  const load = useCallback(() => {
    api
      .get(`/patients/${patientId}/record`)
      .then(setRecord)
      .catch((e) => toast(e.message));
  }, [patientId]);
  useEffect(load, [load]);
  if (!record) return <Skeleton />;
  return <PatientRecordView record={record} role={role} reload={load} toast={toast} onReferral={onReferral} onClose={onClose} referralId={referralId} />;
}

// ---------- the ASHA's register ----------

const NEW_PATIENT = { name: "", age: "", sex: "F", phone: "", address: "", language: "bn", email: "", consent: false };

export function PatientRegister({ toast, onReferral, selectedId, onSelect }) {
  const [rows, setRows] = useState(null);
  const [q, setQ] = useState("");
  const [adding, setAdding] = useState(false);
  const [f, setF] = useState(NEW_PATIENT);
  const [photo, setPhoto] = useState(null);
  const [busy, setBusy] = useState(false);
  const load = useCallback(() => {
    api
      .get(`/patients/register${q.trim() ? `?q=${encodeURIComponent(q.trim())}` : ""}`)
      .then(setRows)
      .catch((e) => toast(e.message));
  }, [q]);
  useEffect(() => {
    const x = setTimeout(load, 250);
    return () => clearTimeout(x);
  }, [load]);
  const valid = f.name.trim() && f.age !== "" && Number(f.age) <= 120 && /^[6-9]\d{9}$/.test(f.phone) && f.consent;
  const add = async () => {
    if (!valid || busy) return;
    setBusy(true);
    try {
      const p = await api.post("/patients", {
        name: f.name.trim(),
        age: Number(f.age),
        sex: f.sex || null,
        phone: f.phone,
        address: f.address.trim() || null,
        language: f.language,
        email: f.email.trim() || null,
        consent_given: true,
      });
      if (photo) await uploadPhoto(photo, "patient", p.id);
      toast(p.possible_duplicate_of ? "Saved. Someone with this name and phone is already on your register." : `Registered · Health ID ${p.health_id}`);
      setF(NEW_PATIENT);
      setPhoto(null);
      setAdding(false);
      load();
      onSelect(p.id);
    } catch (e) {
      toast(fieldErrors(e));
    } finally {
      setBusy(false);
    }
  };
  return (
    <section className="panel register-panel">
      <div className="panel-head">
        <div>
          <p className="eyebrow">My area</p>
          <h3>My patients</h3>
          <p className="muted">Everyone you look after. One person = one record; every referral stays under it.</p>
        </div>
        <button className="primary-btn" onClick={() => setAdding(!adding)}>
          {adding ? "Close" : "＋ Register"}
        </button>
      </div>
      {adding && (
        <div className="sub-form reveal">
          <div className="form-grid">
            <Field label="Name *">
              <input value={f.name} onChange={(e) => setF({ ...f, name: e.target.value })} />
            </Field>
            <Field label="Age *">
              <input inputMode="numeric" value={f.age} onChange={(e) => setF({ ...f, age: e.target.value.replace(/\D/g, "").slice(0, 3) })} />
            </Field>
            <Field label="Sex">
              <select value={f.sex} onChange={(e) => setF({ ...f, sex: e.target.value })}>
                <option value="F">Female</option>
                <option value="M">Male</option>
                <option value="O">Other</option>
              </select>
            </Field>
            <Field label="Mobile *">
              <input inputMode="tel" value={f.phone} onChange={(e) => setF({ ...f, phone: e.target.value.replace(/\D/g, "").slice(0, 10) })} placeholder="10 digits" />
            </Field>
            <Field label="Village / address" full>
              <input value={f.address} onChange={(e) => setF({ ...f, address: e.target.value })} placeholder="para, landmark" />
            </Field>
            <Field label="Language for messages">
              <select value={f.language} onChange={(e) => setF({ ...f, language: e.target.value })}>
                {LANGS.map(([k, l]) => (
                  <option key={k} value={k}>
                    {l}
                  </option>
                ))}
              </select>
            </Field>
            <Field label="Email (optional)">
              <input type="email" value={f.email} onChange={(e) => setF({ ...f, email: e.target.value })} />
            </Field>
            <label className="field full check-field">
              <input type="checkbox" checked={f.consent} onChange={(e) => setF({ ...f, consent: e.target.checked })} />
              <span>The patient agreed to their details being recorded *</span>
            </label>
          </div>
          <div className="photo-line">
            <PhotoPicker label={photo ? "Retake photo" : "Photo (for identification)"} onFile={setPhoto} busy={busy} />
            {photo && <span className="chip bed-held">✓ Photo ready</span>}
          </div>
          <button className="primary-btn" disabled={!valid || busy} onClick={add}>
            {busy ? "Saving…" : "Save patient"}
          </button>
        </div>
      )}
      <div className="search-row">
        <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Search name, phone, Health ID or village" aria-label="Search patients" />
      </div>
      {rows === null ? (
        <Skeleton />
      ) : rows.length === 0 ? (
        <Empty title={q ? "No match" : "No patients yet"} text={q ? "Try another spelling or the phone number." : "Register the people you visit."} />
      ) : (
        <div className="register-list">
          {rows.map((r) => (
            <button key={r.patient.id} className={`register-row ${selectedId === r.patient.id ? "selected" : ""}`} onClick={() => onSelect(r.patient.id)}>
              <PhotoView id={r.patient.photo_id} alt="" className="photo-mini" />
              <span className="register-main">
                <b>
                  {r.patient.name}
                  {r.patient.deceased_at && " †"}
                </b>
                <small>
                  {r.patient.age} y · {r.patient.health_id}
                  {r.patient.address ? ` · ${r.patient.address}` : ""}
                </small>
              </span>
              <span className="register-side">
                {r.open_referral_code ? <span className="chip">{r.open_referral_code}</span> : <small>{r.last_visit_at ? `Visited ${day(r.last_visit_at)}` : "Not visited"}</small>}
                {r.active_medicines > 0 && <small>💊 {r.active_medicines}</small>}
              </span>
            </button>
          ))}
        </div>
      )}
      {selectedId && (
        <div className="record-wrap">
          <PatientRecord key={selectedId} patientId={selectedId} role="WORKER" toast={toast} onReferral={onReferral} onClose={() => onSelect(null)} />
        </div>
      )}
    </section>
  );
}

// ---------- the patient's own page: health record and night emergency ----------

export function PatientHealthPortal({ toast }) {
  const { t } = useLanguage();
  const [signedIn, setSignedIn] = useState(!!patientToken());
  const [code, setCode] = useState("");
  const [last4, setLast4] = useState("");
  const [record, setRecord] = useState(null);
  const [error, setError] = useState("");
  const [emergency, setEmergency] = useState(false);
  const load = useCallback(() => {
    patientApi
      .get("/public/me/record")
      .then(setRecord)
      .catch((e) => {
        if (e.status === 401) {
          patientLogout();
          setSignedIn(false);
        } else toast(e.message);
      });
  }, []);
  useEffect(() => {
    if (signedIn) load();
  }, [signedIn, load]);
  const login = async (e) => {
    e.preventDefault();
    setError("");
    try {
      await patientLogin(code.trim().toUpperCase(), last4);
      setSignedIn(true);
    } catch (err) {
      setError(err.message);
    }
  };
  if (!signedIn)
    return (
      <div className="panel">
        <p className="eyebrow">{t("myHealth")}</p>
        <h3>{t("myHealthTitle")}</h3>
        <p className="muted">{t("myHealthHelp")}</p>
        <form className="lookup" onSubmit={login}>
          <input value={code} onChange={(e) => setCode(e.target.value)} placeholder="HID-XXXXXX" autoCapitalize="characters" aria-label="Health ID" />
          <input value={last4} onChange={(e) => setLast4(e.target.value.replace(/\D/g, "").slice(0, 4))} placeholder={t("phoneLast4")} inputMode="numeric" style={{ maxWidth: 170 }} />
          <button className="primary-btn" type="submit" disabled={!code.trim() || last4.length !== 4}>
            {t("open")}
          </button>
        </form>
        {error && <p className="error-text">{error}</p>}
        <div className="emergency-hint">
          🚨 {t("emergencyNeedsId")} <a href="tel:108">108</a>
        </div>
      </div>
    );
  return (
    <div className="portal">
      <button className="sos-btn" onClick={() => setEmergency(true)}>
        <span>🚨</span>
        <b>{t("emergencyNow")}</b>
        <small>{t("emergencyNowSub")}</small>
      </button>
      {emergency && <EmergencyPanel onClose={() => (setEmergency(false), load())} />}
      <div className="panel">
        {record ? <PatientRecordView record={record} role="PATIENT" reload={load} toast={toast} /> : <Skeleton />}
        <button
          className="link-btn"
          onClick={() => {
            patientLogout();
            setSignedIn(false);
            setRecord(null);
          }}
        >
          {t("signOut")}
        </button>
      </div>
    </div>
  );
}

export function EmergencyPanel({ onClose }) {
  const { t } = useLanguage();
  const [conditions, setConditions] = useState([]);
  const [pick, setPick] = useState("");
  const [note, setNote] = useState("");
  const [pickup, setPickup] = useState("");
  const [where, setWhere] = useState(null);
  const [state, setState] = useState("form"); // form | locating | booking | done
  const [result, setResult] = useState(null);
  const [error, setError] = useState("");
  useEffect(() => {
    patientApi.get("/public/emergency-conditions").then(setConditions).catch(() => {});
    // Where the patient is, for the nearest hospital (asked once; works without it too).
    if (navigator.geolocation) {
      setState("locating");
      navigator.geolocation.getCurrentPosition(
        (pos) => (setWhere({ latitude: pos.coords.latitude, longitude: pos.coords.longitude }), setState("form")),
        () => setState("form"),
        { timeout: 8000, maximumAge: 600000 },
      );
    }
  }, []);
  const book = async () => {
    if (!pick) return;
    setState("booking");
    setError("");
    try {
      const r = await patientApi.post("/public/emergency", { condition: pick, note: note.trim() || null, pickup_note: pickup.trim() || null, ...(where || {}) });
      setResult(r);
      setState("done");
    } catch (e) {
      setError(e.message);
      setState("form");
    }
  };
  const chosen = conditions.find((c) => c.condition === pick);
  return (
    <div className="consult-modal" role="dialog" aria-modal="true">
      <div className="consult-modal-card emergency-card">
        <button className="consult-close" onClick={onClose} aria-label="Close">
          ×
        </button>
        <a className="call-108" href="tel:108">
          📞 {t("call108")}
        </a>
        {state !== "done" ? (
          <>
            <h3>{t("whatHappened")}</h3>
            <div className="emergency-grid">
              {conditions.map((c) => (
                <button key={c.condition} className={pick === c.condition ? "em-choice on" : "em-choice"} onClick={() => setPick(c.condition)}>
                  {t(`em_${c.condition}`) !== `em_${c.condition}` ? t(`em_${c.condition}`) : c.label}
                </button>
              ))}
            </div>
            {chosen && (
              <ul className="precautions">
                {chosen.precautions.map((x) => (
                  <li key={x}>{x}</li>
                ))}
              </ul>
            )}
            <Field label={t("pickupWhere")} full>
              <input value={pickup} onChange={(e) => setPickup(e.target.value)} placeholder={t("pickupPlaceholder")} />
            </Field>
            <Field label={t("anythingElse")} full>
              <input value={note} onChange={(e) => setNote(e.target.value)} />
            </Field>
            <p className="muted">{state === "locating" ? t("findingLocation") : where ? `📍 ${t("locationFound")}` : t("noLocation")}</p>
            {error && <p className="error-text">{error}</p>}
            <button className="danger-btn wide-btn" disabled={!pick || state === "booking"} onClick={book}>
              {state === "booking" ? t("booking") : t("bookHospital")}
            </button>
          </>
        ) : (
          <div className="em-result reveal">
            <p className="eyebrow">{result.already_open ? t("alreadyBooked") : t("booked")}</p>
            <h3>{result.hospital_name}</h3>
            <p>
              {result.service} · {t("code")} <b>{result.referral_code}</b>
            </p>
            {result.hospital_phone && (
              <a className="secondary-btn" href={`tel:${result.hospital_phone}`}>
                📞 {t("callHospital")} {result.hospital_phone}
              </a>
            )}
            <div className="ward-chips">
              {result.bed_held && <span className="chip bed-held">✓ {t("bedHeld")}</span>}
              {result.ambulance_requested && <span className="chip bed-held">🚑 {t("ambulanceAsked")}</span>}
            </div>
            {result.reasons.length > 0 && <p className="muted">{result.reasons.join(" · ")}</p>}
            <ul className="precautions">
              {result.precautions.map((x) => (
                <li key={x}>{x}</li>
              ))}
            </ul>
            <p className="muted">{t("ashaTold")}</p>
          </div>
        )}
      </div>
    </div>
  );
}
