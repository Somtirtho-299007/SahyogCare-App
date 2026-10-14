import React, { useCallback, useEffect, useRef, useState } from "react";
import { createRoot } from "react-dom/client";
import { createPortal } from "react-dom";
import QRCode from "qrcode";
import "./styles.css";
import "./language-sidebar.css";
import {
  api,
  currentUser,
  getDistricts,
  loginMethods,
  logout,
  lookupReferral,
  newKey,
  qs,
  refreshMe,
  request,
  requestCode,
  uploadPhoto,
  verifyCode,
} from "./api.js";
import {
  FlagChip,
  PatientHealthPortal,
  PatientRecord,
  PatientRegister,
  PhotoPicker,
  PhotoView,
  VitalsGrid,
  VitalsReadout,
  useVitalRanges,
} from "./health.jsx";
import { LanguageProvider, LanguageSidebar, readLS, useLanguage, writeLS } from "./i18n.jsx";
import { TOURS, Tour } from "./tour.jsx";
import { Dashboard, Empty, Field, Skeleton, Stat } from "./ui.jsx";

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
const isMobile = (x) => /^[6-9]\d{9}$/.test(x.trim());
const pretty = (s) => (s || "").replaceAll("_", " ");
const REFRESH_MS = 15000;

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
    // Drafts belong to the person who wrote them: clear them on this shared phone.
    try {
      Object.keys(localStorage)
        .filter((k) => k.startsWith("sahyog_"))
        .forEach((k) => localStorage.removeItem(k));
    } catch {
      /* storage unavailable */
    }
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
          onPatient={() => {
            signOut();
            signIn({ screen: "patient", user: null });
          }}
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
        {session.screen === "patient" && <PatientDashboard toast={setToast} />}
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

function AccessScreen({ user, onApproved, onSignOut, onPatient }) {
  const [mine, setMine] = useState(undefined); // undefined = loading, null = no request yet
  const [facilities, setFacilities] = useState([]);
  // Nobody is put in an area by default: each person picks where they work.
  const [form, setForm] = usePersisted("sahyog_join_form", {
    role: "WORKER",
    name: "",
    facility_id: "",
    note: "",
    district: "",
  });
  const [districts, setDistricts] = useState(null); // null while loading
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [photoId, setPhotoId] = useState(user.photo_id || null);
  const [photoBusy, setPhotoBusy] = useState(false);
  const set = (k) => (e) => setForm((f) => ({ ...f, [k]: e.target.value }));
  // Her own photo, so the district office can check a real ASHA is joining.
  const addPhoto = async (file) => {
    setPhotoBusy(true);
    setError("");
    try {
      setPhotoId((await uploadPhoto(file, "user")).id);
    } catch (e) {
      setError(e.message);
    } finally {
      setPhotoBusy(false);
    }
  };

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
    getDistricts()
      .then(setDistricts)
      .catch(() => setDistricts([]));
  }, []);
  useEffect(() => {
    if (!form.district) return setFacilities([]);
    api.get(`/facilities${qs({ district: form.district })}`).then(setFacilities).catch(() => {});
  }, [form.district]);

  const submit = async () => {
    setBusy(true);
    setError("");
    try {
      const body = { role: form.role, name: form.name.trim(), note: form.note.trim() || null, district: form.district };
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

  const [invite, setInvite] = useState("");
  const [passphrase, setPassphrase] = useState("");
  const enterOffice = async () => {
    setBusy(true);
    setError("");
    try {
      await api.post("/invite-codes/office", { district: form.district, name: form.name.trim(), passphrase });
      setPassphrase("");
      await check();
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  };
  const redeem = async () => {
    setBusy(true);
    setError("");
    try {
      await api.post("/invite-codes/redeem", { code: invite.trim(), name: form.name.trim() });
      await check();
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  };

  const waiting = mine?.status === "PENDING";
  const canSend = form.name.trim() && form.district && (!NEEDS_HOSPITAL.has(form.role) || form.facility_id);
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
            <input id="join-name" value={form.name} onChange={set("name")} placeholder="Full name" />
            <label>Where you work</label>
            {districts === null ? (
              <p className="otp-note">Loading areas…</p>
            ) : districts.length === 0 ? (
              <p className="otp-note" role="alert">Could not load the list of areas. Refresh the page.</p>
            ) : null}
            <div className="role-grid area-grid">
              {(districts || []).map((d) => (
                <button
                  key={d}
                  className={`role-choice ${form.district === d ? "selected" : ""}`}
                  onClick={() => setForm((f) => ({ ...f, district: d, facility_id: "" }))}
                >
                  <span>{d}</span>
                  <small>Approved by the {d} office</small>
                </button>
              ))}
            </div>
            <label>Invite code from your district office</label>
            <input
              value={invite}
              onChange={(e) => setInvite(e.target.value.toUpperCase())}
              placeholder="e.g. HS-KAL-7K3M9QWX"
              autoCapitalize="characters"
            />
            <button className="primary-btn" onClick={redeem} disabled={!invite.trim() || !form.name.trim() || busy}>
              {busy ? "Checking…" : "Join with code"}
            </button>
            <p className="otp-note">No code? Ask to join below and the district office will approve you.</p>
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
                <select className="join-select" value={form.facility_id} onChange={set("facility_id")}>
                  <option value="">Choose your hospital</option>
                  {facilities.map((f) => (
                    <option key={f.id} value={f.id}>
                      {f.name}
                    </option>
                  ))}
                </select>
              </>
            )}
            {form.role === "COORDINATOR" ? (
              <>
                <label>District office passphrase</label>
                <input
                  id="office-passphrase"
                  type="password"
                  autoComplete="off"
                  value={passphrase}
                  onChange={(e) => setPassphrase(e.target.value)}
                  placeholder={form.district ? `The ${form.district} office passphrase` : "Choose your area first"}
                />
                <button
                  className="primary-btn"
                  onClick={enterOffice}
                  disabled={!form.district || !form.name.trim() || !passphrase || busy}
                >
                  {busy ? "Checking…" : "Enter as district office"}
                </button>
                <p className="otp-note">Only the district office knows this passphrase. Wrong tries are limited.</p>
              </>
            ) : (
              <>
                <label>How the coordinator can confirm it's you (optional)</label>
                <input value={form.note} onChange={set("note")} placeholder="e.g. ASHA, Chakdaha block, ID 1234" />
                <label>Your photo {form.role === "WORKER" ? "(helps the district office confirm you are a real ASHA)" : "(optional)"}</label>
                <div className="photo-line">
                  {photoId && <PhotoView id={photoId} alt="You" className="photo-mini" />}
                  <PhotoPicker label={photoId ? "Retake" : "Take a selfie"} onFile={addPhoto} busy={photoBusy} />
                </div>
                <button className="primary-btn" onClick={submit} disabled={!canSend || busy}>
                  {busy ? "Sending…" : "Ask to join"}
                </button>
              </>
            )}
          </>
        )}
        {error && (
          <div className="otp-note" role="alert">
            {error}
          </div>
        )}
        <button className="link-btn" onClick={onPatient}>
          I'm a patient: track my referral
        </button>
        <button className="link-btn" onClick={onSignOut}>
          Sign out
        </button>
      </div>
    </div>
  );
}

