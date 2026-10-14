import React, { useCallback, useEffect, useRef, useState } from "react";
import { createRoot } from "react-dom/client";
import { createPortal } from "react-dom";
import QRCode from "qrcode";
import "./styles.css";
import "./language-sidebar.css";
import {
  api,
  currentUser,
  refreshMe,
  logout,
  newKey,
  patientApi,
  patientLogout,
  patientToken,
  qs,
  request,
} from "./api.js";
import {
  FlagChip,
  EmergencyPanel,
  PatientRecord,
  PatientRecordView,
  PatientRegister,
  PhotoView,
  VitalsGrid,
  VitalsReadout,
  useVitalRanges,
} from "./health.jsx";
import { EntryScreen, JoinScreen, NewCodeCard, PeoplePanel, SCREEN_FOR } from "./entry.jsx";
import { LanguageProvider, LanguageSidebar, errorText, readLS, useLanguage, writeLS } from "./i18n.jsx";
import { TOURS, Tour } from "./tour.jsx";
import { Dashboard, Empty, Field, Skeleton, Stat } from "./ui.jsx";

const ROLES = {
  asha: { label: "ASHA / ANM", icon: "◉", desc: "Field worker coordination" },
  patient: { label: "Patient", icon: "♡", desc: "My referral & care journey" },
  medical: { label: "Medical Team", icon: "✚", desc: "Triage, referrals & outcomes" },
  coordinator: { label: "Coordinator", icon: "◆", desc: "District office & approvals" },
};
const JOURNEY = ["CREATED", "ACCEPTED", "ARRIVAL_RECORDED", "CONSULTED", "OUTCOME_RECORDED", "FOLLOW_UP_DUE", "CLOSED"];
const TRIAGE_KEY = { EMERGENCY: "emergency", PRIORITY: "priority", ROUTINE: "routine" };
const pretty = (s) => (s || "").replaceAll("_", " ");
// Words from the server (statuses, wards, services) shown in the person's language.
const said = (t, prefix, s) => {
  const k = `${prefix}${s}`;
  const v = t(k);
  return v === k ? pretty(s) : v;
};
const statusText = (t, s) => said(t, "st_", s);
const wardText = (t, w) => said(t, "ward_", w);
const serviceText = (t, s) => said(t, "svc_", (s || "").replace(/\W+/g, "_"));
const REFRESH_MS = 30000;

const ESANJEEVANI_URL = "https://esanjeevani.mohfw.gov.in/#/";
const EMERGENCY_NUMBER = "108";
const SERVICES = ["General Medicine", "Emergency", "Maternity", "Paediatrics", "ICU", "Diagnostics"];

// State that survives a page refresh (kept in this browser only). Falls back to plain
// state when storage is blocked, e.g. in a private window.
function usePersisted(key, initial) {
  const [value, setValue] = useState(() => {
    try {
      const raw = localStorage.getItem(key);
      return raw === null ? initial : JSON.parse(raw);
    } catch {
      return initial;
    }
  });
  useEffect(() => {
    try {
      if (value === null || value === undefined) localStorage.removeItem(key);
      else localStorage.setItem(key, JSON.stringify(value));
    } catch {
      /* storage unavailable: keep working in memory */
    }
  }, [key, value]);
  return [value, setValue];
}

const fmtTime = (iso) => (iso ? new Date(iso).toLocaleString([], { dateStyle: "medium", timeStyle: "short" }) : "");

// Re-run `load` now, every 30 seconds while the screen is in view, and as soon as the
// tab comes back into view. A phone in a pocket does not keep fetching.
function usePolling(load) {
  useEffect(() => {
    load();
    const id = setInterval(() => document.visibilityState === "visible" && load(), REFRESH_MS);
    const onFocus = () => document.visibilityState === "visible" && load();
    document.addEventListener("visibilitychange", onFocus);
    return () => {
      clearInterval(id);
      document.removeEventListener("visibilitychange", onFocus);
    };
  }, [load]);
}

function App() {
  const { t } = useLanguage();
  const [session, setSession] = useState(() => {
    const user = currentUser();
    if (user) return { screen: SCREEN_FOR[user.role], user };
    // A patient signed in to their own account on this phone.
    return patientToken() ? { screen: "patient", user: null } : null;
  });
  const [toast, setToastState] = useState("");
  const toastTimer = useRef();
  const setToast = useCallback((msg) => {
    setToastState(msg);
    clearTimeout(toastTimer.current);
    toastTimer.current = setTimeout(() => setToastState(""), 3200);
  }, []);
  const tourKey = session?.screen || "auth";
  const [tourOpen, setTourOpen] = useState(false);
  // The tour opens by itself once per dashboard, never on the start screen: the first
  // thing a new person sees is the three big doors, nothing on top of them.
  const onDashboard = !!session && (session.screen === "patient" || session.user?.approved !== false);
  useEffect(() => {
    if (onDashboard && !readLS(`sahyogcare_tour_${tourKey}`)) {
      const x = setTimeout(() => setTourOpen(true), 600);
      return () => clearTimeout(x);
    }
  }, [tourKey, onDashboard]);
  const closeTour = () => {
    writeLS(`sahyogcare_tour_${tourKey}`, "1");
    setTourOpen(false);
  };
  useEffect(() => {
    const onLogout = () => setSession(null);
    window.addEventListener("sahyog:logout", onLogout);
    return () => window.removeEventListener("sahyog:logout", onLogout);
  }, []);
  // Already logged in on this phone: ask the server once whether a personal code is
  // waiting to be shown (e.g. the office approved this person since the last visit).
  const userId = session?.user?.id;
  useEffect(() => {
    if (!userId) return;
    refreshMe()
      .then(({ new_code, ...user }) => {
        setSession((s) => (s?.user?.id === user.id ? { ...s, user, screen: SCREEN_FOR[user.role], newCode: new_code || s.newCode } : s));
      })
      .catch(() => {});
  }, [userId]);
  const signIn = (s) => {
    window.scrollTo(0, 0); // open the dashboard at its top, not where the sign-in form was scrolled
    setSession(s);
    if (s.user && s.user.approved !== false) setToast(`${t(s.screen)} · ${s.user.name}`);
  };
  const signOut = () => {
    // Drafts belong to the person who wrote them: clear them on this shared phone.
    try {
      Object.keys(localStorage)
        .filter((k) => k.startsWith("sahyog_"))
        .forEach((k) => localStorage.removeItem(k));
    } catch {
      /* storage unavailable */
    }
    logout();
    patientLogout();
    setSession(null);
  };
  if (!session)
    return (
      <>
        <EntryScreen onSignIn={signIn} onTour={() => setTourOpen(true)} />
        <LanguageSidebar />
        <Tour steps={TOURS.auth} open={tourOpen} onClose={closeTour} />
      </>
    );
  if (session.user && session.user.approved === false)
    return (
      <>
        <JoinScreen
          user={session.user}
          onApproved={({ new_code, ...user }) => signIn({ screen: SCREEN_FOR[user.role], user, newCode: new_code })}
          onSignOut={signOut}
        />
        <LanguageSidebar />
      </>
    );
  const newCode = session.newCode;
  return (
    <div className="app-shell">
      <header className="topbar">
        <div className="brand">
          <div className="brand-mark">स</div>
          <div>
            <strong>SahyogCare</strong>
            <span>{t("tagline")}</span>
          </div>
        </div>
        <div className="session">
          <button className="help-btn" data-tour="help" onClick={() => setTourOpen(true)} aria-label={t("appTour")} title={t("appTour")}>
            ?
          </button>
          <span className="role-pill">
            {ROLES[session.screen].icon} {t(session.screen)}
          </span>
          {session.user && (
            <span className="email">
              {session.user.email || session.user.phone} · {session.user.district}
            </span>
          )}
          <button className="ghost-btn" onClick={signOut}>
            {t("signOut")}
          </button>
        </div>
      </header>
      <main className="page page-fade" key={session.screen}>
        {session.screen === "asha" && <AshaDashboard toast={setToast} />}
        {session.screen === "patient" && <PatientHome toast={setToast} onSignOut={signOut} />}
        {session.screen === "medical" && <MedicalDashboard user={session.user} toast={setToast} />}
        {session.screen === "coordinator" && <CoordinatorDashboard user={session.user} toast={setToast} />}
      </main>
      {toast && (
        <div className="toast" key={toast} role="status">
          <span className="toast-icon">✓</span>
          {toast}
        </div>
      )}
      <LanguageSidebar />
      {newCode ? (
        <NewCodeCard code={newCode} onDone={() => setSession((s) => ({ ...s, newCode: null }))} />
      ) : (
        <Tour steps={TOURS[session.screen]} open={tourOpen} onClose={closeTour} />
      )}
    </div>
  );
}

// ---------- Coordinator ----------

const ROLE_LABEL_KEY = { WORKER: "roleAsha", FACILITY_STAFF: "roleStaff", DOCTOR: "roleDoctor" };

