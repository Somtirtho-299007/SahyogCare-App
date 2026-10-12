import React, { useCallback, useEffect, useRef, useState } from "react";
import { createRoot } from "react-dom/client";
import { createPortal } from "react-dom";
import QRCode from "qrcode";
import "./styles.css";
import "./language-sidebar.css";
import { api, currentUser, logout, lookupReferral, newKey, qs, refreshMe, requestCode, verifyCode } from "./api.js";
import { LanguageProvider, LanguageSidebar, readLS, useLanguage, writeLS } from "./i18n.jsx";
import { TOURS, Tour } from "./tour.jsx";
import { Dashboard, Empty, Field, Skeleton, Stat, VitalInput } from "./ui.jsx";

const ROLES = {
  asha: { label: "ASHA / ANM", icon: "◉", desc: "Field worker coordination" },
  patient: { label: "Patient", icon: "♡", desc: "My referral & care journey" },
  medical: { label: "Medical Team", icon: "✚", desc: "Triage, referrals & outcomes" },
  coordinator: { label: "Coordinator", icon: "◆", desc: "District office & approvals" },
};
// Backend role → which screen it uses.
const SCREEN_FOR = { WORKER: "asha", FACILITY_STAFF: "medical", DOCTOR: "medical", COORDINATOR: "coordinator" };
const JOURNEY = ["CREATED", "ACCEPTED", "ARRIVAL_RECORDED", "CONSULTED", "OUTCOME_RECORDED", "FOLLOW_UP_DUE", "CLOSED"];
const TRIAGE_LABEL = { EMERGENCY: "Emergency", PRIORITY: "Priority", ROUTINE: "Routine" };
const isEmail = (x) => /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(x.trim());
const pretty = (s) => (s || "").replaceAll("_", " ");
const REFRESH_MS = 15000;