// ---------- Coordinator ----------

const ROLE_LABEL = Object.fromEntries(REQUEST_ROLES.map((r) => [r.role, r.label]));

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
    <Dashboard
      title={`${user?.district || ""} ${t("coordinatorDashboard")}`.trim()}
      subtitle={`${t("coordinatorSub")} You see only ${user?.district || "your area"}.`}
    >
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
                <div className="request-who">
                  <PhotoView id={r.photo_id} alt={r.name} className="photo-face" />
                  <div>
                  <span className="status-badge">{ROLE_LABEL[r.requested_role] || pretty(r.requested_role)}</span>
                  <h4>{r.name}</h4>
                  {!r.photo_id && r.requested_role === "WORKER" && <small className="muted">No photo yet</small>}
                  <p>
                    {r.email || r.phone}
                    {r.facility_name ? ` · ${r.facility_name}` : ""}
                    {r.note ? ` · ${r.note}` : ""}
                  </p>
                  </div>
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
      <InvitePanel facilities={facilities || []} toast={toast} />
      <HospitalsPanel facilities={facilities} toast={toast} onChange={load} />
    </Dashboard>
  );
}

const INVITE_ROLES = [
  { role: "WORKER", label: "ASHA (whole district)" },
  { role: "FACILITY_STAFF", label: "Hospital staff" },
  { role: "DOCTOR", label: "Doctor" },
  { role: "COORDINATOR", label: "Another coordinator (1 use, 7 days)" },
];