function CoordinatorDashboard({ user, toast }) {
  const { t } = useLanguage();
  const [requests, setRequests] = useState(null);
  const [facilities, setFacilities] = useState(null);
  const [busyId, setBusyId] = useState(null);

  const load = useCallback(async () => {
    try {
      const [reqs, facs] = await Promise.all([api.get("/access-requests"), api.get("/facilities")]);
      setRequests(reqs);
      setFacilities(facs);
    } catch (e) {
      if (e.status !== 401) toast(errorText(t, e));
    }
  }, [toast]);
  usePolling(load);

  const decide = async (r, action) => {
    setBusyId(r.id);
    try {
      await api.post(`/access-requests/${r.id}/${action}`);
      toast(`${r.name} · ${action === "approve" ? t("approvedToast") : t("rejectedToast")}`);
      setRequests((list) => (list || []).filter((x) => x.id !== r.id));
    } catch (e) {
      toast(errorText(t, e));
      load();
    } finally {
      setBusyId(null);
    }
  };

  const wards = (facilities || []).flatMap((f) => f.wards || []);
  return (
    <Dashboard
      title={`${user?.district || ""} ${t("coordinatorDashboard")}`.trim()}
      subtitle={`${t("coordinatorSub")} ${t("youSeeOnly")} ${user?.district || ""}.`}
    >
      <div className="stats">
        <Stat tour="stats" label={t("waitingApproval")} value={requests ? requests.length : "–"} meta={t("peopleAsked")} />
        <Stat label={t("hospitals")} value={facilities ? facilities.length : "–"} meta={t("inYourDistrict")} />
        <Stat
          label={t("freeBeds")}
          value={facilities ? wards.reduce((n, w) => n + w.free, 0) : "–"}
          meta={`${t("ofReported")} ${wards.reduce((n, w) => n + w.total, 0)}`}
        />
      </div>
      <section className="panel" data-tour="requests">
        <div className="panel-head">
          <div>
            <p className="eyebrow">{t("accessEyebrow")}</p>
            <h3>{t("whoWantsJoin")}</h3>
          </div>
        </div>
        {requests === null ? (
          <Skeleton />
        ) : requests.length === 0 ? (
          <Empty title={t("noOneWaiting")} text={t("noOneWaitingSub")} />
        ) : (
          <div className="queue">
            {requests.map((r) => (
              <div className="queue-item" key={r.id}>
                <div className="request-who">
                  <PhotoView id={r.photo_id} alt={r.name} className="photo-face" />
                  <div>
                  <span className="status-badge">{ROLE_LABEL_KEY[r.requested_role] ? t(ROLE_LABEL_KEY[r.requested_role]) : pretty(r.requested_role)}</span>
                  <h4>{r.name}</h4>
                  {!r.photo_id && r.requested_role === "WORKER" && <small className="muted">{t("noPhotoYet")}</small>}
                  <p>
                    {r.email || r.phone}
                    {r.facility_name ? ` · ${r.facility_name}` : ""}
                    {r.note ? ` · ${r.note}` : ""}
                  </p>
                  </div>
                </div>
                <div className="queue-actions">
                  <button className="secondary-btn" disabled={busyId === r.id} onClick={() => decide(r, "reject")}>
                    {t("reject")}
                  </button>
                  <button className="primary-btn" disabled={busyId === r.id} onClick={() => decide(r, "approve")}>
                    {t("approve")}
                  </button>
                </div>
              </div>
            ))}
          </div>
        )}
      </section>
      <PeoplePanel me={user} facilities={facilities} toast={toast} />
      <HospitalsPanel facilities={facilities} toast={toast} onChange={load} />
    </Dashboard>
  );
}

const WARDS = ["GENERAL", "EMERGENCY", "MATERNITY", "PAEDIATRIC", "ICU"];

function HospitalsPanel({ facilities, toast, onChange }) {
  const { t } = useLanguage();
  const [open, setOpen] = useState(null); // hospital id being managed
  const [adding, setAdding] = useState(false);
  const [bed, setBed] = useState({ ward: "GENERAL", total: "", occupied: "" });
  const [service, setService] = useState("");
  const [busy, setBusy] = useState(false);
  const blank = { name: "", type: "Rural Hospital", address: "", pincode: "", phone: "", services: "General Medicine", source: "" };
  const [form, setForm] = useState(blank);
  const set = (k) => (e) => setForm((f) => ({ ...f, [k]: e.target.value }));

  const run = async (fn, done) => {
    setBusy(true);
    try {
      await fn();
      toast(done);
      onChange();
    } catch (e) {
      toast(errorText(t, e));
    } finally {
      setBusy(false);
    }
  };
  const saveBeds = (f) =>
    run(
      () => request("PUT", `/facilities/${f.id}/beds/${bed.ward}`, { total: Number(bed.total), occupied: Number(bed.occupied) }),
      `${f.name}: ${wardText(t, bed.ward)} · ${t("bedsSaved")}`,
    );
  const addService = (f) =>
    run(() => request("PATCH", `/facilities/${f.id}`, { add_services: [service.trim()] }), `${service.trim()} · ${t("added")}`).then(() =>
      setService(""),
    );
  const toggleAmbulance = (f) =>
    run(() => request("PATCH", `/facilities/${f.id}`, { has_ambulance: !f.has_ambulance }), t("ambulanceUpdated"));
  const addHospital = () =>
    run(
      () =>
        api.post("/facilities", {
          name: form.name.trim(),
          type: form.type.trim(),
          address: form.address.trim() || null,
          pincode: form.pincode.trim() || null,
          phone: form.phone.trim() || null,
          source: form.source.trim() || null,
          services: form.services.split(",").map((x) => x.trim()).filter(Boolean),
        }),
      `${form.name.trim()} · ${t("added")}`,
    ).then(() => {
      setForm(blank);
      setAdding(false);
    });

  const bedsValid = bed.total !== "" && bed.occupied !== "" && Number(bed.occupied) <= Number(bed.total);
  return (
    <section className="panel" data-tour="beds" style={{ marginTop: 18 }}>
      <div className="panel-head">
        <div>
          <p className="eyebrow">{t("hospitalsBeds")}</p>
          <h3>{t("hospitalsInDistrict")}</h3>
        </div>
        <button className="secondary-btn" onClick={() => setAdding((x) => !x)}>
          {adding ? t("close") : `+ ${t("addHospital")}`}
        </button>
      </div>
      {adding && (
        <div className="form-grid" style={{ marginBottom: 16 }}>
          <Field label={t("name")}>
            <input value={form.name} onChange={set("name")} placeholder="Karimpur Rural Hospital" />
          </Field>
          <Field label={t("hospitalType")}>
            <input value={form.type} onChange={set("type")} />
          </Field>
          <Field label={t("address")} full>
            <input value={form.address} onChange={set("address")} />
          </Field>
          <Field label={t("pinCode")}>
            <input inputMode="numeric" maxLength="6" value={form.pincode} onChange={set("pincode")} />
          </Field>
          <Field label={t("phone")}>
            <input inputMode="tel" value={form.phone} onChange={set("phone")} />
          </Field>
          <Field label={t("servicesComma")} full>
            <input value={form.services} onChange={set("services")} />
          </Field>
          <Field label={t("detailsSource")} full>
            <input value={form.source} onChange={set("source")} placeholder="nadia.gov.in" />
          </Field>
          <div className="action-row" style={{ gridColumn: "1/-1" }}>
            <button
              className="primary-btn"
              disabled={busy || form.name.trim().length < 2 || !form.services.trim() || (form.pincode && !/^\d{6}$/.test(form.pincode))}
              onClick={addHospital}
            >
              {t("saveHospital")}
            </button>
          </div>
        </div>
      )}
      {facilities === null ? (
        <Skeleton />
      ) : (
        <div className="queue">
          {facilities.map((f) => (
            <div className="queue-item" key={f.id} style={{ flexDirection: "column", alignItems: "stretch" }}>
              <div style={{ display: "flex", justifyContent: "space-between", gap: 12 }}>
                <div>
                  <h4>{f.name}</h4>
                  <p>
                    {f.type}
                    {f.address ? ` · ${f.address}` : ""}
                    {f.pincode ? ` ${f.pincode}` : ""}
                  </p>
                  <p>
                    {f.phone ? <a href={`tel:${f.phone}`}>{f.phone}</a> : t("noPhoneYet")}
                    {f.has_ambulance ? ` · ${t("hasAmbulance")}` : ""}
                    {f.source ? ` · ${t("source")}: ${f.source}` : ""}
                  </p>
                  <div className="ward-chips">
                    {(f.services || []).map((s) => (
                      <span key={s.service} className="step-chip">
                        {serviceText(t, s.service)}
                      </span>
                    ))}
                  </div>
                  <div className="ward-chips">
                    {(f.wards || []).length === 0 ? (
                      <span className="step-chip">{t("noBedData")}</span>
                    ) : (
                      f.wards.map((w) => (
                        <span key={w.ward} className="step-chip" title={w.stale ? t("notConfirmed12h") : ""}>
                          {wardText(t, w.ward)}: <b>{w.free}</b> {t("freeOf")} {w.total}
                          {w.stale ? ` · ${t("old")}` : ""}
                        </span>
                      ))
                    )}
                  </div>
                </div>
                <div className="queue-actions" style={{ alignSelf: "flex-start" }}>
                  <button className="secondary-btn" onClick={() => setOpen(open === f.id ? null : f.id)}>
                    {open === f.id ? t("done") : t("manage")}
                  </button>
                </div>
              </div>
              {open === f.id && (
                <div className="form-grid" style={{ marginTop: 12 }}>
                  <Field label={t("ward")}>
                    <select value={bed.ward} onChange={(e) => setBed((b) => ({ ...b, ward: e.target.value }))}>
                      {WARDS.map((w) => (
                        <option key={w} value={w}>
                          {wardText(t, w)}
                        </option>
                      ))}
                    </select>
                  </Field>
                  <Field label={t("totalOccupied")}>
                    <div style={{ display: "flex", gap: 8 }}>
                      <input inputMode="numeric" placeholder={t("total")} value={bed.total}
                        onChange={(e) => setBed((b) => ({ ...b, total: e.target.value.replace(/\D/g, "") }))} />
                      <input inputMode="numeric" placeholder={t("occupied")} value={bed.occupied}
                        onChange={(e) => setBed((b) => ({ ...b, occupied: e.target.value.replace(/\D/g, "") }))} />
                    </div>
                  </Field>
                  <div className="action-row" style={{ gridColumn: "1/-1", marginTop: 0 }}>
                    <button className="primary-btn" disabled={!bedsValid || busy} onClick={() => saveBeds(f)}>
                      {t("saveBeds")}
                    </button>
                    <button className="secondary-btn" disabled={busy} onClick={() => toggleAmbulance(f)}>
                      {f.has_ambulance ? t("markNoAmbulance") : t("markHasAmbulance")}
                    </button>
                  </div>
                  <Field label={t("addServiceLabel")} full>
                    <div style={{ display: "flex", gap: 8 }}>
                      <input value={service} onChange={(e) => setService(e.target.value)} placeholder="Maternity" />
                      <button className="secondary-btn" disabled={!service.trim() || busy} onClick={() => addService(f)}>
                        {t("add")}
                      </button>
                    </div>
                  </Field>
                </div>
              )}
            </div>
          ))}
        </div>
      )}
    </section>
  );
}