// Re-run `load` now, every 15 seconds, and whenever the tab comes back into view.
function usePolling(load) {
  useEffect(() => {
    load();
    const id = setInterval(load, REFRESH_MS);
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
    return readLS("sahyogcare_patient_mode") ? { screen: "patient", user: null } : null;
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
  useEffect(() => {
    if (!readLS(`sahyogcare_tour_${tourKey}`)) {
      const x = setTimeout(() => setTourOpen(true), 600);
      return () => clearTimeout(x);
    }
  }, [tourKey]);
  const closeTour = () => {
    writeLS(`sahyogcare_tour_${tourKey}`, "1");
    setTourOpen(false);
  };
  useEffect(() => {
    const onLogout = () => setSession(null);
    window.addEventListener("sahyog:logout", onLogout);
    return () => window.removeEventListener("sahyog:logout", onLogout);
  }, []);
  const signIn = (s) => {
    if (s.screen === "patient") writeLS("sahyogcare_patient_mode", "1");
    setSession(s);
    if (s.user) setToast(`${t(s.screen)} · ${s.user.name}`);
  };
  const signOut = () => {
    logout();
    writeLS("sahyogcare_patient_mode", "");
    setSession(null);
  };
  if (!session)
    return (
      <>
        <Auth onSignIn={signIn} onTour={() => setTourOpen(true)} />
        <LanguageSidebar />
        <Tour steps={TOURS.auth} open={tourOpen} onClose={closeTour} />
      </>
    );
  if (session.user && session.user.approved === false)
    return (
      <>
        <AccessScreen
          user={session.user}
          onApproved={(user) => signIn({ screen: SCREEN_FOR[user.role], user })}
          onSignOut={signOut}
        />
        <LanguageSidebar />
      </>
    );
  return (
    <div className="app-shell">
      <header className="topbar">
        <div className="brand">
          <div className="brand-mark">स</div>
          <div>
            <strong>SahyogCare</strong>
            <span>Care without black holes</span>
          </div>
        </div>
        <div className="session">
          <button className="help-btn" data-tour="help" onClick={() => setTourOpen(true)} aria-label="App tour" title="App tour">
            ?
          </button>
          <span className="role-pill">
            {ROLES[session.screen].icon} {t(session.screen)}
          </span>
          {session.user && <span className="email">{session.user.email}</span>}
          <button className="ghost-btn" onClick={signOut}>
            {t("signOut")}
          </button>
        </div>
      </header>
      <main className="page page-fade" key={session.screen}>
        {session.screen === "asha" && <AshaDashboard toast={setToast} />}
        {session.screen === "patient" && <PatientDashboard />}
        {session.screen === "medical" && <MedicalDashboard user={session.user} toast={setToast} />}
        {session.screen === "coordinator" && <CoordinatorDashboard toast={setToast} />}
      </main>
      {toast && (
        <div className="toast" key={toast} role="status">
          <span className="toast-icon">✓</span>
          {toast}
        </div>
      )}
      <LanguageSidebar />
      <Tour steps={TOURS[session.screen]} open={tourOpen} onClose={closeTour} />
    </div>
  );
}

// ---------- New account: ask for a role, wait for the coordinator ----------

const REQUEST_ROLES = [
  { role: "WORKER", label: "ASHA / ANM" },
  { role: "FACILITY_STAFF", label: "Hospital staff" },
  { role: "DOCTOR", label: "Doctor" },
  { role: "COORDINATOR", label: "Coordinator (district office)" },
];
const NEEDS_HOSPITAL = new Set(["FACILITY_STAFF", "DOCTOR"]);

function AccessScreen({ user, onApproved, onSignOut }) {
  const [mine, setMine] = useState(undefined); // undefined = loading, null = no request yet
  const [facilities, setFacilities] = useState([]);
  const [form, setForm] = useState({ role: "WORKER", name: "", facility_id: "", note: "" });
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const set = (k) => (e) => setForm((f) => ({ ...f, [k]: e.target.value }));

  const approvedRef = useRef(onApproved);
  approvedRef.current = onApproved;
  const check = useCallback(async () => {
    try {
      const me = await refreshMe();
      if (me.approved) return approvedRef.current(me);
      setMine(await api.get("/access-requests/mine"));
    } catch (e) {
      setError(e.message);
    }
  }, []);
  usePolling(check);
  useEffect(() => {
    api.get("/facilities").then(setFacilities).catch(() => {});
  }, []);

  const submit = async () => {
    setBusy(true);
    setError("");
    try {
      const body = { role: form.role, name: form.name.trim(), note: form.note.trim() || null };
      if (NEEDS_HOSPITAL.has(form.role)) body.facility_id = form.facility_id;
      const r = await api.post("/access-requests", body);
      setMine(r);
      if (r.status === "APPROVED") await check();
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  };

  const waiting = mine?.status === "PENDING";
  const canSend = form.name.trim() && (!NEEDS_HOSPITAL.has(form.role) || form.facility_id);
  return (
    <div className="auth-card-wrap access-wrap">
      <div className="auth-card">
        <div className="mini-brand">
          स <span>SahyogCare</span>
        </div>
        {mine === undefined ? (
          <Skeleton />
        ) : waiting ? (
          <>
            <h2>Waiting for approval</h2>
            <p className="muted">
              You asked to join as <b>{REQUEST_ROLES.find((r) => r.role === mine.requested_role)?.label}</b>
              {mine.facility_name ? ` at ${mine.facility_name}` : ""}. The district coordinator has been told. This page
              opens your dashboard by itself once you are approved.
            </p>
            <button className="primary-btn" onClick={check}>
              Check again
            </button>
          </>
        ) : (
          <>
            <h2>Welcome to SahyogCare</h2>
            <p className="muted">
              Signed in as <b>{user.email}</b>. Tell us your role; the district coordinator approves it before you can
              see any patient records.
            </p>
            {mine?.status === "REJECTED" && (
              <div className="otp-note" role="alert">
                Your last request was not approved{mine.decision_note ? `: ${mine.decision_note}` : "."} You can ask again.
              </div>
            )}
            <label>Your name</label>
            <input value={form.name} onChange={set("name")} placeholder="Full name" />
            <label>Your role</label>
            <div className="role-grid">
              {REQUEST_ROLES.map((r) => (
                <button
                  key={r.role}
                  className={`role-choice ${form.role === r.role ? "selected" : ""}`}
                  onClick={() => setForm((f) => ({ ...f, role: r.role }))}
                >
                  <span>{r.label}</span>
                </button>
              ))}
            </div>
            {NEEDS_HOSPITAL.has(form.role) && (
              <>
                <label>Your hospital</label>
                <select className="otp-input" value={form.facility_id} onChange={set("facility_id")}>
                  <option value="">Choose your hospital</option>
                  {facilities.map((f) => (
                    <option key={f.id} value={f.id}>
                      {f.name}
                    </option>
                  ))}
                </select>
              </>
            )}
            <label>How the coordinator can confirm it's you (optional)</label>
            <input value={form.note} onChange={set("note")} placeholder="e.g. ASHA, Chakdaha block, ID 1234" />
            <button className="primary-btn" onClick={submit} disabled={!canSend || busy}>
              {busy ? "Sending…" : "Ask to join"}
            </button>
          </>
        )}
        {error && (
          <div className="otp-note" role="alert">
            {error}
          </div>
        )}
        <button className="link-btn" onClick={onSignOut}>
          Sign out
        </button>
      </div>
    </div>
  );
}

// ---------- Coordinator ----------

const ROLE_LABEL = Object.fromEntries(REQUEST_ROLES.map((r) => [r.role, r.label]));

function CoordinatorDashboard({ toast }) {
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
      if (e.status !== 401) toast(e.message);
    }
  }, [toast]);
  usePolling(load);

  const decide = async (r, action) => {
    setBusyId(r.id);
    try {
      await api.post(`/access-requests/${r.id}/${action}`);
      toast(`${r.name} · ${action === "approve" ? "approved" : "rejected"}`);
      setRequests((list) => (list || []).filter((x) => x.id !== r.id));
    } catch (e) {
      toast(e.message);
      load();
    } finally {
      setBusyId(null);
    }
  };

  const wards = (facilities || []).flatMap((f) => f.wards || []);
  return (
    <Dashboard title={t("coordinatorDashboard")} subtitle={t("coordinatorSub")}>
      <div className="stats">
        <Stat tour="stats" label="Waiting for approval" value={requests ? requests.length : "–"} meta="People who asked to join" />
        <Stat label="Hospitals" value={facilities ? facilities.length : "–"} meta="In your district" />
        <Stat
          label="Free beds"
          value={facilities ? wards.reduce((n, w) => n + w.free, 0) : "–"}
          meta={`of ${wards.reduce((n, w) => n + w.total, 0)} reported`}
        />
      </div>
      <section className="panel" data-tour="requests">
        <div className="panel-head">
          <div>
            <p className="eyebrow">Access</p>
            <h3>Who wants to join</h3>
          </div>
        </div>
        {requests === null ? (
          <Skeleton />
        ) : requests.length === 0 ? (
          <Empty title="No one is waiting" text="New sign-ups appear here for you to approve." />
        ) : (
          <div className="queue">
            {requests.map((r) => (
              <div className="queue-item" key={r.id}>
                <div>
                  <span className="status-badge">{ROLE_LABEL[r.requested_role] || pretty(r.requested_role)}</span>
                  <h4>{r.name}</h4>
                  <p>
                    {r.email}
                    {r.facility_name ? ` · ${r.facility_name}` : ""}
                    {r.note ? ` · ${r.note}` : ""}
                  </p>
                </div>
                <div className="queue-actions">
                  <button className="secondary-btn" disabled={busyId === r.id} onClick={() => decide(r, "reject")}>
                    Reject
                  </button>
                  <button className="primary-btn" disabled={busyId === r.id} onClick={() => decide(r, "approve")}>
                    Approve
                  </button>
                </div>
              </div>
            ))}
          </div>
        )}
      </section>
      <section className="panel" data-tour="beds" style={{ marginTop: 18 }}>
        <div className="panel-head">
          <div>
            <p className="eyebrow">Beds</p>
            <h3>Hospitals in the district</h3>
          </div>
        </div>
        {facilities === null ? (
          <Skeleton />
        ) : (
          <div className="queue">
            {facilities.map((f) => (
              <div className="queue-item" key={f.id}>
                <div>
                  <h4>{f.name}</h4>
                  <p>
                    {f.type}
                    {f.phone ? ` · ${f.phone}` : ""}
                    {f.has_ambulance ? " · has ambulance" : ""}
                  </p>
                  <div className="ward-chips">
                    {(f.wards || []).length === 0 ? (
                      <span className="step-chip">No bed data yet</span>
                    ) : (
                      f.wards.map((w) => (
                        <span key={w.ward} className="step-chip" title={w.stale ? "Not confirmed in the last 12 hours" : ""}>
                          {pretty(w.ward).toLowerCase()}: <b>{w.free}</b> free of {w.total}
                          {w.stale ? " ·  old" : ""}
                        </span>
                      ))
                    )}
                  </div>
                </div>
              </div>
            ))}
          </div>
        )}
      </section>
    </Dashboard>
  );
}