function InvitePanel({ facilities, toast }) {
  const [codes, setCodes] = useState(null);
  const [form, setForm] = useState({ role: "WORKER", facility_id: "", max_uses: "", days: "30", label: "" });
  const [busy, setBusy] = useState(false);
  const set = (k) => (e) => setForm((f) => ({ ...f, [k]: e.target.value }));
  const load = useCallback(async () => {
    try {
      setCodes(await api.get("/invite-codes"));
    } catch (e) {
      if (e.status !== 401) toast(e.message);
    }
  }, [toast]);
  usePolling(load);

  const create = async () => {
    setBusy(true);
    try {
      const body = { role: form.role, label: form.label.trim() || null, expires_in_days: Number(form.days) || null };
      if (NEEDS_HOSPITAL.has(form.role)) body.facility_id = form.facility_id;
      if (form.max_uses) body.max_uses = Number(form.max_uses);
      const c = await api.post("/invite-codes", body);
      setCodes((list) => [c, ...(list || [])]);
      toast(`Code ${c.code} created`);
    } catch (e) {
      toast(e.message);
    } finally {
      setBusy(false);
    }
  };
  const revoke = async (c) => {
    try {
      const r = await api.post(`/invite-codes/${c.id}/revoke`);
      setCodes((list) => list.map((x) => (x.id === r.id ? r : x)));
      toast(`${c.code} revoked`);
    } catch (e) {
      toast(e.message);
    }
  };
  const copy = async (c) => {
    try {
      await navigator.clipboard.writeText(c.code);
      toast("Code copied");
    } catch {
      toast(c.code);
    }
  };

  const canCreate = !NEEDS_HOSPITAL.has(form.role) || form.facility_id;
  return (
    <section className="panel" data-tour="invites" style={{ marginTop: 18 }}>
      <div className="panel-head">
        <div>
          <p className="eyebrow">Invite codes</p>
          <h3>Let people join without waiting</h3>
        </div>
      </div>
      <div className="form-grid">
        <Field label="Who is this code for">
          <select value={form.role} onChange={set("role")}>
            {INVITE_ROLES.map((r) => (
              <option key={r.role} value={r.role}>
                {r.label}
              </option>
            ))}
          </select>
        </Field>
        {NEEDS_HOSPITAL.has(form.role) ? (
          <Field label="Hospital">
            <select value={form.facility_id} onChange={set("facility_id")}>
              <option value="">Choose a hospital</option>
              {facilities.map((f) => (
                <option key={f.id} value={f.id}>
                  {f.name}
                </option>
              ))}
            </select>
          </Field>
        ) : (
          <Field label="Note (optional)">
            <input value={form.label} onChange={set("label")} placeholder="e.g. Chakdaha block training" />
          </Field>
        )}
        {form.role !== "COORDINATOR" && (
          <>
            <Field label="How many people can use it (empty = no limit)">
              <input inputMode="numeric" value={form.max_uses} onChange={set("max_uses")} placeholder="e.g. 25" />
            </Field>
            <Field label="Valid for (days)">
              <input inputMode="numeric" value={form.days} onChange={set("days")} />
            </Field>
          </>
        )}
      </div>
      <div className="action-row">
        <button className="primary-btn" onClick={create} disabled={!canCreate || busy}>
          {busy ? "Creating…" : "Create code"}
        </button>
      </div>
      {codes === null ? (
        <Skeleton />
      ) : codes.length === 0 ? (
        <Empty title="No codes yet" text="Create one and share it privately, e.g. by SMS to the people it is for." />
      ) : (
        <div className="queue" style={{ marginTop: 16 }}>
          {codes.map((c) => (
            <div className="queue-item" key={c.id}>
              <div>
                <span className="status-badge">{c.usable ? "Active" : c.revoked ? "Revoked" : "Expired / used up"}</span>
                <h4 style={{ fontFamily: "monospace", letterSpacing: ".05em" }}>{c.code}</h4>
                <p>
                  {INVITE_ROLES.find((r) => r.role === c.role)?.label}
                  {c.facility_name ? ` · ${c.facility_name}` : ""}
                  {c.label ? ` · ${c.label}` : ""} · used {c.uses}
                  {c.max_uses ? ` of ${c.max_uses}` : ""}
                  {c.expires_at ? ` · until ${new Date(c.expires_at).toLocaleDateString()}` : ""}
                </p>
              </div>
              {c.usable && (
                <div className="queue-actions">
                  <button className="secondary-btn" onClick={() => copy(c)}>
                    Copy
                  </button>
                  <button className="secondary-btn" onClick={() => revoke(c)}>
                    Revoke
                  </button>
                </div>
              )}
            </div>
          ))}
        </div>
      )}
    </section>
  );
}

const WARDS = ["GENERAL", "EMERGENCY", "MATERNITY", "PAEDIATRIC", "ICU"];