// ---------- Shared pieces: emergency, teleconsult, beds, ambulance, re-routing ----------

function EmergencyBox({ compact }) {
  const { t } = useLanguage();
  return (
    <div className={`emergency-box ${compact ? "compact" : ""}`} role="note">
      <span className="emergency-dot" aria-hidden="true" />
      <div>
        <b>{t("emergencyAmbulance")}: {EMERGENCY_NUMBER}</b>
        {!compact && <small>{t("emergencyAmbulanceSub")}</small>}
      </div>
      <a className="secondary-btn" href={`tel:${EMERGENCY_NUMBER}`}>
        {t("call")} {EMERGENCY_NUMBER}
      </a>
    </div>
  );
}

function ESanjeevaniCard({ summary, toast }) {
  const { t } = useLanguage();
  const [open, setOpen] = useState(false);
  const copySummary = async () => {
    if (!summary) return;
    try {
      await navigator.clipboard.writeText(summary);
      toast?.(t("summaryCopied"));
    } catch {
      toast?.(summary);
    }
  };
  return (
    <>
      <section className="teleconsult-card" data-tour="consult">
        <div className="teleconsult-icon">✚</div>
        <div className="teleconsult-copy">
          <p className="eyebrow">eSanjeevani</p>
          <h3>{t("teleconsultTitle")}</h3>
          <p>{t("teleconsultText")}</p>
        </div>
        <button className="primary-btn" onClick={() => setOpen(true)}>
          {t("startConsult")} →
        </button>
      </section>
      {open &&
        createPortal(
          <div className="consult-modal" role="dialog" aria-modal="true" onClick={(e) => e.target === e.currentTarget && setOpen(false)}>
            <div className="consult-modal-card">
              <button className="consult-close" onClick={() => setOpen(false)} aria-label={t("close")}>
                ×
              </button>
              <div className="teleconsult-icon large">✚</div>
              <p className="eyebrow">eSanjeevani · Ministry of Health</p>
              <h3>{t("teleconsultTitle")}</h3>
              <p className="muted">{t("teleconsultSoon")}</p>
              {summary && (
                <button className="secondary-btn" style={{ width: "100%", marginTop: 8 }} onClick={copySummary}>
                  {t("copySummary")}
                </button>
              )}
              <a className="primary-btn link-as-btn" href={ESANJEEVANI_URL} target="_blank" rel="noopener noreferrer"
                onClick={() => setOpen(false)}>
                {t("goTo")} esanjeevani.mohfw.gov.in ↗
              </a>
            </div>
          </div>,
          document.body,
        )}
    </>
  );
}

function BedChip({ bed }) {
  const { t } = useLanguage();
  if (!bed) return <span className="chip muted-chip">{t("noBedHeld")}</span>;
  const ward = wardText(t, bed.ward);
  return (
    <span className={`chip bed-${bed.status.toLowerCase()}`} title={bed.release_reason || ""}>
      {t(`bed_${bed.status}`)} · {ward}
      {bed.status === "HELD" ? ` · ${t("until")} ${new Date(bed.held_until).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}` : ""}
    </span>
  );
}

function RecommendationRow({ r, picked, onPick }) {
  const { t } = useLanguage();
  const beds =
    r.ward === null ? t("noBedNeeded") : r.beds_free === null ? t("noBedData") : `${r.beds_free}/${r.beds_total} ${t("free")}`;
  const tone = r.ward === null || r.beds_free === null ? "" : r.beds_free > 0 ? "good" : "bad";
  return (
    <button className={`facility ${picked ? "picked" : ""}`} onClick={() => onPick(r)}>
      <div style={{ minWidth: 0 }}>
        <b>{r.facility_name}</b>
        <span>
          {r.facility_type}
          {r.phone ? ` · ☎ ${r.phone}` : ""}
          {r.has_ambulance ? ` · ${t("ambulance")}` : ""}
        </span>
        <small className="spec-chips">
          {r.reasons.slice(0, 3).map((x) => (
            <i key={x}>{x}</i>
          ))}
        </small>
      </div>
      <strong className={`beds-pill ${tone}`}>{beds}</strong>
    </button>
  );
}

function RerouteFinder({ referral, onDone, toast }) {
  const { t } = useLanguage();
  const [alts, setAlts] = useState(null);
  const [busy, setBusy] = useState(false);
  useEffect(() => {
    api.get(`/referrals/${referral.id}/alternatives`).then(setAlts).catch((e) => toast(errorText(t, e)));
  }, [referral.id]);
  const send = async (alt, allow = false) => {
    setBusy(true);
    try {
      const fresh = await api.post(`/referrals/${referral.id}/reroute`, {
        destination_facility_id: alt.facility_id,
        allow_without_bed: allow,
      });
      toast(`${alt.facility_name} · ${t("newCode")} ${fresh.code}`);
      onDone(fresh);
    } catch (e) {
      if (e.code === "NO_BEDS_AVAILABLE") toast(`${alt.facility_name}: ${t("noFreeBedPick")}`);
      else toast(errorText(t, e));
    } finally {
      setBusy(false);
    }
  };
  if (alts === null) return <Skeleton />;
  if (alts.length === 0) return <Empty title={t("noOtherHospital")} text={t("callOffice")} />;
  return (
    <div className="facility-list reveal">
      {alts.map((a) => (
        <div key={a.facility_id} className="alt-row">
          <RecommendationRow r={a} onPick={() => send(a)} />
          {a.beds_free === 0 && (
            <button className="link-btn" disabled={busy} onClick={() => send(a, true)}>
              {t("sendAnyway")}
            </button>
          )}
        </div>
      ))}
    </div>
  );
}

function AmbulanceInfo({ amb }) {
  const { t } = useLanguage();
  if (!amb) return null;
  return (
    <div className={`amb-card amb-${amb.status.toLowerCase()}`}>
      <b>🚑 {t(`amb_${amb.status}`)}</b>
      <small>
        {amb.expected_at && amb.status === "DISPATCHED" ? `${t("expected")} ${fmtTime(amb.expected_at)}` : ""}
        {amb.vehicle_number ? ` · ${amb.vehicle_number}` : ""}
        {amb.driver_phone ? ` · ${t("driver")} ${amb.driver_phone}` : ""}
        {amb.cancel_reason ? ` · ${amb.cancel_reason}` : ""}
      </small>
    </div>
  );
}

// ASHA: ask the hospital for its ambulance, see it coming, or fall back to 108.
function AshaAmbulance({ referral, onChange, toast }) {
  const { t } = useLanguage();
  const [pickup, setPickup] = usePersisted(`sahyog_pickup_${referral.id}`, "");
  const [busy, setBusy] = useState(false);
  const amb = referral.ambulance;
  const open = amb && ["REQUESTED", "DISPATCHED", "PICKED_UP"].includes(amb.status);
  const canAsk = ["CREATED", "ACCEPTED"].includes(referral.status) && !open;
  const run = async (fn, ok) => {
    setBusy(true);
    try {
      onChange(await fn());
      toast(ok);
    } catch (e) {
      toast(e.code === "NO_HOSPITAL_AMBULANCE" ? `${referral.facility.name}: ${t("noAmbulanceCall")} ${EMERGENCY_NUMBER}` : errorText(t, e));
    } finally {
      setBusy(false);
    }
  };
  return (
    <div className="amb-block">
      <AmbulanceInfo amb={amb} />
      {canAsk && (
        <div className="inline-form">
          <input value={pickup} onChange={(e) => setPickup(e.target.value)} placeholder={t("pickupPlaceholderAsha")} />
          <button
            className="secondary-btn"
            disabled={busy || pickup.trim().length < 3}
            onClick={() => run(() => api.post(`/referrals/${referral.id}/ambulance`, { pickup_note: pickup.trim() }), t("amb_REQUESTED"))}
          >
            {t("requestAmbulance")}
          </button>
        </div>
      )}
      {amb?.status === "DISPATCHED" && (
        <button className="secondary-btn" disabled={busy}
          onClick={() => run(() => api.post(`/referrals/${referral.id}/ambulance/picked-up`), t("markedPickedUp"))}>
          {t("patientInAmbulance")}
        </button>
      )}
      {referral.is_open && ["CREATED", "ACCEPTED"].includes(referral.status) && <EmergencyBox compact />}
    </div>
  );
}