function Auth({ onSignIn, onTour }) {
  const { t } = useLanguage();
  const [role, setRole] = useState("asha");
  const [email, setEmail] = useState("");
  const [otp, setOtp] = useState("");
  const [sent, setSent] = useState(false);
  const [demoOtp, setDemoOtp] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const sendOtp = async () => {
    if (!isEmail(email) || busy) return;
    setBusy(true);
    setError("");
    try {
      const r = await requestCode(email);
      setOtp("");
      setDemoOtp(r.dev_code || "");
      setSent(true);
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  };
  const verify = async () => {
    if (otp.length !== 6 || busy) return;
    setBusy(true);
    setError("");
    try {
      const user = await verifyCode(email, otp);
      onSignIn({ screen: SCREEN_FOR[user.role], user });
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  };
  return (
    <div className="auth-screen">
      <div className="auth-art">
        <div className="orb orb1"></div>
        <div className="orb orb2"></div>
        <div className="care-illustration">✚</div>
        <p className="eyebrow">SahyogCare · Kenshi</p>
        <h1>
          {t("oneReferral")}
          <br />
          <em>{t("oneJourney")}</em>
        </h1>
        <p className="muted-light">{t("authDescription")}</p>
        <div className="auth-proof">
          <span>✓</span> {t("offlineReady")}
        </div>
        <div className="auth-proof">
          <span>✓</span> {t("closedLoop")}
        </div>
      </div>
      <div className="auth-card-wrap">
        <div className="auth-card">
          <div className="mini-brand">
            स <span>SahyogCare</span>
          </div>
          <button className="help-btn auth-help" onClick={onTour} aria-label="App tour" title="App tour">
            ?
          </button>
          <h2>{t("welcome")}</h2>
          <p className="muted">{t("chooseRole")}</p>
          <div className="role-grid" data-tour="roles">
            {Object.entries(ROLES).map(([key, r]) => (
              <button
                key={key}
                className={`role-choice ${role === key ? "selected" : ""}`}
                onClick={() => {
                  setRole(key);
                  setError("");
                }}
              >
                <b>{r.icon}</b>
                <span>{t(key)}</span>
                <small>{t(`${key}Desc`)}</small>
              </button>
            ))}
          </div>
          {role === "patient" ? (
            <>
              <p className="muted" data-tour="email">
                {t("patientNoLogin")}
              </p>
              <button className="primary-btn" onClick={() => onSignIn({ screen: "patient", user: null })}>
                {t("continuePatient")} →
              </button>
            </>
          ) : (
            <>
              <label>{t("email")}</label>
              <input
                data-tour="email"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                onKeyDown={(e) => e.key === "Enter" && !sent && sendOtp()}
                readOnly={sent}
                placeholder="you@gmail.com"
                type="email"
                autoComplete="email"
              />
              {!sent ? (
                <button className="primary-btn" onClick={sendOtp} disabled={!isEmail(email) || busy}>
                  {busy ? t("loading") : t("sendCode")}
                </button>
              ) : (
                <>
                  <div className="otp-note">{t("otpNote")}</div>
                  <input
                    className="otp-input"
                    value={otp}
                    onChange={(e) => setOtp(e.target.value.replace(/\D/g, ""))}
                    onKeyDown={(e) => e.key === "Enter" && verify()}
                    placeholder="Enter 6-digit OTP"
                    inputMode="numeric"
                    maxLength="6"
                    autoComplete="one-time-code"
                    autoFocus
                  />
                  <button className="primary-btn" onClick={verify} disabled={otp.length !== 6 || busy}>
                    {busy ? t("loading") : t("verify")}
                  </button>
                  <button
                    className="link-btn"
                    onClick={() => {
                      setSent(false);
                      setOtp("");
                      setDemoOtp("");
                      setError("");
                    }}
                  >
                    {t("changeEmail")}
                  </button>
                  {demoOtp && (
                    <div className="demo-code">
                      Test OTP: <b>{demoOtp}</b>
                    </div>
                  )}
                </>
              )}
            </>
          )}
          {error && (
            <div className="otp-note" role="alert">
              {error}
            </div>
          )}
          <div className="auth-disclaimer">{t("demoAccounts")}</div>
        </div>
      </div>
    </div>
  );
}

// ---------- ASHA ----------

const EMPTY_FORM = { name: "", age: "", phone: "", triage: "PRIORITY", symptom: "", consent: false };

function AshaDashboard({ toast }) {
  const { t } = useLanguage();
  const [step, setStep] = useState(0);
  const [form, setForm] = useState(EMPTY_FORM);
  const [current, setCurrent] = useState(null); // { patient, encounter } for the case being created
  const [facilities, setFacilities] = useState([]);
  const [loadingFacilities, setLoadingFacilities] = useState(false);
  const [search, setSearch] = useState("");
  const [selected, setSelected] = useState(null);
  const [service, setService] = useState("");
  const [referral, setReferral] = useState(null);
  const [qr, setQr] = useState("");
  const [qrText, setQrText] = useState("");
  const [followUps, setFollowUps] = useState([]);
  const [referrals, setReferrals] = useState(null);
  const [alerts, setAlerts] = useState([]);
  const [busy, setBusy] = useState(false);
  const fail = (e) => toast(e.message);

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
      setReferral((r) => (r ? refs.find((x) => x.id === r.id) || r : r));
    } catch (e) {
      if (e.status !== 401) fail(e);
    }
  }, []);
  usePolling(load);

  useEffect(() => {
    if (step !== 1) return;
    setLoadingFacilities(true);
    const x = setTimeout(() => {
      api
        .get(`/facilities${qs({ q: search.trim() })}`)
        .then(setFacilities)
        .catch(fail)
        .finally(() => setLoadingFacilities(false));
    }, 250);
    return () => clearTimeout(x);
  }, [step, search]);

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
    form.name.trim() && form.age !== "" && Number(form.age) <= 120 && /^[6-9]\d{9}$/.test(form.phone) && form.consent;

  const submit = async () => {
    if (!formValid || busy) return;
    setBusy(true);
    try {
      const patient = await api.post("/patients", {
        name: form.name.trim(),
        age: Number(form.age),
        phone: form.phone,
        consent_given: true,
      });
      const encounter = await api.post(`/patients/${patient.id}/encounters`, {
        reason: form.symptom.trim() || "Referral",
        triage: form.triage,
      });
      setCurrent({ patient, encounter });
      setStep(1);
      toast(patient.possible_duplicate_of ? "Saved. A patient with this name and phone already exists." : "Patient case saved");
    } catch (e) {
      fail(e);
    } finally {
      setBusy(false);
    }
  };

  const pickFacility = (f) => {
    setSelected(f);
    const usable = f.services.find((s) => s.availability !== "UNAVAILABLE") || f.services[0];
    setService(usable?.service || "");
  };

  const createReferral = async () => {
    if (!selected || !service || !current || busy) return;
    setBusy(true);
    try {
      const r = await api.post(
        "/referrals",
        {
          patient_id: current.patient.id,
          encounter_id: current.encounter.id,
          destination_facility_id: selected.id,
          requested_service: service,
        },
        { headers: { "Idempotency-Key": newKey() } },
      );
      setReferral(r);
      setStep(2);
      toast("Referral created and tracked");
      load();
    } catch (e) {
      fail(e);
    } finally {
      setBusy(false);
    }
  };

  const newCase = () => {
    setForm(EMPTY_FORM);
    setCurrent(null);
    setSelected(null);
    setService("");
    setSearch("");
    setFacilities([]);
    setReferral(null);
    setStep(0);
  };

  const openReferral = (r) => {
    setReferral(r);
    setCurrent({ patient: r.patient, encounter: null });
    setStep(2);
  };

  const copyPass = async () => {
    try {
      await navigator.clipboard.writeText(qrText);
      toast(t("passCopied"));
    } catch {
      window.prompt(t("copyPass"), qrText);
    }
  };

  const followUp = referral && followUps.find((f) => f.referral_id === referral.id);
  const finishFollowUp = async (kind) => {
    if (!followUp || busy) return;
    setBusy(true);
    try {
      await api.post(`/follow-ups/${followUp.id}/${kind}`);
      toast(kind === "complete" ? t("followUpDoneToast") : t("followUpMissedToast"));
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
      <section className="feature-grid">
        <div className="panel wide" data-tour="intake">
          <div className="panel-head">
            <div>
              <p className="eyebrow">Feature 01</p>
              <h3>{t("patientIntake")}</h3>
            </div>
            <span className="step-chip">
              {t("step")} {step + 1}/3
            </span>
          </div>
          <div className="step-progress" aria-hidden="true">
            <i style={{ width: `${((step + 1) / 3) * 100}%` }} />
          </div>
          {step === 0 && (
            <div className="form-grid">
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
              <Field label={t("triage")}>
                <select value={form.triage} onChange={(e) => setForm({ ...form, triage: e.target.value })}>
                  <option value="ROUTINE">Routine</option>
                  <option value="PRIORITY">Priority</option>
                  <option value="EMERGENCY">Emergency</option>
                </select>
              </Field>
              <Field label={t("symptoms")} full>
                <textarea
                  value={form.symptom}
                  onChange={(e) => setForm({ ...form, symptom: e.target.value })}
                  placeholder="Administrative summary only — no autonomous diagnosis."
                />
              </Field>
              <label className="field full" style={{ flexDirection: "row", alignItems: "center", gap: 10 }}>
                <input
                  type="checkbox"
                  checked={form.consent}
                  onChange={(e) => setForm({ ...form, consent: e.target.checked })}
                  style={{ width: 18, height: 18, flex: "none" }}
                />
                <span>{t("consentLabel")}</span>
              </label>
              <button className="primary-btn" onClick={submit} disabled={!formValid || busy}>
                {busy ? t("loading") : t("saveCase")}
              </button>
            </div>
          )}
          {step === 1 && (
            <div>
              <div className="search-row">
                <input value={search} onChange={(e) => setSearch(e.target.value)} placeholder={t("searchFacility")} />
              </div>
              {loadingFacilities && facilities.length === 0 ? (
                <Skeleton />
              ) : facilities.length === 0 ? (
                <Empty title={t("noFacility")} text={t("tryAnother")} />
              ) : (
                <div className="facility-list">
                  {facilities.map((f) => (
                    <button
                      className={`facility ${selected?.id === f.id ? "picked" : ""}`}
                      key={f.id}
                      onClick={() => pickFacility(f)}
                    >
                      <div>
                        <b>{f.name}</b>
                        <span>
                          {f.type} · {f.district}
                          {f.phone ? ` · ☎ ${f.phone}` : ""}
                        </span>
                        <small className="spec-chips">
                          {f.services.map((s) => (
                            <i
                              key={s.service}
                              title={s.availability_note || ""}
                              style={
                                s.availability === "UNAVAILABLE" ? { textDecoration: "line-through", opacity: 0.6 } : undefined
                              }
                            >
                              {s.service}
                              {s.availability === "UNAVAILABLE" ? ` · ${t("unavailable")}` : ""}
                            </i>
                          ))}
                        </small>
                      </div>
                      <strong>{f.beds ?? "—"} beds</strong>
                    </button>
                  ))}
                </div>
              )}
              {selected && (
                <div className="form-grid" style={{ marginTop: 12 }}>
                  <Field label={t("serviceNeeded")} full>
                    <select value={service} onChange={(e) => setService(e.target.value)}>
                      {selected.services.map((s) => (
                        <option key={s.service} value={s.service}>
                          {s.service}
                          {s.availability === "UNAVAILABLE" ? ` (${t("unavailable")})` : ""}
                        </option>
                      ))}
                    </select>
                  </Field>
                </div>
              )}
              <button className="primary-btn" disabled={!selected || !service || busy} onClick={createReferral}>
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
              <h3>{referral.is_open ? t("referralLive") : pretty(referral.status)}</h3>
              <p>
                {referral.patient.name} → {referral.facility.name} · {referral.requested_service}
              </p>
              {followUp && (referral.status === "FOLLOW_UP_DUE" || referral.status === "OVERDUE") ? (
                <>
                  <p>
                    <b>{t("followUpDue")}:</b> {new Date(followUp.due_at).toLocaleDateString()}
                    {followUp.is_late ? ` · ${t("followUpLate")}` : ""}
                  </p>
                  <div className="action-row">
                    <button className="primary-btn" onClick={() => finishFollowUp("complete")} disabled={busy}>
                      {t("followUpDone")}
                    </button>
                    {referral.status === "FOLLOW_UP_DUE" && (
                      <button className="secondary-btn" onClick={() => finishFollowUp("miss")} disabled={busy}>
                        {t("visitMissed")}
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
                      <b>{pretty(h.to_status)}</b>
                      <small>{new Date(h.at).toLocaleString()}</small>
                    </div>
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>
        <div className="panel" data-tour="continuity">
          <p className="eyebrow">Feature 03</p>
          <h3>{t("myContinuity")}</h3>
          <p className="muted">{t("continuityText")}</p>
          {alerts.slice(0, 3).map((n) => (
            <div className="mini-ref" key={n.id} role="button" tabIndex={0} onClick={() => readAlert(n)} title="Mark as read">
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
                  <small>{pretty(r.status)}</small>
                </div>
              ))
          )}
        </div>
      </section>
      <VitalsPanel patient={current?.patient} triage={form.triage} toast={toast} />
    </Dashboard>
  );
}

const VITAL_FIELDS = ["systolic", "diastolic", "pulse", "temperature", "spo2", "respiratoryRate", "glucose", "weight"];
// Screen field → backend field.
const VITAL_API = {
  systolic: "systolic",
  diastolic: "diastolic",
  pulse: "pulse",
  temperature: "temperature_c",
  spo2: "spo2",
  respiratoryRate: "respiratory_rate",
  glucose: "glucose_mg_dl",
  weight: "weight_kg",
};
const emptyVitals = () => Object.fromEntries(VITAL_FIELDS.map((f) => [f, ""]));

function VitalsPanel({ patient, triage, toast }) {
  const { t } = useLanguage();
  const [v, setV] = useState(emptyVitals);
  const [meds, setMeds] = useState([]);
  const [updatedAt, setUpdatedAt] = useState(null);
  const [busy, setBusy] = useState(false);
  useEffect(() => {
    setV(emptyVitals());
    setMeds([]);
    setUpdatedAt(null);
    if (!patient) return;
    let alive = true;
    api
      .get(`/patients/${patient.id}/encounters`)
      .then((list) => {
        if (!alive) return;
        const withVitals = list.find((e) => Object.values(e.vitals).some((x) => x !== null));
        if (withVitals) {
          setV(Object.fromEntries(VITAL_FIELDS.map((f) => [f, withVitals.vitals[VITAL_API[f]] ?? ""])));
          setUpdatedAt(withVitals.created_at);
        }
        const withMeds = list.find((e) => e.medicines.length);
        if (withMeds)
          setMeds(
            withMeds.medicines.map((m, i) => ({
              id: i + 1,
              name: m.name,
              dose: m.dose || "",
              frequency: m.frequency || "",
              adherence: m.notes || "",
            })),
          );
      })
      .catch(() => {});
    return () => {
      alive = false;
    };
  }, [patient?.id]);
  if (!patient)
    return (
      <section className="panel vitals-panel">
        <div className="empty">
          <div>♡</div>
          <h4>Select a patient case first</h4>
          <p>Patient vitals and ongoing medicines will appear here after a case is created.</p>
        </div>
      </section>
    );
  const bpSys = Number(v.systolic),
    bpDia = Number(v.diastolic),
    review = (bpSys && bpSys >= 120) || (bpDia && bpDia >= 80);
  const set = (k, x) => setV((a) => ({ ...a, [k]: x }));
  const add = () => setMeds((a) => [...a, { id: Date.now(), name: "", dose: "", frequency: "", adherence: "" }]);
  const med = (id, k, x) => setMeds((a) => a.map((m) => (m.id === id ? { ...m, [k]: x } : m)));
  // Only save when at least one reading or a named medicine has been entered.
  const hasData = VITAL_FIELDS.some((f) => String(v[f]).trim() !== "") || meds.some((m) => m.name.trim());
  const save = async () => {
    if (busy) return;
    if (!hasData) return toast(t("enterReading"));
    setBusy(true);
    try {
      const vitals = Object.fromEntries(VITAL_FIELDS.filter((f) => v[f] !== "").map((f) => [VITAL_API[f], Number(v[f])]));
      const medicines = meds
        .filter((m) => m.name.trim())
        .map((m) => ({ name: m.name.trim(), dose: m.dose || null, frequency: m.frequency || null, notes: m.adherence || null }));
      const enc = await api.post(`/patients/${patient.id}/encounters`, {
        reason: "Vitals and medicines update",
        triage: triage || "ROUTINE",
        vitals,
        medicines,
      });
      setUpdatedAt(enc.created_at);
      toast(enc.triage_suggestion || t("savedVitals"));
    } catch (e) {
      const fields = e.details?.fields;
      toast(
        fields
          ? `${e.message} ${Object.entries(fields)
              .map(([k, m]) => `${k}: ${m}`)
              .join(" · ")}`
          : e.message,
      );
    } finally {
      setBusy(false);
    }
  };
  return (
    <section className="panel vitals-panel" data-tour="vitals">
      <div className="panel-head">
        <div>
          <p className="eyebrow">Feature 02</p>
          <h3>{t("vitalsTitle")}</h3>
          <p className="muted">{patient.name}</p>
        </div>
        {updatedAt && (
          <span className="step-chip">
            {t("lastUpdated")} {new Date(updatedAt).toLocaleTimeString()}
          </span>
        )}
      </div>
      <div className="bp-highlight">
        <div className="bp-symbol">
          <span>♥</span>
          <i></i>
        </div>
        <div className="bp-copy">
          <span>{t("bloodPressure")}</span>
          <strong>
            {v.systolic || "—"} / {v.diastolic || "—"} <small>mmHg</small>
          </strong>
          <small>{t("bpReference")}</small>
        </div>
        <span className={`vital-status ${review ? "review" : "ok"}`}>{review ? t("reviewReading") : t("withinReference")}</span>
      </div>
      <div className="vitals-grid">
        <VitalInput label={t("systolic")} value={v.systolic} set={(x) => set("systolic", x)} unit="mmHg" />
        <VitalInput label={t("diastolic")} value={v.diastolic} set={(x) => set("diastolic", x)} unit="mmHg" />
        <VitalInput label={t("pulse")} value={v.pulse} set={(x) => set("pulse", x)} unit="bpm" />
        <VitalInput label={t("temperature")} value={v.temperature} set={(x) => set("temperature", x)} unit="°C" />
        <VitalInput label={t("spo2")} value={v.spo2} set={(x) => set("spo2", x)} unit="%" />
        <VitalInput label={t("respiratoryRate")} value={v.respiratoryRate} set={(x) => set("respiratoryRate", x)} unit="/min" />
        <VitalInput label={t("glucose")} value={v.glucose} set={(x) => set("glucose", x)} unit="mg/dL" />
        <VitalInput label={t("weight")} value={v.weight} set={(x) => set("weight", x)} unit="kg" />
      </div>
      <div className="medicine-section">
        <div className="section-title">
          <div>
            <p className="eyebrow">{t("medicinesTitle")}</p>
            <h4>{t("medicinesTitle")}</h4>
          </div>
          <button className="secondary-btn" onClick={add}>
            ＋ {t("addMedicine")}
          </button>
        </div>
        {meds.length === 0 ? (
          <div className="medicine-empty">{t("noMedicines")}</div>
        ) : (
          <div className="medicine-list">
            {meds.map((m) => (
              <div className="medicine-row" key={m.id}>
                <input value={m.name} onChange={(e) => med(m.id, "name", e.target.value)} placeholder={t("medicineName")} />
                <input value={m.dose} onChange={(e) => med(m.id, "dose", e.target.value)} placeholder={t("dose")} />
                <input
                  value={m.frequency}
                  onChange={(e) => med(m.id, "frequency", e.target.value)}
                  placeholder={t("frequency")}
                />
                <input
                  value={m.adherence}
                  onChange={(e) => med(m.id, "adherence", e.target.value)}
                  placeholder={t("adherence")}
                />
                <button className="link-btn remove-med" onClick={() => setMeds((a) => a.filter((x) => x.id !== m.id))}>
                  {t("remove")}
                </button>
              </div>
            ))}
          </div>
        )}
      </div>
      <div className="action-row">
        <button className="primary-btn" onClick={save} disabled={busy || !hasData} title={hasData ? "" : t("enterReading")}>
          {busy ? t("loading") : t("updateVitals")}
        </button>
      </div>
      <p className="medical-note">ℹ {t("bpNote")}</p>
    </section>
  );
}

// ---------- Patient (no login) ----------

function PatientDashboard() {
  const { t } = useLanguage();
  const [code, setCode] = useState("");
  const [last4, setLast4] = useState("");
  const [result, setResult] = useState(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [consult, setConsult] = useState(false);
  const find = async (e) => {
    e.preventDefault();
    if (!code.trim() || last4.length !== 4 || busy) return;
    setBusy(true);
    setError("");
    try {
      setResult(await lookupReferral(code.trim().toUpperCase(), last4));
    } catch (err) {
      setResult(null);
      setError(err.message);
    } finally {
      setBusy(false);
    }
  };
  const status = result ? pretty(result.status) : "";
  return (
    <Dashboard title={t("patientDashboard")} subtitle={t("patientSub")}>
      <div className="stats">
        <Stat
          tour="stats"
          label={t("myContinuity")}
          value={result?.code || "—"}
          meta={result ? t("activeJourney") : t("waitingReferral")}
        />
        <Stat
          label={t("destination")}
          value={result?.facility_name?.split(" ")[0] || "—"}
          meta={result?.facility_name || "No facility yet"}
        />
        <Stat label={t("currentStatus")} value={status || "Not started"} meta={t("updatedShared")} />
      </div>
      <section className="feature-grid">
        <div className="panel wide">
          <div className="panel-head">
            <div>
              <p className="eyebrow">Feature 02</p>
              <h3>{t("referralPass")}</h3>
            </div>
            <span className="status-badge">{status || "No referral"}</span>
          </div>
          <form className="lookup" data-tour="token" onSubmit={find}>
            <input
              value={code}
              onChange={(e) => setCode(e.target.value)}
              placeholder="Referral code e.g. SC-7K3M9Q"
              autoCapitalize="characters"
            />
            <input
              value={last4}
              onChange={(e) => setLast4(e.target.value.replace(/\D/g, "").slice(0, 4))}
              placeholder={t("phoneLast4")}
              inputMode="numeric"
              style={{ maxWidth: 170 }}
            />
            <button type="submit" className="secondary-btn" disabled={busy}>
              {t("find")}
            </button>
          </form>
          {result ? (
            <div data-tour="journey">
              {result.status === "REJECTED" ? (
                <Empty title={status} text={t("referralRejected")} />
              ) : (
                <PatientJourney status={result.status} />
              )}
            </div>
          ) : (
            <Empty title={error || t("noReferral")} text={t("askToken")} />
          )}
        </div>
        <div className="panel">
          <p className="eyebrow">{t("checklist")}</p>
          <h3>{t("beforeTravel")}</h3>
          <ul className="checklist">
            <li>{t("carryToken")}</li>
            <li>{t("medicines")}</li>
            <li>{t("phoneReach")}</li>
            <li>{t("showJourney")}</li>
          </ul>
        </div>
      </section>
      <section className="teleconsult-card" data-tour="consult">
        <div className="teleconsult-icon">✚</div>
        <div className="teleconsult-copy">
          <p className="eyebrow">eSanjeevani</p>
          <h3>{t("teleconsultTitle")}</h3>
          <p>{t("teleconsultText")}</p>
        </div>
        <button className="primary-btn" onClick={() => setConsult(true)}>
          {t("startConsult")} →
        </button>
      </section>
      {consult &&
        createPortal(
          <div
            className="consult-modal"
            role="dialog"
            aria-modal="true"
            onClick={(e) => e.target === e.currentTarget && setConsult(false)}
          >
            <div className="consult-modal-card">
              <button className="consult-close" onClick={() => setConsult(false)} aria-label={t("close")}>
                ×
              </button>
              <div className="teleconsult-icon large">✚</div>
              <p className="eyebrow">eSanjeevani</p>
              <h3>{t("teleconsultTitle")}</h3>
              <p className="muted">{t("teleconsultSoon")}</p>
              <button className="primary-btn" onClick={() => setConsult(false)}>
                {t("close")}
              </button>
            </div>
          </div>,
          document.body,
        )}
    </Dashboard>
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
            <b>{pretty(i === idx ? status : s)}</b>
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
  OVERDUE: { path: "escalate", label: "escalate", role: "COORDINATOR" },
};
const ROLE_NAME = { FACILITY_STAFF: "facility staff", DOCTOR: "doctor", COORDINATOR: "coordinator" };

function MedicalDashboard({ user, toast }) {
  const { t } = useLanguage();
  const [referrals, setReferrals] = useState(null);
  const [filter, setFilter] = useState("ALL");
  const [rejecting, setRejecting] = useState(null); // referral id
  const [reasons, setReasons] = useState([]);
  const [reason, setReason] = useState("");
  const [note, setNote] = useState("");
  const [busyId, setBusyId] = useState(null);
  const fail = (e) => toast(e.message);

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
      toast(`${r.code} · ${pretty(updated.status)}`);
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
      : open.filter((r) => filter === "ALL" || TRIAGE_LABEL[r.triage] === filter)
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
      {user?.role === "FACILITY_STAFF" && <PassScanner toast={toast} onDone={(r) => (replace(r), load())} />}
      <section className="panel">
        <div className="panel-head">
          <div>
            <p className="eyebrow">Feature 03</p>
            <h3>{t("operationsQueue")}</h3>
          </div>
          <div className="filters" data-tour="filters">
            {["ALL", "Emergency", "Priority", "Routine", "Closed"].map((f) => (
              <button key={f} className={filter === f ? "filter active" : "filter"} onClick={() => setFilter(f)}>
                {f}
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
              const mine = next && next.role === user?.role;
              return (
                <div className="queue-item" key={r.id} style={rejecting === r.id ? { flexWrap: "wrap" } : undefined}>
                  <div>
                    <span className={`urgency ${r.triage.toLowerCase()}`}>{TRIAGE_LABEL[r.triage]}</span>
                    <h4>{r.patient.name}</h4>
                    <p>
                      {r.code} · {r.facility.name} · {r.requested_service}
                    </p>
                    <p>{r.reason}</p>
                  </div>
                  <div className="queue-actions">
                    <span className="status-badge">{pretty(r.status)}</span>
                    <div style={{ display: "flex", gap: 9, alignItems: "center", flexWrap: "wrap" }}>
                      {!r.is_open ? (
                        <button className="secondary-btn" disabled>
                          {t("closed")}
                        </button>
                      ) : next ? (
                        <button
                          className="secondary-btn"
                          disabled={!mine || busyId === r.id}
                          title={mine ? "" : `${t("waitingFor")} ${ROLE_NAME[next.role]}`}
                          onClick={() => act(r, next.path)}
                        >
                          {mine ? t(next.label) : `${t("waitingFor")} ${ROLE_NAME[next.role]}`}
                        </button>
                      ) : (
                        <button className="secondary-btn" disabled>
                          {t("withAsha")}
                        </button>
                      )}
                      {r.status === "CREATED" && user?.role === "FACILITY_STAFF" && rejecting !== r.id && (
                        <button className="secondary-btn" onClick={() => setRejecting(r.id)} disabled={busyId === r.id}>
                          {t("reject")}
                        </button>
                      )}
                    </div>
                  </div>
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
                      <Field label="Note">
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
      toast(`${r.referral.code} · ${r.already_recorded ? pretty(r.referral.status) : t("recordArrival")} ✓`);
      setText("");
      onDone(r.referral);
    } catch (e) {
      toast(e.message);
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