function HospitalsPanel({ facilities, toast, onChange }) {
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
      toast(e.message);
    } finally {
      setBusy(false);
    }
  };
  const saveBeds = (f) =>
    run(
      () => request("PUT", `/facilities/${f.id}/beds/${bed.ward}`, { total: Number(bed.total), occupied: Number(bed.occupied) }),
      `${f.name}: ${pretty(bed.ward).toLowerCase()} beds saved`,
    );
  const addService = (f) =>
    run(() => request("PATCH", `/facilities/${f.id}`, { add_services: [service.trim()] }), `${service.trim()} added`).then(() =>
      setService(""),
    );
  const toggleAmbulance = (f) =>
    run(() => request("PATCH", `/facilities/${f.id}`, { has_ambulance: !f.has_ambulance }), "Ambulance updated");
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
      `${form.name.trim()} added`,
    ).then(() => {
      setForm(blank);
      setAdding(false);
    });

  const bedsValid = bed.total !== "" && bed.occupied !== "" && Number(bed.occupied) <= Number(bed.total);
  return (
    <section className="panel" data-tour="beds" style={{ marginTop: 18 }}>
      <div className="panel-head">
        <div>
          <p className="eyebrow">Hospitals & beds</p>
          <h3>Hospitals in the district</h3>
        </div>
        <button className="secondary-btn" onClick={() => setAdding((x) => !x)}>
          {adding ? "Close" : "+ Add hospital"}
        </button>
      </div>
      {adding && (
        <div className="form-grid" style={{ marginBottom: 16 }}>
          <Field label="Name">
            <input value={form.name} onChange={set("name")} placeholder="e.g. Karimpur Rural Hospital" />
          </Field>
          <Field label="Type">
            <input value={form.type} onChange={set("type")} />
          </Field>
          <Field label="Address" full>
            <input value={form.address} onChange={set("address")} />
          </Field>
          <Field label="PIN code">
            <input inputMode="numeric" maxLength="6" value={form.pincode} onChange={set("pincode")} />
          </Field>
          <Field label="Phone">
            <input inputMode="tel" value={form.phone} onChange={set("phone")} />
          </Field>
          <Field label="Services (comma-separated)" full>
            <input value={form.services} onChange={set("services")} />
          </Field>
          <Field label="Where these details come from" full>
            <input value={form.source} onChange={set("source")} placeholder="e.g. nadia.gov.in hospital list" />
          </Field>
          <div className="action-row" style={{ gridColumn: "1/-1" }}>
            <button
              className="primary-btn"
              disabled={busy || form.name.trim().length < 2 || !form.services.trim() || (form.pincode && !/^\d{6}$/.test(form.pincode))}
              onClick={addHospital}
            >
              Save hospital
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
                    {f.phone ? <a href={`tel:${f.phone}`}>{f.phone}</a> : "No phone yet"}
                    {f.has_ambulance ? " · has ambulance" : ""}
                    {f.source ? ` · Source: ${f.source}` : ""}
                  </p>
                  <div className="ward-chips">
                    {(f.services || []).map((s) => (
                      <span key={s.service} className="step-chip">
                        {s.service}
                      </span>
                    ))}
                  </div>
                  <div className="ward-chips">
                    {(f.wards || []).length === 0 ? (
                      <span className="step-chip">No bed data yet</span>
                    ) : (
                      f.wards.map((w) => (
                        <span key={w.ward} className="step-chip" title={w.stale ? "Not confirmed in the last 12 hours" : ""}>
                          {pretty(w.ward).toLowerCase()}: <b>{w.free}</b> free of {w.total}
                          {w.stale ? " · old" : ""}
                        </span>
                      ))
                    )}
                  </div>
                </div>
                <div className="queue-actions" style={{ alignSelf: "flex-start" }}>
                  <button className="secondary-btn" onClick={() => setOpen(open === f.id ? null : f.id)}>
                    {open === f.id ? "Done" : "Manage"}
                  </button>
                </div>
              </div>
              {open === f.id && (
                <div className="form-grid" style={{ marginTop: 12 }}>
                  <Field label="Ward">
                    <select value={bed.ward} onChange={(e) => setBed((b) => ({ ...b, ward: e.target.value }))}>
                      {WARDS.map((w) => (
                        <option key={w} value={w}>
                          {pretty(w).toLowerCase()}
                        </option>
                      ))}
                    </select>
                  </Field>
                  <Field label="Total beds / occupied now">
                    <div style={{ display: "flex", gap: 8 }}>
                      <input inputMode="numeric" placeholder="Total" value={bed.total}
                        onChange={(e) => setBed((b) => ({ ...b, total: e.target.value.replace(/\D/g, "") }))} />
                      <input inputMode="numeric" placeholder="Occupied" value={bed.occupied}
                        onChange={(e) => setBed((b) => ({ ...b, occupied: e.target.value.replace(/\D/g, "") }))} />
                    </div>
                  </Field>
                  <div className="action-row" style={{ gridColumn: "1/-1", marginTop: 0 }}>
                    <button className="primary-btn" disabled={!bedsValid || busy} onClick={() => saveBeds(f)}>
                      Save beds
                    </button>
                    <button className="secondary-btn" disabled={busy} onClick={() => toggleAmbulance(f)}>
                      {f.has_ambulance ? "Mark: no ambulance" : "Mark: has ambulance"}
                    </button>
                  </div>
                  <Field label="Add a service this hospital offers" full>
                    <div style={{ display: "flex", gap: 8 }}>
                      <input value={service} onChange={(e) => setService(e.target.value)} placeholder="e.g. Maternity" />
                      <button className="secondary-btn" disabled={!service.trim() || busy} onClick={() => addService(f)}>
                        Add
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
  return (
    <div className={`emergency-box ${compact ? "compact" : ""}`} role="note">
      <span className="emergency-dot" aria-hidden="true" />
      <div>
        <b>Emergency ambulance: {EMERGENCY_NUMBER}</b>
        {!compact && <small>Free, 24×7. Call when the hospital's own ambulance is not coming quickly.</small>}
      </div>
      <a className="secondary-btn" href={`tel:${EMERGENCY_NUMBER}`}>
        Call {EMERGENCY_NUMBER}
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
      toast?.("Patient summary copied");
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
                  Copy patient summary for the doctor
                </button>
              )}
              <a className="primary-btn link-as-btn" href={ESANJEEVANI_URL} target="_blank" rel="noopener noreferrer"
                onClick={() => setOpen(false)}>
                Go to esanjeevani.mohfw.gov.in ↗
              </a>
            </div>
          </div>,
          document.body,
        )}
    </>
  );
}

const BED_TEXT = { HELD: "Bed held", OCCUPIED: "In bed", RELEASED: "Bed released", EXPIRED: "Bed hold expired" };

function BedChip({ bed }) {
  if (!bed) return <span className="chip muted-chip">No bed held</span>;
  const ward = pretty(bed.ward).toLowerCase();
  return (
    <span className={`chip bed-${bed.status.toLowerCase()}`} title={bed.release_reason || ""}>
      {BED_TEXT[bed.status]} · {ward}
      {bed.status === "HELD" ? ` · until ${new Date(bed.held_until).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}` : ""}
    </span>
  );
}

function RecommendationRow({ r, picked, onPick }) {
  const beds =
    r.ward === null ? "No bed needed" : r.beds_free === null ? "No bed data" : `${r.beds_free} of ${r.beds_total} free`;
  const tone = r.ward === null || r.beds_free === null ? "" : r.beds_free > 0 ? "good" : "bad";
  return (
    <button className={`facility ${picked ? "picked" : ""}`} onClick={() => onPick(r)}>
      <div style={{ minWidth: 0 }}>
        <b>{r.facility_name}</b>
        <span>
          {r.facility_type}
          {r.phone ? ` · ☎ ${r.phone}` : ""}
          {r.has_ambulance ? " · ambulance" : ""}
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
  const [alts, setAlts] = useState(null);
  const [busy, setBusy] = useState(false);
  useEffect(() => {
    api.get(`/referrals/${referral.id}/alternatives`).then(setAlts).catch((e) => toast(e.message));
  }, [referral.id]);
  const send = async (alt, allow = false) => {
    setBusy(true);
    try {
      const fresh = await api.post(`/referrals/${referral.id}/reroute`, {
        destination_facility_id: alt.facility_id,
        allow_without_bed: allow,
      });
      toast(`Sent to ${alt.facility_name} · new code ${fresh.code}`);
      onDone(fresh);
    } catch (e) {
      if (e.code === "NO_BEDS_AVAILABLE") toast(`${alt.facility_name} has no free bed now. Pick another.`);
      else toast(e.message);
    } finally {
      setBusy(false);
    }
  };
  if (alts === null) return <Skeleton />;
  if (alts.length === 0) return <Empty title="No other hospital offers this service" text="Call the district office." />;
  return (
    <div className="facility-list reveal">
      {alts.map((a) => (
        <div key={a.facility_id} className="alt-row">
          <RecommendationRow r={a} onPick={() => send(a)} />
          {a.beds_free === 0 && (
            <button className="link-btn" disabled={busy} onClick={() => send(a, true)}>
              Send anyway
            </button>
          )}
        </div>
      ))}
    </div>
  );
}

const AMB_TEXT = {
  REQUESTED: "Ambulance requested",
  DISPATCHED: "Ambulance on the way",
  PICKED_UP: "Patient in ambulance",
  COMPLETED: "Reached hospital",
  CANCELLED: "Ambulance cancelled",
};

function AmbulanceInfo({ amb }) {
  if (!amb) return null;
  return (
    <div className={`amb-card amb-${amb.status.toLowerCase()}`}>
      <b>🚑 {AMB_TEXT[amb.status]}</b>
      <small>
        {amb.expected_at && amb.status === "DISPATCHED" ? `Expected ${fmtTime(amb.expected_at)}` : ""}
        {amb.vehicle_number ? ` · ${amb.vehicle_number}` : ""}
        {amb.driver_phone ? ` · Driver ${amb.driver_phone}` : ""}
        {amb.cancel_reason ? ` · ${amb.cancel_reason}` : ""}
      </small>
    </div>
  );
}

// ASHA: ask the hospital for its ambulance, see it coming, or fall back to 108.
function AshaAmbulance({ referral, onChange, toast }) {
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
      toast(e.code === "NO_HOSPITAL_AMBULANCE" ? `${referral.facility.name} has no ambulance. Call ${EMERGENCY_NUMBER}.` : e.message);
    } finally {
      setBusy(false);
    }
  };
  return (
    <div className="amb-block">
      <AmbulanceInfo amb={amb} />
      {canAsk && (
        <div className="inline-form">
          <input value={pickup} onChange={(e) => setPickup(e.target.value)} placeholder="Pickup: village, landmark, house" />
          <button
            className="secondary-btn"
            disabled={busy || pickup.trim().length < 3}
            onClick={() => run(() => api.post(`/referrals/${referral.id}/ambulance`, { pickup_note: pickup.trim() }), "Ambulance requested")}
          >
            Request hospital ambulance
          </button>
        </div>
      )}
      {amb?.status === "DISPATCHED" && (
        <button className="secondary-btn" disabled={busy}
          onClick={() => run(() => api.post(`/referrals/${referral.id}/ambulance/picked-up`), "Marked: patient picked up")}>
          Patient is in the ambulance
        </button>
      )}
      {referral.is_open && ["CREATED", "ACCEPTED"].includes(referral.status) && <EmergencyBox compact />}
    </div>
  );
}