// Hospital desk: keep this hospital's beds current.
function StaffBedsPanel({ facilityId, toast }) {
  const { t } = useLanguage();
  const [facility, setFacility] = useState(null);
  const [bed, setBed] = usePersisted("sahyog_staff_bed_form", { ward: "GENERAL", total: "", occupied: "" });
  const [busy, setBusy] = useState(false);
  const load = useCallback(async () => {
    try {
      setFacility(await api.get(`/facilities/${facilityId}`));
    } catch (e) {
      if (e.status !== 401) toast(errorText(t, e));
    }
  }, [facilityId, toast]);
  usePolling(load);
  const save = async () => {
    setBusy(true);
    try {
      setFacility(
        await request("PUT", `/facilities/${facilityId}/beds/${bed.ward}`, {
          total: Number(bed.total),
          occupied: Number(bed.occupied),
        }),
      );
      toast(`${wardText(t, bed.ward)} · ${t("bedsSaved")}`);
    } catch (e) {
      toast(errorText(t, e));
    } finally {
      setBusy(false);
    }
  };
  const valid = bed.total !== "" && bed.occupied !== "" && Number(bed.occupied) <= Number(bed.total);
  return (
    <section className="panel" data-tour="beds" style={{ marginBottom: 18 }}>
      <div className="panel-head">
        <div>
          <p className="eyebrow">{t("beds")}</p>
          <h3>{facility ? facility.name : t("yourHospital")}</h3>
        </div>
      </div>
      <div className="ward-chips" style={{ marginBottom: 14 }}>
        {facility === null ? (
          <span className="chip muted-chip">{t("loading")}</span>
        ) : facility.wards.length === 0 ? (
          <span className="chip muted-chip">{t("noBedsYet")}</span>
        ) : (
          facility.wards.map((w) => (
            <span key={w.ward} className={`chip ${w.free > 0 ? "bed-held" : "bed-expired"}`} title={w.stale ? t("notConfirmed12h") : ""}>
              {wardText(t, w.ward)}: <b>{w.free}</b> {t("free")} · {w.held} {t("held")} · {w.occupied}/{w.total} {t("occupied")}
              {w.stale ? ` · ${t("pleaseConfirm")}` : ""}
            </span>
          ))
        )}
      </div>
      <div className="form-grid">
        <Field label={t("ward")}>
          <select id="staff-ward" value={bed.ward} onChange={(e) => setBed({ ...bed, ward: e.target.value })}>
            {WARDS.map((w) => (
              <option key={w} value={w}>
                {wardText(t, w)}
              </option>
            ))}
          </select>
        </Field>
        <Field label={t("totalOccupied")}>
          <div style={{ display: "flex", gap: 8 }}>
            <input id="staff-total" inputMode="numeric" placeholder={t("total")} value={bed.total}
              onChange={(e) => setBed({ ...bed, total: e.target.value.replace(/\D/g, "") })} />
            <input id="staff-occupied" inputMode="numeric" placeholder={t("occupied")} value={bed.occupied}
              onChange={(e) => setBed({ ...bed, occupied: e.target.value.replace(/\D/g, "") })} />
          </div>
        </Field>
      </div>
      <div className="action-row">
        <button className="primary-btn" disabled={!valid || busy} onClick={save}>
          {t("saveBeds")}
        </button>
      </div>
    </section>
  );
}

// ---------- ASHA ----------

// patientId is set when the referral is for someone already on the ASHA's register.
const EMPTY_FORM = { name: "", age: "", phone: "", triage: "PRIORITY", symptom: "", consent: false, patientId: null };