// Hospital desk: keep this hospital's beds current.
function StaffBedsPanel({ facilityId, toast }) {
  const [facility, setFacility] = useState(null);
  const [bed, setBed] = usePersisted("sahyog_staff_bed_form", { ward: "GENERAL", total: "", occupied: "" });
  const [busy, setBusy] = useState(false);
  const load = useCallback(async () => {
    try {
      setFacility(await api.get(`/facilities/${facilityId}`));
    } catch (e) {
      if (e.status !== 401) toast(e.message);
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
      toast(`${pretty(bed.ward).toLowerCase()} beds updated`);
    } catch (e) {
      toast(e.message);
    } finally {
      setBusy(false);
    }
  };
  const valid = bed.total !== "" && bed.occupied !== "" && Number(bed.occupied) <= Number(bed.total);
  return (
    <section className="panel" data-tour="beds" style={{ marginBottom: 18 }}>
      <div className="panel-head">
        <div>
          <p className="eyebrow">Beds</p>
          <h3>{facility ? facility.name : "Your hospital"}</h3>
        </div>
      </div>
      <div className="ward-chips" style={{ marginBottom: 14 }}>
        {facility === null ? (
          <span className="chip muted-chip">Loading…</span>
        ) : facility.wards.length === 0 ? (
          <span className="chip muted-chip">No beds reported yet. Add your first ward below.</span>
        ) : (
          facility.wards.map((w) => (
            <span key={w.ward} className={`chip ${w.free > 0 ? "bed-held" : "bed-expired"}`} title={w.stale ? "Not confirmed in 12 hours" : ""}>
              {pretty(w.ward).toLowerCase()}: <b>{w.free}</b> free · {w.held} held · {w.occupied}/{w.total} occupied
              {w.stale ? " · please confirm" : ""}
            </span>
          ))
        )}
      </div>
      <div className="form-grid">
        <Field label="Ward">
          <select id="staff-ward" value={bed.ward} onChange={(e) => setBed({ ...bed, ward: e.target.value })}>
            {WARDS.map((w) => (
              <option key={w} value={w}>
                {pretty(w).toLowerCase()}
              </option>
            ))}
          </select>
        </Field>
        <Field label="Total beds / occupied now">
          <div style={{ display: "flex", gap: 8 }}>
            <input id="staff-total" inputMode="numeric" placeholder="Total" value={bed.total}
              onChange={(e) => setBed({ ...bed, total: e.target.value.replace(/\D/g, "") })} />
            <input id="staff-occupied" inputMode="numeric" placeholder="Occupied" value={bed.occupied}
              onChange={(e) => setBed({ ...bed, occupied: e.target.value.replace(/\D/g, "") })} />
          </div>
        </Field>
      </div>
      <div className="action-row">
        <button className="primary-btn" disabled={!valid || busy} onClick={save}>
          Save beds
        </button>
      </div>
    </section>
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
  const [phoneOk, setPhoneOk] = useState(false);
  useEffect(() => {
    loginMethods()
      .then((m) => setPhoneOk(!!m.phone))
      .catch(() => {});
  }, []);
  const validId = isEmail(email) || (phoneOk && isMobile(email));
  const sendOtp = async () => {
    if (!validId || busy) return;
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
              <label>{phoneOk ? "Email or mobile number" : t("email")}</label>
              <input
                data-tour="email"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                onKeyDown={(e) => e.key === "Enter" && !sent && sendOtp()}
                readOnly={sent}
                placeholder={phoneOk ? "you@gmail.com or 98XXXXXXXX" : "you@gmail.com"}
                type={phoneOk ? "text" : "email"}
                autoComplete={phoneOk ? "username" : "email"}
              />
              {!sent ? (
                <button className="primary-btn" onClick={sendOtp} disabled={!validId || busy}>
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
  const fail = (e) => toast(e.message);

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
      toast(patient.possible_duplicate_of ? "Saved. A patient with this name and phone already exists." : "Patient case saved");
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
      toast(r.bed ? "Referral sent · bed held" : "Referral sent");
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
          👥 My patients
        </button>
        <button role="tab" aria-selected={view === "referral"} className={view === "referral" ? "tab active" : "tab"} onClick={() => setView("referral")}>
          ➜ Referral{referral?.is_open ? ` · ${referral.code}` : ""}
        </button>
      </div>
      {view === "patients" && (
        <>
          {alerts.length > 0 && (
            <section className="panel alerts-strip">
              {alerts.slice(0, 4).map((n) => (
                <div className="mini-ref" key={n.id} role="button" tabIndex={0} onClick={() => readAlert(n)} title="Mark as read">
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
          {step === 0 && form.patientId && (
            <div className="known-patient">
              <b>{form.name}</b> · {form.age} y · 📞 {form.phone}
              <small>On your register — this referral is added to the same record.</small>
              <button className="link-btn" onClick={newCase}>
                Someone else
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
                        {x}
                      </option>
                    ))}
                  </select>
                </Field>
                <Field label={t("searchFacility")}>
                  <input id="asha-search" value={search} onChange={(e) => setSearch(e.target.value)} placeholder="Hospital name" />
                </Field>
              </div>
              <p className="muted small-note">Best match first: free beds in the right ward, recent answers, and distance.</p>
              {loadingFacilities && facilities.length === 0 ? (
                <Skeleton />
              ) : shown.length === 0 ? (
                <Empty title={t("noFacility")} text="No hospital in your area lists this service yet." />
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
                  {noBeds.alternatives.length > 0 && <p>These have free beds now:</p>}
                  <div className="facility-list">
                    {noBeds.alternatives.map((a) => (
                      <RecommendationRow key={a.facility_id} r={a} onPick={(x) => (setSelected(x), createReferral(false, x))} />
                    ))}
                  </div>
                  <button className="link-btn" disabled={busy} onClick={() => createReferral(true)}>
                    Send to {selected?.facility_name} anyway (no bed held)
                  </button>
                </div>
              )}
              {!current?.encounter && (
                <p className="muted small-note">Save the patient's case first (step 1).</p>
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
              <h3>{referral.is_open ? t("referralLive") : pretty(referral.status)}</h3>
              <p>
                {referral.patient.name} → {referral.facility.name} · {referral.requested_service}
              </p>
              <div className="ward-chips" style={{ justifyContent: "center" }}>
                <BedChip bed={referral.bed} />
                {referral.rerouted_from_code && <span className="chip">Continues {referral.rerouted_from_code}</span>}
                {referral.rerouted_to_code && <span className="chip bed-released">Sent on as {referral.rerouted_to_code}</span>}
              </div>
              {referral.facility.phone && (
                <p className="muted">
                  Hospital desk: <a href={`tel:${referral.facility.phone}`}>{referral.facility.phone}</a>
                </p>
              )}
              <AshaAmbulance referral={referral} onChange={(r) => (setReferralState(r), load())} toast={toast} />
              {["CREATED", "ACCEPTED", "REJECTED"].includes(referral.status) && !referral.rerouted_to_id && (
                <div className="reroute-block">
                  {!rerouting ? (
                    <button className="secondary-btn" onClick={() => setRerouting(true)}>
                      {referral.status === "REJECTED" ? "Choose another hospital" : "Send to another hospital"}
                    </button>
                  ) : (
                    <>
                      <p className="muted small-note">Other hospitals for {referral.requested_service}, best first:</p>
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
          <h4>Select a patient case first</h4>
          <p>Readings appear here after a case is created. Medicines are on the patient's record (My patients).</p>
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
          <p className="eyebrow">Feature 02</p>
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
      <p className="medical-note">ℹ Normal ranges are for adults at rest and are guides only; children and pregnancy differ. The ASHA and doctor decide.</p>
    </section>
  );
}

// ---------- Patient (no login) ----------

function PatientDashboard({ toast }) {
  const { t } = useLanguage();
  const [ptab, setPtab] = usePersisted("sahyog_patient_tab", "health"); // health | track
  const [code, setCode] = usePersisted("sahyog_patient_code", "");
  const [last4, setLast4] = usePersisted("sahyog_patient_last4", "");
  const [result, setResult] = useState(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const lookup = async (c = code, l = last4) => {
    if (!c.trim() || l.length !== 4) return;
    setBusy(true);
    setError("");
    try {
      setResult(await lookupReferral(c.trim().toUpperCase(), l));
    } catch (err) {
      setResult(null);
      setError(err.message);
    } finally {
      setBusy(false);
    }
  };
  const find = (e) => {
    e.preventDefault();
    if (!busy) lookup();
  };
  // After a refresh, show the last referral looked up on this phone again.
  useEffect(() => {
    if (code && last4.length === 4) lookup();
  }, []);
  const status = result ? pretty(result.status) : "";
  return (
    <Dashboard title={t("patientDashboard")} subtitle={t("patientSub")}>
      <div className="view-tabs" role="tablist">
        <button role="tab" aria-selected={ptab === "health"} className={ptab === "health" ? "tab active" : "tab"} onClick={() => setPtab("health")}>
          ♡ {t("myHealth")}
        </button>
        <button role="tab" aria-selected={ptab === "track"} className={ptab === "track" ? "tab active" : "tab"} onClick={() => setPtab("track")}>
          ➜ {t("trackReferral")}
        </button>
      </div>
      {ptab === "health" && <PatientHealthPortal toast={toast} />}
      {ptab === "track" && (
      <>
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
            <div data-tour="journey" className="reveal">
              {result.rerouted_to_code ? (
                <div className="notice good">
                  <b>
                    You were sent to {result.rerouted_to_facility}. Your new code is {result.rerouted_to_code}.
                  </b>
                  <button
                    className="secondary-btn"
                    onClick={() => (setCode(result.rerouted_to_code), lookup(result.rerouted_to_code, last4))}
                  >
                    Track the new referral
                  </button>
                </div>
              ) : result.status === "REJECTED" ? (
                <Empty title={status} text={t("referralRejected")} />
              ) : (
                <PatientJourney status={result.status} />
              )}
              {result.ambulance && <AmbulanceInfo amb={result.ambulance} />}
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
      </>
      )}
      <EmergencyBox />
      <ESanjeevaniCard toast={toast} summary={result ? `SahyogCare referral ${result.code} to ${result.facility_name}.` : ""} />
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
  // The follow-up checkup happens at the hospital, so staff or the doctor confirm it (the ASHA only sends the patient).
  FOLLOW_UP_DUE: { path: "close", label: "checkupDone", role: "FACILITY_STAFF", also: "DOCTOR" },
  OVERDUE: { path: "close", label: "checkupDone", role: "FACILITY_STAFF", also: "DOCTOR" },
  ESCALATED: { path: "close", label: "checkupDone", role: "FACILITY_STAFF", also: "DOCTOR" },
};
const ROLE_NAME = { FACILITY_STAFF: "facility staff", DOCTOR: "doctor", COORDINATOR: "coordinator" };

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
      {user?.role === "FACILITY_STAFF" && user.facility_id && <StaffBedsPanel facilityId={user.facility_id} toast={toast} />}
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
              const mine = next && (next.role === user?.role || next.also === user?.role);
              return (
                <div className="queue-item" key={r.id} style={rejecting === r.id ? { flexWrap: "wrap" } : undefined}>
                  <div>
                    <span className={`urgency ${r.triage.toLowerCase()}`}>{TRIAGE_LABEL[r.triage]}</span>
                    <h4>{r.patient.name}</h4>
                    <p>
                      {r.code} · {r.facility.name} · {r.requested_service}
                    </p>
                    <p>{r.reason}</p>
                    {r.origin === "PATIENT_EMERGENCY" && <span className="chip deceased-chip">🚨 Booked by the patient at night</span>}
                    {r.latest_vitals ? (
                      <div className="queue-vitals">
                        <small className="muted">Latest readings · {new Date(r.latest_vitals_at).toLocaleString()}</small>
                        <VitalsReadout vitals={r.latest_vitals} flags={r.vitals_flags} ranges={ranges} />
                      </div>
                    ) : (
                      <div className="queue-vitals">
                        <VitalsReadout vitals={r.vitals} flags={r.vitals_flags} ranges={ranges} />
                      </div>
                    )}
                    <div className="ward-chips">
                      <BedChip bed={r.bed} />
                      {r.rerouted_from_code && <span className="chip">Sent on from {r.rerouted_from_code}</span>}
                      {r.status === "REROUTED" && <span className="chip bed-released">Patient sent elsewhere</span>}
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
                      {user?.role === "FACILITY_STAFF" && r.ambulance?.status === "REQUESTED" && dispatching !== r.id && (
                        <button className="primary-btn" onClick={() => setDispatching(r.id)}>
                          Send ambulance
                        </button>
                      )}
                      {user?.role === "FACILITY_STAFF" && r.ambulance?.status === "DISPATCHED" && (
                        <button className="secondary-btn" disabled={busyId === r.id} onClick={() => act(r, "ambulance/picked-up")}>
                          Patient picked up
                        </button>
                      )}
                      <button className="link-btn" onClick={() => setRecordFor(recordFor === r.id ? null : r.id)}>
                        {recordFor === r.id ? "Hide record" : "📋 Patient record"}
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
                      <Field label="Pickup">
                        <input value={r.ambulance?.pickup_note || ""} readOnly />
                      </Field>
                      <Field label="Arrives in (minutes)">
                        <input id="dispatch-eta" inputMode="numeric" value={trip.eta}
                          onChange={(e) => setTrip({ ...trip, eta: e.target.value.replace(/\D/g, "").slice(0, 3) })} />
                      </Field>
                      <Field label="Vehicle number">
                        <input id="dispatch-vehicle" value={trip.vehicle} placeholder="WB-xx-xxxx"
                          onChange={(e) => setTrip({ ...trip, vehicle: e.target.value.toUpperCase() })} />
                      </Field>
                      <Field label="Driver's mobile">
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
                          Confirm: ambulance sent
                        </button>
                        <button
                          className="secondary-btn"
                          disabled={busyId === r.id}
                          onClick={async () => {
                            if (await act(r, "ambulance/cancel", { reason: "Hospital ambulance not available" })) setDispatching(null);
                          }}
                        >
                          Can't send (tell ASHA to call 108)
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