function AshaDashboard({ toast }) {
  const { t } = useLanguage();
  // Everything the ASHA is in the middle of survives a refresh or a dropped connection.
  const [view, setView] = usePersisted("sahyog_asha_view", "patients"); // patients | referral
  const [patientSel, setPatientSel] = usePersisted("sahyog_asha_patient", null);
  const [step, setStep] = usePersisted("sahyog_asha_step", 0);
  const [form, setForm] = usePersisted("sahyog_asha_form", EMPTY_FORM);
  const [current, setCurrent] = usePersisted("sahyog_asha_current", null); // { patient, encounter }
  const [service, setService] = usePersisted("sahyog_asha_service", "General Medicine");
  const [referralId, setReferralId] = usePersisted("sahyog_asha_referral", null);
  const [facilities, setFacilities] = useState([]);
  const [loadingFacilities, setLoadingFacilities] = useState(false);
  const [search, setSearch] = useState("");
  const [selected, setSelected] = useState(null);
  const [referral, setReferralState] = useState(null);
  const [noBeds, setNoBeds] = useState(null); // { message, alternatives } when the chosen ward is full
  const [rerouting, setRerouting] = useState(false);
  const setReferral = (r) => {
    setReferralState(r);
    setReferralId(r ? r.id : null);
  };
  const [qr, setQr] = useState("");
  const [qrText, setQrText] = useState("");
  const [followUps, setFollowUps] = useState([]);
  const [referrals, setReferrals] = useState(null);
  const [alerts, setAlerts] = useState([]);
  const [busy, setBusy] = useState(false);
  const fail = (e) => toast(errorText(t, e));

  const readReferralId = () => {
    try {
      return JSON.parse(localStorage.getItem("sahyog_asha_referral") || "null");
    } catch {
      return null;
    }
  };
  const load = useCallback(async () => {
    try {
      const [refs, notes, fus] = await Promise.all([
        api.get("/referrals"),
        api.get("/notifications?unread=true"),
        api.get("/follow-ups"),
      ]);
      setReferrals(refs);
      setAlerts(notes);
      setFollowUps(fus);
      setReferralState((r) => {
        const id = r?.id || readReferralId();
        return id ? refs.find((x) => x.id === id) || r : r;
      });
    } catch (e) {
      if (e.status !== 401) fail(e);
    }
  }, []);
  usePolling(load);

  // Hospitals for the needed service, best first (free beds, recent answers, distance).
  useEffect(() => {
    if (step !== 1 || !service) return;
    setLoadingFacilities(true);
    api
      .get(`/facilities/recommend${qs({ service, limit: 30 })}`)
      .then(setFacilities)
      .catch(fail)
      .finally(() => setLoadingFacilities(false));
  }, [step, service]);
  const shown = facilities.filter((f) => f.facility_name.toLowerCase().includes(search.trim().toLowerCase()));

  useEffect(() => {
    if (!referral?.is_open) {
      setQr("");
      setQrText("");
      return;
    }
    let alive = true;
    api
      .get(`/referrals/${referral.id}/pass`)
      .then((p) => {
        if (alive) setQrText(p.qr_text);
        return QRCode.toDataURL(p.qr_text, { margin: 1, width: 220 });
      })
      .then((url) => alive && setQr(url))
      .catch(() => alive && setQr(""));
    return () => {
      alive = false;
    };
  }, [referral?.id, referral?.is_open]);

  const formValid =
    !!form.patientId ||
    (form.name.trim() && form.age !== "" && Number(form.age) <= 120 && /^[6-9]\d{9}$/.test(form.phone) && form.consent);

  const submit = async () => {
    if (!formValid || busy) return;
    setBusy(true);
    try {
      // Someone already on the register keeps their one record; only new people are registered.
      const patient = form.patientId
        ? await api.get(`/patients/${form.patientId}`)
        : await api.post("/patients", {
            name: form.name.trim(),
            age: Number(form.age),
            phone: form.phone,
            consent_given: true,
          });
      const encounter = await api.post(`/patients/${patient.id}/encounters`, {
        reason: form.symptom.trim() || "Referral",
        triage: form.triage,
        kind: "REFERRAL",
      });
      setCurrent({ patient, encounter });
      setStep(1);
      toast(patient.possible_duplicate_of ? t("savedDuplicate") : t("caseSaved"));
    } catch (e) {
      fail(e);
    } finally {
      setBusy(false);
    }
  };

  const pickFacility = (f) => {
    setSelected(f);
    setNoBeds(null);
  };

  const createReferral = async (allowWithoutBed = false, target = selected) => {
    if (!target || !service || !current?.encounter || busy) return;
    setBusy(true);
    try {
      const r = await api.post(
        "/referrals",
        {
          patient_id: current.patient.id,
          encounter_id: current.encounter.id,
          destination_facility_id: target.facility_id,
          requested_service: target.service || service,
          allow_without_bed: allowWithoutBed,
        },
        { headers: { "Idempotency-Key": newKey() } },
      );
      setReferral(r);
      setNoBeds(null);
      setStep(2);
      toast(r.bed ? `${t("referralSent")} · ${t("bed_HELD")}` : t("referralSent"));
      load();
    } catch (e) {
      if (e.code === "NO_BEDS_AVAILABLE") setNoBeds({ message: e.message, alternatives: e.details.alternatives || [] });
      else fail(e);
    } finally {
      setBusy(false);
    }
  };

  // "Make referral" from the register: the referral goes under that patient's record.
  const referFrom = (p) => {
    newCase();
    setForm({ ...EMPTY_FORM, patientId: p.id, name: p.name, age: String(p.age), phone: p.phone, consent: true });
    setView("referral");
    window.scrollTo({ top: 0, behavior: "smooth" });
  };

  const newCase = () => {
    setForm(EMPTY_FORM);
    setCurrent(null);
    setSelected(null);
    setService("General Medicine");
    setSearch("");
    setFacilities([]);
    setReferral(null);
    setNoBeds(null);
    setRerouting(false);
    setStep(0);
  };

  const openReferral = (r) => {
    setReferral(r);
    setRerouting(false);
    setCurrent({ patient: r.patient, encounter: null });
    setStep(2);
  };

  const copyPass = async () => {
    try {
      await navigator.clipboard.writeText(qrText);
      toast(t("passCopied"));
    } catch {
      toast(qrText);
    }
  };

  const followUp = referral && followUps.find((f) => f.referral_id === referral.id);
  const finishFollowUp = async (kind) => {
    if (!followUp || busy) return;
    setBusy(true);
    try {
      await api.post(`/follow-ups/${followUp.id}/${kind}`);
      toast(kind === "sent" ? t("followUpSentToast") : t("followUpMissedToast"));
      const fresh = await api.get(`/referrals/${referral.id}`);
      setReferral(fresh);
      load();
    } catch (e) {
      fail(e);
    } finally {
      setBusy(false);
    }
  };

  const readAlert = async (n) => {
    try {
      await api.post(`/notifications/${n.id}/read`);
      setAlerts((a) => a.filter((x) => x.id !== n.id));
    } catch (e) {
      fail(e);
    }
  };

  const today = new Date().toDateString();
  const list = referrals || [];
  const casesToday = list.filter((r) => new Date(r.created_at).toDateString() === today).length;

  return (
    <Dashboard title={t("ashaDashboard")} subtitle={t("ashaSub")}>
      <div className="stats">
        <Stat tour="stats" label={t("casesToday")} value={casesToday} meta={t("noHidden")} />
        <Stat label={t("openReferrals")} value={list.filter((r) => r.is_open).length} meta={t("updatedShared")} />
        <Stat label={t("alerts")} value={alerts.length} meta={t("alertsMeta")} />
      </div>
      <div className="view-tabs" role="tablist">
        <button role="tab" aria-selected={view === "patients"} className={view === "patients" ? "tab active" : "tab"} onClick={() => setView("patients")}>
          👥 {t("myPatients")}
        </button>
        <button role="tab" aria-selected={view === "referral"} className={view === "referral" ? "tab active" : "tab"} onClick={() => setView("referral")}>
          ➜ {t("referralTab")}{referral?.is_open ? ` · ${referral.code}` : ""}
        </button>
      </div>
      {view === "patients" && (
        <>
          {alerts.length > 0 && (
            <section className="panel alerts-strip">
              {alerts.slice(0, 4).map((n) => (
                <div className="mini-ref" key={n.id} role="button" tabIndex={0} onClick={() => readAlert(n)} title={t("markRead")}>
                  <b>🔔</b>
                  <span>{n.message}</span>
                  <small>{new Date(n.created_at).toLocaleTimeString()}</small>
                </div>
              ))}
            </section>
          )}
          <PatientRegister toast={toast} onReferral={referFrom} selectedId={patientSel} onSelect={setPatientSel} />
        </>
      )}
      {view === "referral" && (
      <>
      <section className="feature-grid">
        <div className="panel wide" data-tour="intake">
          <div className="panel-head">
            <div>
              <p className="eyebrow">{t("newReferralEyebrow")}</p>
              <h3>{t("patientIntake")}</h3>
            </div>
            <span className="step-chip">
              {t("step")} {step + 1}/3
            </span>
          </div>
          <div className="step-progress" aria-hidden="true">
            <i style={{ width: `${((step + 1) / 3) * 100}%` }} />
          </div>
          {step === 0 && form.patientId && (
            <div className="known-patient">
              <b>{form.name}</b> · {form.age} {t("yearsShort")} · 📞 {form.phone}
              <small>{t("onRegister")}</small>
              <button className="link-btn" onClick={newCase}>
                {t("someoneElse")}
              </button>
            </div>
          )}
          {step === 0 && (
            <div className="form-grid">
              {!form.patientId && (
              <>
              <Field label={t("patientName")}>
                <input
                  value={form.name}
                  onChange={(e) => setForm({ ...form, name: e.target.value })}
                  placeholder={t("patientName")}
                />
              </Field>
              <Field label={t("age")}>
                <input
                  value={form.age}
                  onChange={(e) => setForm({ ...form, age: e.target.value.replace(/\D/g, "").slice(0, 3) })}
                  placeholder={t("age")}
                  inputMode="numeric"
                />
              </Field>
              <Field label={t("phone")}>
                <input
                  value={form.phone}
                  onChange={(e) => setForm({ ...form, phone: e.target.value.replace(/\D/g, "").slice(0, 10) })}
                  placeholder={t("phoneRequired")}
                  type="tel"
                  inputMode="tel"
                />
              </Field>
              </>
              )}
              <Field label={t("triage")}>
                <select value={form.triage} onChange={(e) => setForm({ ...form, triage: e.target.value })}>
                  <option value="ROUTINE">{t("routine")}</option>
                  <option value="PRIORITY">{t("priority")}</option>
                  <option value="EMERGENCY">{t("emergency")}</option>
                </select>
              </Field>
              <Field label={t("symptoms")} full>
                <textarea
                  value={form.symptom}
                  onChange={(e) => setForm({ ...form, symptom: e.target.value })}
                  placeholder={t("symptomsPlaceholder")}
                />
              </Field>
              {!form.patientId && (
              <label className="field full" style={{ flexDirection: "row", alignItems: "center", gap: 10 }}>
                <input
                  type="checkbox"
                  checked={form.consent}
                  onChange={(e) => setForm({ ...form, consent: e.target.checked })}
                  style={{ width: 18, height: 18, flex: "none" }}
                />
                <span>{t("consentLabel")}</span>
              </label>
              )}
              <button className="primary-btn" onClick={submit} disabled={!formValid || busy}>
                {busy ? t("loading") : t("saveCase")}
              </button>
            </div>
          )}
          {step === 1 && (
            <div>
              <div className="form-grid" style={{ marginBottom: 12 }}>
                <Field label={t("serviceNeeded")}>
                  <select id="asha-service" value={service} onChange={(e) => (setService(e.target.value), setSelected(null))}>
                    {SERVICES.map((x) => (
                      <option key={x} value={x}>
                        {serviceText(t, x)}
                      </option>
                    ))}
                  </select>
                </Field>
                <Field label={t("searchFacility")}>
                  <input id="asha-search" value={search} onChange={(e) => setSearch(e.target.value)} placeholder={t("hospitalName")} />
                </Field>
              </div>
              <p className="muted small-note">{t("bestMatchFirst")}</p>
              {loadingFacilities && facilities.length === 0 ? (
                <Skeleton />
              ) : shown.length === 0 ? (
                <Empty title={t("noFacility")} text={t("noHospitalService")} />
              ) : (
                <div className="facility-list">
                  {shown.map((f) => (
                    <RecommendationRow key={f.facility_id} r={f} picked={selected?.facility_id === f.facility_id} onPick={pickFacility} />
                  ))}
                </div>
              )}
              {noBeds && (
                <div className="notice warn reveal" role="alert">
                  <b>{noBeds.message}</b>
                  {noBeds.alternatives.length > 0 && <p>{t("theseHaveBeds")}</p>}
                  <div className="facility-list">
                    {noBeds.alternatives.map((a) => (
                      <RecommendationRow key={a.facility_id} r={a} onPick={(x) => (setSelected(x), createReferral(false, x))} />
                    ))}
                  </div>
                  <button className="link-btn" disabled={busy} onClick={() => createReferral(true)}>
                    {selected?.facility_name}: {t("sendWithoutBed")}
                  </button>
                </div>
              )}
              {!current?.encounter && (
                <p className="muted small-note">{t("saveCaseFirst")}</p>
              )}
              <button className="primary-btn" disabled={!selected || !current?.encounter || busy} onClick={() => createReferral()}>
                {busy ? t("loading") : t("createReferral")}
              </button>
            </div>
          )}
          {step === 2 && referral && (
            <div className="success-panel">
              <div className="token">{referral.code}</div>
              {qr && (
                <img
                  src={qr}
                  alt={t("referralPassQr")}
                  width="180"
                  height="180"
                  style={{ display: "block", margin: "10px auto", borderRadius: 12 }}
                />
              )}
              {qrText && (
                <button className="link-btn" onClick={copyPass}>
                  {t("copyPass")}
                </button>
              )}
              <h3>{referral.is_open ? t("referralLive") : statusText(t, referral.status)}</h3>
              <p>
                {referral.patient.name} → {referral.facility.name} · {serviceText(t, referral.requested_service)}
              </p>
              <div className="ward-chips" style={{ justifyContent: "center" }}>
                <BedChip bed={referral.bed} />
                {referral.rerouted_from_code && <span className="chip">{t("continues")} {referral.rerouted_from_code}</span>}
                {referral.rerouted_to_code && <span className="chip bed-released">{t("sentOnAs")} {referral.rerouted_to_code}</span>}
              </div>
              {referral.facility.phone && (
                <p className="muted">
                  {t("hospitalDesk")}: <a href={`tel:${referral.facility.phone}`}>{referral.facility.phone}</a>
                </p>
              )}
              <AshaAmbulance referral={referral} onChange={(r) => (setReferralState(r), load())} toast={toast} />
              {["CREATED", "ACCEPTED", "REJECTED"].includes(referral.status) && !referral.rerouted_to_id && (
                <div className="reroute-block">
                  {!rerouting ? (
                    <button className="secondary-btn" onClick={() => setRerouting(true)}>
                      {referral.status === "REJECTED" ? t("chooseAnother") : t("sendAnother")}
                    </button>
                  ) : (
                    <>
                      <p className="muted small-note">{t("otherHospitalsFor")} {serviceText(t, referral.requested_service)}</p>
                      <RerouteFinder
                        referral={referral}
                        toast={toast}
                        onDone={(fresh) => (setReferral(fresh), setRerouting(false), load())}
                      />
                      <button className="link-btn" onClick={() => setRerouting(false)}>
                        {t("cancel")}
                      </button>
                    </>
                  )}
                </div>
              )}
              {followUp && (referral.status === "FOLLOW_UP_DUE" || referral.status === "OVERDUE") ? (
                <>
                  <p>
                    <b>{t("followUpDue")}:</b> {new Date(followUp.due_at).toLocaleDateString()}
                    {followUp.is_late ? ` · ${t("followUpLate")}` : ""}
                  </p>
                  {followUp.sent_at && (
                    <p className="muted">
                      ✓ {t("sentForCheckup")} · {new Date(followUp.sent_at).toLocaleDateString()} · {t("waitingHospitalCheckup")}
                    </p>
                  )}
                  <div className="action-row">
                    {!followUp.sent_at && (
                      <button className="primary-btn" onClick={() => finishFollowUp("sent")} disabled={busy}>
                        {t("sendForCheckup")}
                      </button>
                    )}
                    {referral.status === "FOLLOW_UP_DUE" && (
                      <button className="secondary-btn" onClick={() => finishFollowUp("miss")} disabled={busy}>
                        {t("couldntGo")}
                      </button>
                    )}
                  </div>
                </>
              ) : (
                <p>{t("shareToken")}</p>
              )}
              <div className="action-row">
                <button className="secondary-btn" onClick={newCase}>
                  ＋ {t("newCase")}
                </button>
              </div>
              <div className="timeline">
                {referral.events.map((h, i) => (
                  <div className="timeline-item active" key={i}>
                    <i></i>
                    <div>
                      <b>{statusText(t, h.to_status)}</b>
                      <small>{new Date(h.at).toLocaleString()}</small>
                    </div>
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>
        <div className="panel" data-tour="continuity">
          <p className="eyebrow">{t("myReferralsEyebrow")}</p>
          <h3>{t("myContinuity")}</h3>
          <p className="muted">{t("continuityText")}</p>
          {alerts.slice(0, 3).map((n) => (
            <div className="mini-ref" key={n.id} role="button" tabIndex={0} onClick={() => readAlert(n)} title={t("markRead")}>
              <b>🔔</b>
              <span>{n.message}</span>
              <small>{new Date(n.created_at).toLocaleTimeString()}</small>
            </div>
          ))}
          {referrals === null ? (
            <Skeleton />
          ) : list.length === 0 ? (
            <Empty title={t("noReferrals")} text={t("createFirst")} />
          ) : (
            [...list]
              .sort((a, b) => new Date(b.created_at) - new Date(a.created_at))
              .slice(0, 4)
              .map((r) => (
                <div className="mini-ref" key={r.id} role="button" tabIndex={0} onClick={() => openReferral(r)}>
                  <b>{r.code}</b>
                  <span>{r.patient.name}</span>
                  <small>{statusText(t, r.status)}</small>
                </div>
              ))
          )}
        </div>
      </section>
      <VitalsPanel patient={current?.patient} referral={referral} toast={toast} />
      </>
      )}
      <ESanjeevaniCard
        toast={toast}
        summary={
          current?.patient
            ? `Patient: ${current.patient.name}, ${current.patient.age} y. Reason: ${referral?.reason || form.symptom || "-"}. Triage: ${referral?.triage || form.triage}.${referral ? ` SahyogCare referral ${referral.code} to ${referral.facility.name}.` : ""}`
            : ""
        }
      />
    </Dashboard>
  );
}

// Readings for the patient of the current referral, with normal ranges beside each one.
// Saved as a new reading on the patient's record (older readings are never overwritten).
function VitalsPanel({ patient, referral, toast }) {
  const { t } = useLanguage();
  const ranges = useVitalRanges();
  const [values, setValues] = useState({});
  const [latest, setLatest] = useState(null);
  const [busy, setBusy] = useState(false);
  const loadLatest = useCallback(() => {
    if (!patient) return;
    api
      .get(`/patients/${patient.id}/encounters`)
      .then((list) => setLatest(list.find((e) => Object.values(e.vitals).some((x) => x !== null)) || null))
      .catch(() => {});
  }, [patient?.id]);
  useEffect(() => {
    setValues({});
    setLatest(null);
    loadLatest();
  }, [loadLatest]);
  if (!patient)
    return (
      <section className="panel vitals-panel">
        <div className="empty">
          <div>♡</div>
          <h4>{t("selectCaseFirst")}</h4>
          <p>{t("selectCaseFirstSub")}</p>
        </div>
      </section>
    );
  const entered = Object.fromEntries(Object.entries(values).filter(([, v]) => v !== "" && v !== undefined).map(([k, v]) => [k, Number(v)]));
  const save = async () => {
    if (busy) return;
    if (!Object.keys(entered).length) return toast(t("enterReading"));
    setBusy(true);
    try {
      const enc = await api.post(`/patients/${patient.id}/encounters`, {
        reason: referral ? `New readings for ${referral.code}` : "New readings",
        kind: "VITALS_UPDATE",
        referral_id: referral?.id || null,
        vitals: entered,
      });
      setValues({});
      setLatest(enc);
      toast(enc.triage_suggestion || t("savedVitals"));
    } catch (e) {
      const fields = e.details?.fields;
      toast(fields ? `${e.message} ${Object.entries(fields).map(([k, m]) => `${k}: ${m}`).join(" · ")}` : e.message);
    } finally {
      setBusy(false);
    }
  };
  return (
    <section className="panel vitals-panel" data-tour="vitals">
      <div className="panel-head">
        <div>
          <p className="eyebrow">{t("readingsEyebrow")}</p>
          <h3>{t("vitalsTitle")}</h3>
          <p className="muted">{patient.name}</p>
        </div>
        {latest && (
          <span className="step-chip">
            {t("lastUpdated")} {new Date(latest.created_at).toLocaleString()}
          </span>
        )}
      </div>
      {latest && (
        <div className="latest-vitals">
          <VitalsReadout vitals={latest.vitals} flags={latest.flags} ranges={ranges} />
        </div>
      )}
      <VitalsGrid values={values} onChange={setValues} ranges={ranges} />
      <div className="action-row">
        <button className="primary-btn" onClick={save} disabled={busy || !Object.keys(entered).length}>
          {busy ? t("loading") : t("updateVitals")}
        </button>
      </div>
      <p className="medical-note">ℹ {t("rangesNote")}</p>
    </section>
  );
}

// ---------- Patient: their own account ----------

// Everything of the signed-in patient: their referrals (open ones first, with the journey,
// the hospital and the ambulance), their health record, and the night emergency button.
// There is no lookup by referral code: the patient signs in with their own mobile number.
function PatientHome({ toast, onSignOut }) {
  const { t } = useLanguage();
  const [tab, setTab] = usePersisted("sahyog_patient_tab", "referrals"); // referrals | health
  const [refs, setRefs] = useState(null);
  const [record, setRecord] = useState(null);
  const [emergency, setEmergency] = useState(false);
  const signOutRef = useRef(onSignOut);
  signOutRef.current = onSignOut;
  const load = useCallback(async () => {
    try {
      const [mine, rec] = await Promise.all([patientApi.get("/public/me/referrals"), patientApi.get("/public/me/record")]);
      setRefs(mine);
      setRecord(rec);
    } catch (e) {
      if (e.status === 401) signOutRef.current();
      else toast(errorText(t, e));
    }
  }, [toast]);
  usePolling(load);
  const open = (refs || []).filter((r) => r.is_open);
  const past = (refs || []).filter((r) => !r.is_open);
  const alive = record && !record.patient.deceased_at;
  return (
    <Dashboard
      title={record ? `${t("hello")}, ${record.patient.name}` : t("patientDashboard")}
      subtitle={t("patientAccountSub")}
    >
      {alive && (
        <button className="sos-btn" data-tour="sos" onClick={() => setEmergency(true)}>
          <span>🚨</span>
          <b>{t("emergencyNow")}</b>
          <small>{t("emergencyNowSub")}</small>
        </button>
      )}
      {record?.patient.self_registered && <p className="notice good self-note">{t("selfRegNote")}</p>}
      {emergency && createPortal(<EmergencyPanel onClose={() => (setEmergency(false), load())} />, document.body)}
      <div className="view-tabs" role="tablist">
        <button role="tab" aria-selected={tab === "referrals"} className={tab === "referrals" ? "tab active" : "tab"} onClick={() => setTab("referrals")}>
          ➜ {t("myReferralsTab")}
          {open.length ? ` · ${open.length}` : ""}
        </button>
        <button role="tab" aria-selected={tab === "health"} className={tab === "health" ? "tab active" : "tab"} onClick={() => setTab("health")}>
          ♡ {t("myHealth")}
        </button>
      </div>
      {tab === "referrals" && (
        <section className="panel" data-tour="journey">
          {refs === null ? (
            <Skeleton />
          ) : open.length === 0 ? (
            <Empty title={t("noOpenReferral")} text={t("noOpenReferralSub")} />
          ) : (
            open.map((r) => <MyReferralCard key={r.id} r={r} />)
          )}
          {past.length > 0 && (
            <details className="finished past-referrals">
              <summary>
                {t("pastReferrals")} ({past.length})
              </summary>
              {past.map((r) => (
                <div className="mini-ref" key={r.id}>
                  <b>{r.facility_name}</b>
                  <span>
                    {serviceText(t, r.requested_service)} · {r.reason}
                  </span>
                  <small>
                    {statusText(t, r.status)}
                    {r.rerouted_to_facility ? ` → ${r.rerouted_to_facility}` : ""} · {new Date(r.created_at).toLocaleDateString()}
                  </small>
                </div>
              ))}
            </details>
          )}
        </section>
      )}
      {tab === "health" && (
        <section className="panel">{record ? <PatientRecordView record={record} role="PATIENT" reload={load} toast={toast} /> : <Skeleton />}</section>
      )}
      <EmergencyBox />
      <ESanjeevaniCard
        toast={toast}
        summary={record ? `${record.patient.name}, ${record.patient.age} ${t("yearsShort")}. ${open[0] ? `SahyogCare ${open[0].code} → ${open[0].facility_name}.` : ""}` : ""}
      />
    </Dashboard>
  );
}

// One open referral as its patient sees it: where it stands and what to do.
function MyReferralCard({ r }) {
  const { t } = useLanguage();
  return (
    <div className="my-ref reveal">
      <div className="my-ref-head">
        <div>
          <p className="eyebrow">{serviceText(t, r.requested_service)}</p>
          <h3>{r.facility_name}</h3>
          <p className="muted">{r.reason}</p>
        </div>
        <span className={`urgency ${r.triage.toLowerCase()}`}>{t(TRIAGE_KEY[r.triage])}</span>
      </div>
      {r.status === "REJECTED" ? <Empty title={statusText(t, r.status)} text={t("referralRejected")} /> : <PatientJourney status={r.status} />}
      {r.follow_up_due && (
        <p className="notice good">
          <b>{t("followUpDue")}:</b> {new Date(r.follow_up_due).toLocaleDateString()}
        </p>
      )}
      <AmbulanceInfo amb={r.ambulance} />
      <div className="my-ref-actions">
        {r.facility_phone && (
          <a className="secondary-btn" href={`tel:${r.facility_phone}`}>
            📞 {t("callHospital")}
          </a>
        )}
        <span className="desk-code">
          {t("showAtDesk")}: <b>{r.code}</b>
        </span>
      </div>
      {["CREATED", "ACCEPTED"].includes(r.status) && (
        <ul className="checklist">
          <li>{t("medicines")}</li>
          <li>{t("phoneReach")}</li>
          <li>{t("showJourney")}</li>
        </ul>
      )}
    </div>
  );
}

function PatientJourney({ status }) {
  const { t } = useLanguage();
  // Overdue or escalated follow-ups sit at the follow-up step.
  const shown = status === "OVERDUE" || status === "ESCALATED" ? "FOLLOW_UP_DUE" : status;
  const idx = JOURNEY.indexOf(shown);
  return (
    <div className="journey">
      {JOURNEY.map((s, i) => (
        <div className={`journey-step ${i <= idx ? "done" : ""} ${i === idx ? "current" : ""}`} key={s}>
          <span>{i < idx ? "✓" : i === idx ? "•" : "○"}</span>
          <div>
            <b>{statusText(t, i === idx ? status : s)}</b>
            <small>{i === idx ? t("currentStatus") : i < idx ? t("completed") : t("nextStep")}</small>
          </div>
        </div>
      ))}
    </div>
  );
}

// ---------- Medical team ----------

// What happens next for each status, and who does it.
const NEXT_ACTION = {
  CREATED: { path: "accept", label: "accept", role: "FACILITY_STAFF" },
  ACCEPTED: { path: "arrival", label: "recordArrival", role: "FACILITY_STAFF" },
  ARRIVAL_RECORDED: { path: "consultation", label: "consulted", role: "DOCTOR" },
  CONSULTED: { path: "outcome", label: "recordOutcome", role: "DOCTOR" },
  // The follow-up checkup happens at the hospital, so staff or the doctor confirm it (the ASHA only sends the patient).
  FOLLOW_UP_DUE: { path: "close", label: "checkupDone", role: "FACILITY_STAFF", also: "DOCTOR" },
  OVERDUE: { path: "close", label: "checkupDone", role: "FACILITY_STAFF", also: "DOCTOR" },
  ESCALATED: { path: "close", label: "checkupDone", role: "FACILITY_STAFF", also: "DOCTOR" },
};
const ROLE_NAME = { FACILITY_STAFF: "roleStaff", DOCTOR: "roleDoctor", COORDINATOR: "doorOffice" };

function MedicalDashboard({ user, toast }) {
  const { t } = useLanguage();
  const [referrals, setReferrals] = useState(null);
  const [filter, setFilter] = usePersisted("sahyog_medical_filter", "ALL");
  const [rejecting, setRejecting] = useState(null); // referral id
  const [dispatching, setDispatching] = useState(null); // referral id
  const [trip, setTrip] = usePersisted("sahyog_dispatch_form", { eta: "", vehicle: "", driver: "" });
  const [reasons, setReasons] = useState([]);
  const [reason, setReason] = useState("");
  const [note, setNote] = useState("");
  const [busyId, setBusyId] = useState(null);
  const [recordFor, setRecordFor] = useState(null); // referral whose patient record is open
  const ranges = useVitalRanges();
  const fail = (e) => toast(errorText(t, e));

  const load = useCallback(async () => {
    try {
      setReferrals(await api.get("/referrals"));
    } catch (e) {
      if (e.status !== 401) fail(e);
    }
  }, []);
  usePolling(load);
  useEffect(() => {
    api
      .get("/referral-rejection-reasons")
      .then(setReasons)
      .catch(() => {});
  }, []);

  const replace = (r) => setReferrals((list) => (list || []).map((x) => (x.id === r.id ? r : x)));
  const act = async (r, path, body) => {
    setBusyId(r.id);
    try {
      const updated = await api.post(`/referrals/${r.id}/${path}`, body);
      replace(updated);
      toast(`${r.code} · ${statusText(t, updated.status)}`);
      return true;
    } catch (e) {
      fail(e);
      load();
      return false;
    } finally {
      setBusyId(null);
    }
  };
  const confirmReject = async (r) => {
    const chosen = reason || reasons[0]?.code;
    if (await act(r, "reject", { reason: chosen, note: note.trim() || null })) {
      setRejecting(null);
      setReason("");
      setNote("");
    }
  };

  const list = referrals || [];
  const open = list.filter((r) => r.is_open);
  const rank = { EMERGENCY: 0, PRIORITY: 1, ROUTINE: 2 };
  const queue = (
    filter === "Closed"
      ? list.filter((r) => !r.is_open)
      : open.filter((r) => filter === "ALL" || r.triage === filter)
  )
    .slice()
    .sort((a, b) => (rank[a.triage] ?? 3) - (rank[b.triage] ?? 3) || new Date(a.created_at) - new Date(b.created_at));

  return (
    <Dashboard title={t("medicalDashboard")} subtitle={t("medicalSub")}>
      <div className="stats">
        <Stat tour="stats" label={t("incoming")} value={open.length} meta={t("sharedQueue")} />
        <Stat label={t("priority")} value={open.filter((r) => r.triage === "PRIORITY").length} meta={t("requiresAttention")} />
        <Stat
          label={t("emergency")}
          value={open.filter((r) => r.triage === "EMERGENCY").length}
          meta={t("immediateEscalation")}
        />
      </div>
      {user?.role === "FACILITY_STAFF" && user.facility_id && <StaffBedsPanel facilityId={user.facility_id} toast={toast} />}
      {user?.role === "FACILITY_STAFF" && <PassScanner toast={toast} onDone={(r) => (replace(r), load())} />}
      <section className="panel">
        <div className="panel-head">
          <div>
            <p className="eyebrow">{t("queueEyebrow")}</p>
            <h3>{t("operationsQueue")}</h3>
          </div>
          <div className="filters" data-tour="filters">
            {[["ALL", "all"], ["EMERGENCY", "emergency"], ["PRIORITY", "priority"], ["ROUTINE", "routine"], ["Closed", "closed"]].map(([f, k]) => (
              <button key={f} className={filter === f ? "filter active" : "filter"} onClick={() => setFilter(f)}>
                {t(k)}
              </button>
            ))}
          </div>
        </div>
        {referrals === null ? (
          <Skeleton />
        ) : queue.length === 0 ? (
          <Empty title={t("queueEmpty")} text={list.length ? t("nothingInView") : t("freshWorkspace")} />
        ) : (
          <div className="queue" data-tour="queue">
            {queue.map((r) => {
              const next = NEXT_ACTION[r.status];
              const mine = next && (next.role === user?.role || next.also === user?.role);
              return (
                <div className="queue-item" key={r.id} style={rejecting === r.id ? { flexWrap: "wrap" } : undefined}>
                  <div>
                    <span className={`urgency ${r.triage.toLowerCase()}`}>{t(TRIAGE_KEY[r.triage])}</span>
                    <h4>{r.patient.name}</h4>
                    <p>
                      {r.code} · {r.facility.name} · {serviceText(t, r.requested_service)}
                    </p>
                    <p>{r.reason}</p>
                    {r.origin === "PATIENT_EMERGENCY" && <span className="chip deceased-chip">🚨 {t("bookedByPatient")}</span>}
                    {r.latest_vitals ? (
                      <div className="queue-vitals">
                        <small className="muted">{t("latestReadings")} · {new Date(r.latest_vitals_at).toLocaleString()}</small>
                        <VitalsReadout vitals={r.latest_vitals} flags={r.vitals_flags} ranges={ranges} />
                      </div>
                    ) : (
                      <div className="queue-vitals">
                        <VitalsReadout vitals={r.vitals} flags={r.vitals_flags} ranges={ranges} />
                      </div>
                    )}
                    <div className="ward-chips">
                      <BedChip bed={r.bed} />
                      {r.rerouted_from_code && <span className="chip">{t("sentOnFrom")} {r.rerouted_from_code}</span>}
                      {r.status === "REROUTED" && <span className="chip bed-released">{t("sentElsewhere")}</span>}
                    </div>
                    <AmbulanceInfo amb={r.ambulance} />
                    {r.follow_up && r.is_open && r.follow_up.status !== "COMPLETED" && (
                      <div className="ward-chips">
                        <span className="chip">
                          {t("followUpDue")}: {new Date(r.follow_up.due_at).toLocaleDateString()}
                        </span>
                        {r.follow_up.sent_at && <span className="chip bed-held">✓ {t("ashaSentPatient")}</span>}
                      </div>
                    )}
                  </div>
                  <div className="queue-actions">
                    <span className="status-badge">{statusText(t, r.status)}</span>
                    <div style={{ display: "flex", gap: 9, alignItems: "center", flexWrap: "wrap" }}>
                      {!r.is_open ? (
                        <button className="secondary-btn" disabled>
                          {t("closed")}
                        </button>
                      ) : next ? (
                        <button
                          className="secondary-btn"
                          disabled={!mine || busyId === r.id}
                          title={mine ? "" : `${t("waitingFor")} ${t(ROLE_NAME[next.role])}`}
                          onClick={() => act(r, next.path)}
                        >
                          {mine ? t(next.label) : `${t("waitingFor")} ${t(ROLE_NAME[next.role])}`}
                        </button>
                      ) : (
                        <button className="secondary-btn" disabled>
                          {t("withAsha")}
                        </button>
                      )}
                      {user?.role === "FACILITY_STAFF" && r.ambulance?.status === "REQUESTED" && dispatching !== r.id && (
                        <button className="primary-btn" onClick={() => setDispatching(r.id)}>
                          {t("sendAmbulance")}
                        </button>
                      )}
                      {user?.role === "FACILITY_STAFF" && r.ambulance?.status === "DISPATCHED" && (
                        <button className="secondary-btn" disabled={busyId === r.id} onClick={() => act(r, "ambulance/picked-up")}>
                          {t("patientPickedUp")}
                        </button>
                      )}
                      <button className="link-btn" onClick={() => setRecordFor(recordFor === r.id ? null : r.id)}>
                        {recordFor === r.id ? t("hideRecord") : `📋 ${t("patientRecord")}`}
                      </button>
                      {r.status === "CREATED" && user?.role === "FACILITY_STAFF" && rejecting !== r.id && (
                        <button className="secondary-btn" onClick={() => setRejecting(r.id)} disabled={busyId === r.id}>
                          {t("reject")}
                        </button>
                      )}
                    </div>
                  </div>
                  {recordFor === r.id && (
                    <div className="record-wrap" style={{ width: "100%" }}>
                      <PatientRecord
                        patientId={r.patient.id}
                        role={user?.role}
                        referralId={r.id}
                        toast={toast}
                        onClose={() => (setRecordFor(null), load())}
                      />
                    </div>
                  )}
                  {dispatching === r.id && (
                    <div className="form-grid reveal" style={{ width: "100%", marginTop: 10 }}>
                      <Field label={t("pickup")}>
                        <input value={r.ambulance?.pickup_note || ""} readOnly />
                      </Field>
                      <Field label={t("arrivesIn")}>
                        <input id="dispatch-eta" inputMode="numeric" value={trip.eta}
                          onChange={(e) => setTrip({ ...trip, eta: e.target.value.replace(/\D/g, "").slice(0, 3) })} />
                      </Field>
                      <Field label={t("vehicleNumber")}>
                        <input id="dispatch-vehicle" value={trip.vehicle} placeholder="WB-xx-xxxx"
                          onChange={(e) => setTrip({ ...trip, vehicle: e.target.value.toUpperCase() })} />
                      </Field>
                      <Field label={t("driverMobile")}>
                        <input id="dispatch-driver" inputMode="tel" value={trip.driver}
                          onChange={(e) => setTrip({ ...trip, driver: e.target.value.replace(/\D/g, "").slice(0, 10) })} />
                      </Field>
                      <div className="action-row" style={{ gridColumn: "1 / -1" }}>
                        <button
                          className="primary-btn"
                          disabled={!trip.eta || busyId === r.id || (trip.driver && !/^[6-9]\d{9}$/.test(trip.driver))}
                          onClick={async () => {
                            const ok = await act(r, "ambulance/dispatch", {
                              eta_minutes: Number(trip.eta),
                              vehicle_number: trip.vehicle.trim() || null,
                              driver_phone: trip.driver || null,
                            });
                            if (ok) {
                              setDispatching(null);
                              setTrip({ eta: "", vehicle: "", driver: "" });
                            }
                          }}
                        >
                          {t("confirmAmbulanceSent")}
                        </button>
                        <button
                          className="secondary-btn"
                          disabled={busyId === r.id}
                          onClick={async () => {
                            if (await act(r, "ambulance/cancel", { reason: "Hospital ambulance not available" })) setDispatching(null);
                          }}
                        >
                          {t("cantSendAmbulance")}
                        </button>
                        <button className="link-btn" onClick={() => setDispatching(null)}>
                          {t("cancel")}
                        </button>
                      </div>
                    </div>
                  )}
                  {rejecting === r.id && (
                    <div className="form-grid" style={{ width: "100%", marginTop: 10 }}>
                      <Field label={t("rejectReason")}>
                        <select value={reason || reasons[0]?.code || ""} onChange={(e) => setReason(e.target.value)}>
                          {reasons.map((x) => (
                            <option key={x.code} value={x.code}>
                              {x.label}
                            </option>
                          ))}
                        </select>
                      </Field>
                      <Field label={t("note")}>
                        <input value={note} onChange={(e) => setNote(e.target.value)} placeholder={t("optional")} />
                      </Field>
                      <div className="action-row" style={{ gridColumn: "1 / -1" }}>
                        <button className="primary-btn" disabled={busyId === r.id} onClick={() => confirmReject(r)}>
                          {t("confirmReject")}
                        </button>
                        <button className="secondary-btn" onClick={() => setRejecting(null)}>
                          {t("cancel")}
                        </button>
                      </div>
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        )}
      </section>
    </Dashboard>
  );
}

// Facility desk: record arrival by scanning (camera) or pasting the patient's referral pass.
const VITAL_LABELS = [
  ["systolic", "BP", (v) => (v.diastolic ? `${v.systolic}/${v.diastolic}` : v.systolic)],
  ["pulse", "Pulse", (v) => v.pulse],
  ["spo2", "SpO₂", (v) => `${v.spo2}%`],
  ["temperature_c", "Temp", (v) => `${v.temperature_c}°C`],
  ["respiratory_rate", "Resp", (v) => v.respiratory_rate],
  ["glucose_mg_dl", "Sugar", (v) => v.glucose_mg_dl],
];


function PassScanner({ toast, onDone }) {
  const { t } = useLanguage();
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const [camera, setCamera] = useState(false);
  const canScan = typeof window !== "undefined" && "BarcodeDetector" in window && navigator.mediaDevices?.getUserMedia;
  const verify = async (qrText) => {
    if (!qrText.trim() || busy) return;
    setBusy(true);
    try {
      const r = await api.post("/referral-passes/verify", { qr_text: qrText.trim() });
      toast(`${r.referral.code} · ${r.already_recorded ? statusText(t, r.referral.status) : t("recordArrival")} ✓`);
      setText("");
      onDone(r.referral);
    } catch (e) {
      toast(errorText(t, e));
    } finally {
      setBusy(false);
    }
  };
  return (
    <section className="panel" style={{ marginBottom: 18 }}>
      <p className="eyebrow">{t("referralPassQr")}</p>
      <form
        className="lookup"
        onSubmit={(e) => {
          e.preventDefault();
          verify(text);
        }}
      >
        <input value={text} onChange={(e) => setText(e.target.value)} placeholder={t("scanPass")} />
        <button type="submit" className="secondary-btn" disabled={busy || !text.trim()}>
          {t("recordArrival")}
        </button>
        {canScan && (
          <button type="button" className="secondary-btn" onClick={() => setCamera(true)}>
            📷
          </button>
        )}
      </form>
      {camera && (
        <CameraScan
          onClose={() => setCamera(false)}
          onCode={(code) => {
            setCamera(false);
            verify(code);
          }}
        />
      )}
    </section>
  );
}

function CameraScan({ onCode, onClose }) {
  const { t } = useLanguage();
  const video = useRef(null);
  useEffect(() => {
    let stream,
      timer,
      stopped = false;
    const detector = new window.BarcodeDetector({ formats: ["qr_code"] });
    navigator.mediaDevices
      .getUserMedia({ video: { facingMode: "environment" } })
      .then((s) => {
        stream = s;
        if (stopped || !video.current) return;
        video.current.srcObject = s;
        video.current.play();
        const tick = async () => {
          if (stopped) return;
          try {
            const found = await detector.detect(video.current);
            if (found[0]?.rawValue) return onCode(found[0].rawValue);
          } catch {}
          timer = setTimeout(tick, 300);
        };
        tick();
      })
      .catch(onClose);
    return () => {
      stopped = true;
      clearTimeout(timer);
      stream?.getTracks().forEach((tr) => tr.stop());
    };
  }, []);
  return createPortal(
    <div className="consult-modal" role="dialog" aria-modal="true" onClick={(e) => e.target === e.currentTarget && onClose()}>
      <div className="consult-modal-card">
        <button className="consult-close" onClick={onClose} aria-label={t("close")}>
          ×
        </button>
        <p className="eyebrow">{t("scanCamera")}</p>
        <video ref={video} playsInline muted style={{ width: "100%", borderRadius: 14, background: "#000" }} />
      </div>
    </div>,
    document.body,
  );
}

createRoot(document.getElementById("root")).render(
  <LanguageProvider>
    <App />
  </LanguageProvider>,
);
