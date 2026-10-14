// The way in: three doors (Patient / Health worker / District office), one question per
// screen, then the personal code. Also: asking to join, the new-code card, and the
// district office's People list.
import React, { useCallback, useEffect, useRef, useState } from "react";
import {
  api,
  getDistricts,
  loginMethods,
  loginWithPersonalCode,
  markCodeSeen,
  patientChoose,
  patientRequestCode,
  patientSignup,
  patientVerify,
  qs,
  refreshMe,
  requestCode,
  uploadPhoto,
  verifyCode,
} from "./api.js";
import { PhotoPicker, PhotoView } from "./health.jsx";
import { LANGUAGES, errorText, readLS, useLanguage, writeLS } from "./i18n.jsx";
import { Empty, Skeleton } from "./ui.jsx";

const isEmail = (x) => /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(x.trim());
const isMobile = (x) => /^[6-9]\d{9}$/.test(x.trim());
const DOOR_KEY = "sahyog_door"; // which door the person came in by: worker | office
export const SCREEN_FOR = { WORKER: "asha", FACILITY_STAFF: "medical", DOCTOR: "medical", COORDINATOR: "coordinator" };
// Every language the app speaks, each in its own script, right on the start screen.
const QUICK_LANGS = [...LANGUAGES.filter(([k]) => k !== "en"), LANGUAGES.find(([k]) => k === "en")].map(([k, , native]) => [k, native]);

// Personal code as typed: capitals, a dash after 4 characters.
const formatCode = (v) => {
  const raw = v.toUpperCase().replace(/[^A-Z0-9]/g, "").slice(0, 8);
  return raw.length > 4 ? `${raw.slice(0, 4)}-${raw.slice(4)}` : raw;
};

function Brand() {
  return (
    <div className="entry-brand">
      <div className="brand-mark">स</div>
      <div>
        <strong>SahyogCare</strong>
      </div>
    </div>
  );
}

// ---------- Start screen ----------

export function EntryScreen({ onSignIn, onTour }) {
  const { t, language, setLanguage } = useLanguage();
  const [step, setStep] = useState("door"); // door | id | otp | code | pick (patients sharing a phone)
  const [door, setDoor] = useState(readLS(DOOR_KEY) || "worker");
  const [who, setWho] = useState("");
  const [otp, setOtp] = useState("");
  const [code, setCode] = useState("");
  const [codeToken, setCodeToken] = useState("");
  const [devOtp, setDevOtp] = useState("");
  const [phoneOk, setPhoneOk] = useState(false);
  const [channel, setChannel] = useState(""); // patients: sms | email | asha
  const [people, setPeople] = useState([]); // patients: a family on one phone
  const [chooseToken, setChooseToken] = useState("");
  const [signupToken, setSignupToken] = useState("");
  const [me, setMe] = useState({ name: "", age: "", sex: "", address: "", district: "", consent: false });
  const [areas, setAreas] = useState(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  useEffect(() => {
    loginMethods()
      .then((m) => setPhoneOk(!!m.phone))
      .catch(() => {});
  }, []);
  const go = (next) => {
    setError("");
    setStep(next);
  };
  const patientDoor = door === "patient";
  const choose = (d) => {
    setDoor(d);
    writeLS(DOOR_KEY, d);
    go("id");
  };
  // Patients sign in with the mobile their ASHA registered (or an email on their record).
  // Patients sign in with the mobile number their ASHA registered; staff with email (or mobile, when SMS is on).
  const validId = patientDoor ? isMobile(who) : isEmail(who) || (phoneOk && isMobile(who));
  const send = async () => {
    if (!validId || busy) return;
    setBusy(true);
    setError("");
    try {
      const r = patientDoor ? await patientRequestCode(who.trim()) : await requestCode(who.trim());
      setChannel(r.channel || "");
      setDevOtp(r.dev_code || "");
      setOtp("");
      go("otp");
    } catch (e) {
      setError(errorText(t, e));
    } finally {
      setBusy(false);
    }
  };
  const finish = (r) => onSignIn({ screen: SCREEN_FOR[r.user.role], user: r.user, newCode: r.newCode });
  const verify = async () => {
    if (otp.length !== 6 || busy) return;
    setBusy(true);
    setError("");
    try {
      if (patientDoor) {
        const p = await patientVerify(who.trim(), otp);
        setSignupToken(p.signupToken || "");
        if (p.patient) return onSignIn({ screen: "patient", user: null });
        if (p.newAccount) return startSignup();
        setPeople(p.people);
        setChooseToken(p.chooseToken);
        return go("pick");
      }
      const r = await verifyCode(who.trim(), otp);
      if (r.codeRequired) {
        setCodeToken(r.codeToken);
        setCode("");
        go("code");
      } else finish(r);
    } catch (e) {
      setError(errorText(t, e));
    } finally {
      setBusy(false);
    }
  };
  const enterCode = async () => {
    if (code.replace("-", "").length !== 8 || busy) return;
    setBusy(true);
    setError("");
    try {
      finish(await loginWithPersonalCode(codeToken, code));
    } catch (e) {
      if (e.code === "AUTH_REQUIRED" || e.code === "TOKEN_EXPIRED") {
        setError(t("codeStepExpired"));
        go("id");
      } else setError(errorText(t, e));
    } finally {
      setBusy(false);
    }
  };
  // Nobody on this number yet (or someone new on a family phone): make an account.
  const startSignup = () => {
    setMe({ name: "", age: "", sex: "", address: "", district: "", consent: false });
    if (areas === null)
      getDistricts()
        .then(setAreas)
        .catch(() => setAreas([]));
    go("signup");
  };
  const signupValid = me.name.trim().length >= 2 && me.age !== "" && Number(me.age) <= 120 && me.district && me.consent;
  const createAccount = async () => {
    if (!signupValid || busy) return;
    setBusy(true);
    setError("");
    try {
      await patientSignup(signupToken, {
        name: me.name.trim(),
        age: Number(me.age),
        sex: me.sex || null,
        address: me.address.trim() || null,
        district: me.district,
        language: ["bn", "hi", "en"].includes(language) ? language : "bn",
        consent: true,
      });
      onSignIn({ screen: "patient", user: null });
    } catch (e) {
      setError(errorText(t, e));
      if (e.code === "AUTH_REQUIRED") go("id");
    } finally {
      setBusy(false);
    }
  };
  const pick = async (id) => {
    if (busy) return;
    setBusy(true);
    setError("");
    try {
      await patientChoose(chooseToken, id);
      onSignIn({ screen: "patient", user: null });
    } catch (e) {
      setError(errorText(t, e));
      go("id");
    } finally {
      setBusy(false);
    }
  };
  const doorName = door === "office" ? t("doorOffice") : patientDoor ? t("doorPatient") : t("doorWorker");

  return (
    <div className="entry">
      <div className="entry-card">
        <div className="entry-top">
          <Brand />
          <button className="help-btn" onClick={onTour} aria-label={t("appTour")} title={t("appTour")}>
            ?
          </button>
        </div>
        <div className="lang-quick" role="group" aria-label={t("language")} data-tour="language">
          {QUICK_LANGS.map(([k, label]) => (
            <button key={k} className={language === k ? "lang-chip on" : "lang-chip"} onClick={() => setLanguage(k)}>
              {label}
            </button>
          ))}
        </div>

        {step === "door" && (
          <div className="reveal" data-tour="doors">
            <h1 className="entry-title">{t("whoAreYou")}</h1>
            <button className="door door-patient" onClick={() => choose("patient")}>
              <span className="door-icon">♡</span>
              <span>
                <b>{t("doorPatient")}</b>
                <small>{t("doorPatientSub")}</small>
              </span>
            </button>
            <button className="door" onClick={() => choose("worker")}>
              <span className="door-icon">◉</span>
              <span>
                <b>{t("doorWorker")}</b>
                <small>{t("doorWorkerSub")}</small>
              </span>
            </button>
            <button className="door" onClick={() => choose("office")}>
              <span className="door-icon">◆</span>
              <span>
                <b>{t("doorOffice")}</b>
                <small>{t("doorOfficeSub")}</small>
              </span>
            </button>
          </div>
        )}

        {step === "id" && (
          <div className="reveal">
            <p className="entry-step">{doorName}</p>
            <h1 className="entry-title">{patientDoor ? t("patientMobileTitle") : phoneOk ? t("yourEmailOrMobile") : t("yourEmail")}</h1>
            {patientDoor && <p className="muted">{t("patientMobileHelp")}</p>}
            <input
              className="big-input"
              data-tour="email"
              value={who}
              onChange={(e) => setWho(patientDoor ? e.target.value.replace(/\D/g, "").slice(0, 10) : e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && send()}
              placeholder={patientDoor ? "98XXXXXXXX" : phoneOk ? "you@gmail.com / 98XXXXXXXX" : "you@gmail.com"}
              type={patientDoor ? "tel" : phoneOk ? "text" : "email"}
              inputMode={patientDoor ? "numeric" : phoneOk ? "text" : "email"}
              autoComplete={patientDoor ? "tel" : phoneOk ? "username" : "email"}
              maxLength={patientDoor ? 10 : undefined}
              autoFocus
            />
            <button className="primary-btn big-btn" onClick={send} disabled={!validId || busy}>
              {busy ? t("loading") : t("sendCode")}
            </button>
            <button className="link-btn" onClick={() => go("door")}>
              ← {t("back")}
            </button>
          </div>
        )}

        {step === "otp" && (
          <div className="reveal">
            <p className="entry-step">{doorName}</p>
            <h1 className="entry-title">{t("enterOtp")}</h1>
            {channel === "asha" ? (
              <div className="asha-code-note">
                <b>{t("askAshaForCode")}</b>
                <span>{t("askAshaForCodeHow")}</span>
              </div>
            ) : (
              <p className="muted">
                {t("otpSentTo")} <b>{who.trim()}</b>
              </p>
            )}
            <input
              className="big-input otp-big"
              value={otp}
              onChange={(e) => setOtp(e.target.value.replace(/\D/g, "").slice(0, 6))}
              onKeyDown={(e) => e.key === "Enter" && verify()}
              placeholder="● ● ● ● ● ●"
              inputMode="numeric"
              autoComplete="one-time-code"
              autoFocus
            />
            <button className="primary-btn big-btn" onClick={verify} disabled={otp.length !== 6 || busy}>
              {busy ? t("loading") : t("next")}
            </button>
            {devOtp && (
              <div className="demo-code">
                {t("testCode")}: <b>{devOtp}</b>
              </div>
            )}
            <button className="link-btn" onClick={() => go("id")}>
              ← {patientDoor ? t("changeMobile") : phoneOk ? t("changeEmailOrMobile") : t("changeEmail")}
            </button>
          </div>
        )}

        {step === "pick" && (
          <div className="reveal">
            <p className="entry-step">{doorName}</p>
            <h1 className="entry-title">{t("whoIsSigningIn")}</h1>
            <p className="muted">{t("whoIsSigningInHelp")}</p>
            {people.map((p) => (
              <button key={p.id} className="door" onClick={() => pick(p.id)} disabled={busy}>
                <span className="door-icon">♡</span>
                <span>
                  <b>{p.name}</b>
                  <small>
                    {p.age} {t("yearsShort")}
                    {p.sex ? ` · ${t(`sex_${p.sex}`)}` : ""}
                  </small>
                </span>
              </button>
            ))}
            {signupToken && (
              <button className="link-btn" onClick={startSignup}>
                ＋ {t("someoneNewOnPhone")}
              </button>
            )}
          </div>
        )}

        {step === "signup" && (
          <div className="reveal join-form">
            <p className="entry-step">{doorName}</p>
            <h1 className="entry-title">{t("createAccountTitle")}</h1>
            <p className="muted">{t("createAccountHelp")}</p>
            <label>{t("yourName")}</label>
            <input id="signup-name" className="big-input" value={me.name} onChange={(e) => setMe({ ...me, name: e.target.value })} placeholder={t("fullName")} />
            <label>{t("age")}</label>
            <input className="big-input" inputMode="numeric" value={me.age} onChange={(e) => setMe({ ...me, age: e.target.value.replace(/\D/g, "").slice(0, 3) })} />
            <label>{t("sex")}</label>
            <div className="choice-row">
              {["F", "M", "O"].map((x) => (
                <button key={x} className={me.sex === x ? "choice on" : "choice"} onClick={() => setMe({ ...me, sex: x })}>
                  {t(`sex_${x}`)}
                </button>
              ))}
            </div>
            <label>{t("whereYouLive")}</label>
            {areas === null && <p className="muted">{t("loading")}</p>}
            <div className="choice-row">
              {(areas || []).map((d) => (
                <button key={d} className={me.district === d ? "choice on" : "choice"} onClick={() => setMe({ ...me, district: d })}>
                  {d}
                </button>
              ))}
            </div>
            <label>{t("villageAddress")}</label>
            <input className="big-input" value={me.address} onChange={(e) => setMe({ ...me, address: e.target.value })} placeholder={t("addressPlaceholder")} />
            <label className="check-line">
              <input type="checkbox" checked={me.consent} onChange={(e) => setMe({ ...me, consent: e.target.checked })} />
              <span>{t("consentSelf")}</span>
            </label>
            <button className="primary-btn big-btn" onClick={createAccount} disabled={!signupValid || busy}>
              {busy ? t("loading") : t("createAccount")}
            </button>
          </div>
        )}

        {step === "code" && (
          <div className="reveal">
            <p className="entry-step">{doorName}</p>
            <h1 className="entry-title">{t("enterPersonalCode")}</h1>
            <p className="muted">{t("personalCodeHelp")}</p>
            <input
              className="big-input code-big"
              value={code}
              onChange={(e) => setCode(formatCode(e.target.value))}
              onKeyDown={(e) => e.key === "Enter" && enterCode()}
              placeholder="XXXX-XXXX"
              autoCapitalize="characters"
              autoComplete="off"
              spellCheck={false}
              autoFocus
            />
            <button className="primary-btn big-btn" onClick={enterCode} disabled={code.replace("-", "").length !== 8 || busy}>
              {busy ? t("loading") : t("enter")}
            </button>
            <p className="muted small-note">{t("forgotCode")}</p>
          </div>
        )}

        {error && (
          <div className="entry-error" role="alert">
            {error}
          </div>
        )}
      </div>
    </div>
  );
}

// ---------- Asking to join (first time only) ----------

const ROLES_TO_ASK = [
  ["WORKER", "roleAsha"],
  ["FACILITY_STAFF", "roleStaff"],
  ["DOCTOR", "roleDoctor"],
];
const NEEDS_HOSPITAL = new Set(["FACILITY_STAFF", "DOCTOR"]);

export function JoinScreen({ user, onApproved, onSignOut }) {
  const { t } = useLanguage();
  const office = readLS(DOOR_KEY) === "office";
  const [mine, setMine] = useState(undefined); // undefined = loading, null = never asked
  const [districts, setDistricts] = useState(null);
  const [facilities, setFacilities] = useState([]);
  const [form, setForm] = useState({ role: "WORKER", name: "", district: "", facility_id: "", note: "", passphrase: "" });
  const [photoId, setPhotoId] = useState(user.photo_id || null);
  const [photoBusy, setPhotoBusy] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const set = (k) => (e) => setForm((f) => ({ ...f, [k]: e.target.value }));

  const approvedRef = useRef(onApproved);
  approvedRef.current = onApproved;
  const check = useCallback(async () => {
    try {
      const me = await refreshMe();
      if (me.approved) return approvedRef.current(me);
      if (!office) setMine(await api.get("/access-requests/mine"));
      else setMine(null);
    } catch (e) {
      setError(errorText(t, e));
    }
  }, [office]);
  useEffect(() => {
    check();
    // While waiting, look again every half minute (the office may approve at any time).
    const id = setInterval(() => document.visibilityState === "visible" && check(), 30000);
    return () => clearInterval(id);
  }, [check]);
  useEffect(() => {
    getDistricts()
      .then(setDistricts)
      .catch(() => setDistricts([]));
  }, []);
  useEffect(() => {
    if (!form.district || !NEEDS_HOSPITAL.has(form.role)) return;
    api.get(`/facilities${qs({ district: form.district })}`).then(setFacilities).catch(() => {});
  }, [form.district, form.role]);

  const addPhoto = async (file) => {
    setPhotoBusy(true);
    setError("");
    try {
      setPhotoId((await uploadPhoto(file, "user")).id);
    } catch (e) {
      setError(errorText(t, e));
    } finally {
      setPhotoBusy(false);
    }
  };
  const ask = async () => {
    setBusy(true);
    setError("");
    try {
      const body = { role: form.role, name: form.name.trim(), note: form.note.trim() || null, district: form.district };
      if (NEEDS_HOSPITAL.has(form.role)) body.facility_id = form.facility_id;
      const r = await api.post("/access-requests", body);
      setMine(r);
      if (r.status === "APPROVED") await check();
    } catch (e) {
      setError(errorText(t, e));
    } finally {
      setBusy(false);
    }
  };
  const enterOffice = async () => {
    setBusy(true);
    setError("");
    try {
      await api.post("/office/join", { district: form.district, name: form.name.trim(), passphrase: form.passphrase });
      await check();
    } catch (e) {
      setError(errorText(t, e));
    } finally {
      setBusy(false);
    }
  };

  const areas = (
    <>
      <label>{t("whereYouWork")}</label>
      {districts === null && <p className="muted">{t("loading")}</p>}
      {districts && districts.length === 0 && <p className="entry-error">{t("areasFailed")}</p>}
      <div className="choice-row">
        {(districts || []).map((d) => (
          <button key={d} className={form.district === d ? "choice on" : "choice"} onClick={() => setForm((f) => ({ ...f, district: d, facility_id: "" }))}>
            {d}
          </button>
        ))}
      </div>
    </>
  );
  const waiting = mine?.status === "PENDING";
  const canAsk = form.name.trim() && form.district && (!NEEDS_HOSPITAL.has(form.role) || form.facility_id);

  return (
    <div className="entry">
      <div className="entry-card">
        <div className="entry-top">
          <Brand />
        </div>
        {mine === undefined ? (
          <Skeleton />
        ) : office ? (
          <div className="reveal join-form">
            <p className="entry-step">{t("doorOffice")}</p>
            <h1 className="entry-title">{t("officeEnterTitle")}</h1>
            <label>{t("yourName")}</label>
            <input className="big-input" value={form.name} onChange={set("name")} placeholder={t("fullName")} />
            {areas}
            <label>{t("officePassphrase")}</label>
            <input
              id="office-passphrase"
              className="big-input"
              type="password"
              autoComplete="off"
              value={form.passphrase}
              onChange={set("passphrase")}
              placeholder={form.district ? `${form.district} · ${t("officePassphrase")}` : t("chooseAreaFirst")}
            />
            <button className="primary-btn big-btn" onClick={enterOffice} disabled={!form.district || !form.name.trim() || !form.passphrase || busy}>
              {busy ? t("loading") : t("enter")}
            </button>
            <p className="muted small-note">{t("officeOnlyNote")}</p>
          </div>
        ) : waiting ? (
          <div className="reveal waiting">
            <div className="big-tick">✓</div>
            <h1 className="entry-title">{t("requestSent")}</h1>
            <p className="muted">{t("waitingForOffice")}</p>
            <div className="waiting-card">
              <b>{mine.name}</b>
              <span>
                {t(ROLES_TO_ASK.find(([r]) => r === mine.requested_role)?.[1] || "roleAsha")}
                {mine.facility_name ? ` · ${mine.facility_name}` : ""}
              </span>
            </div>
            <button className="secondary-btn big-btn" onClick={check}>
              {t("checkAgain")}
            </button>
          </div>
        ) : (
          <div className="reveal join-form">
            <p className="entry-step">{t("doorWorker")}</p>
            <h1 className="entry-title">{t("askToJoinTitle")}</h1>
            <p className="muted">{t("askToJoinHelp")}</p>
            {mine?.status === "REJECTED" && (
              <div className="entry-error">
                {t("notApproved")}
                {mine.decision_note ? `: ${mine.decision_note}` : ""}
              </div>
            )}
            <label>{t("yourName")}</label>
            <input id="join-name" className="big-input" value={form.name} onChange={set("name")} placeholder={t("fullName")} />
            <label>{t("youAre")}</label>
            <div className="choice-row">
              {ROLES_TO_ASK.map(([r, key]) => (
                <button key={r} className={form.role === r ? "choice on" : "choice"} onClick={() => setForm((f) => ({ ...f, role: r }))}>
                  {t(key)}
                </button>
              ))}
            </div>
            {areas}
            {NEEDS_HOSPITAL.has(form.role) && form.district && (
              <>
                <label>{t("yourHospital")}</label>
                <select className="big-input" value={form.facility_id} onChange={set("facility_id")}>
                  <option value="">{t("chooseHospital")}</option>
                  {facilities.map((f) => (
                    <option key={f.id} value={f.id}>
                      {f.name}
                    </option>
                  ))}
                </select>
              </>
            )}
            <label>{t("yourPhoto")}</label>
            <div className="photo-line">
              {photoId && <PhotoView id={photoId} alt="" className="photo-mini" />}
              <PhotoPicker label={photoId ? t("retake") : t("takeSelfie")} onFile={addPhoto} busy={photoBusy} />
            </div>
            <label>{t("idNoteLabel")}</label>
            <input className="big-input" value={form.note} onChange={set("note")} placeholder={t("idNotePlaceholder")} />
            <button className="primary-btn big-btn" onClick={ask} disabled={!canAsk || busy}>
              {busy ? t("loading") : t("askToJoin")}
            </button>
          </div>
        )}
        {error && (
          <div className="entry-error" role="alert">
            {error}
          </div>
        )}
        <button className="link-btn" onClick={onSignOut}>
          ← {t("backToStart")}
        </button>
      </div>
    </div>
  );
}

// ---------- The new personal code, shown once ----------

export function NewCodeCard({ code, onDone }) {
  const { t } = useLanguage();
  const [busy, setBusy] = useState(false);
  const done = async () => {
    setBusy(true);
    try {
      await markCodeSeen();
    } catch {
      /* shown again next time; harmless */
    }
    onDone();
  };
  return (
    <div className="consult-modal" role="dialog" aria-modal="true" aria-labelledby="new-code-title">
      <div className="consult-modal-card new-code-card">
        <p className="eyebrow">{t("approvedWelcome")}</p>
        <h3 id="new-code-title">{t("yourPersonalCode")}</h3>
        <div className="code-display" aria-label={code.split("").join(" ")}>
          {code}
        </div>
        <ul className="code-rules">
          <li>{t("codeRuleWrite")}</li>
          <li>{t("codeRuleEveryLogin")}</li>
          <li>{t("codeRuleSecret")}</li>
        </ul>
        <button className="primary-btn big-btn" onClick={done} disabled={busy}>
          ✓ {t("codeWritten")}
        </button>
      </div>
    </div>
  );
}

// ---------- District office: everyone in the area ----------

const ROLE_KEY = { WORKER: "roleAsha", FACILITY_STAFF: "roleStaff", DOCTOR: "roleDoctor", COORDINATOR: "doorOffice" };

export function PeoplePanel({ me, facilities, toast }) {
  const { t } = useLanguage();
  const [people, setPeople] = useState(null);
  const [busyId, setBusyId] = useState(null);
  const [q, setQ] = useState("");
  const [all, setAll] = useState(false); // a long list stays short until asked
  const load = useCallback(() => {
    api
      .get("/users")
      .then(setPeople)
      .catch((e) => toast(errorText(t, e)));
  }, [toast]);
  useEffect(load, [load]);
  const hospital = (id) => facilities?.find((f) => f.id === id)?.name;
  const act = async (p, what) => {
    const ask = what === "reset" ? t("confirmReset") : p.is_active ? t("confirmSwitchOff") : t("confirmSwitchOn");
    if (!window.confirm(`${p.name}: ${ask}`)) return;
    setBusyId(p.id);
    try {
      if (what === "reset") await api.post(`/users/${p.id}/reset-code`);
      else await api.patch(`/users/${p.id}`, { is_active: !p.is_active });
      toast(what === "reset" ? t("codeResetDone") : p.is_active ? t("switchedOff") : t("switchedOn"));
      load();
    } catch (e) {
      toast(errorText(t, e));
    } finally {
      setBusyId(null);
    }
  };
  const shown = (people || [])
    .filter((p) => p.approved)
    .filter((p) => !q.trim() || `${p.name} ${p.email || ""} ${p.phone || ""}`.toLowerCase().includes(q.trim().toLowerCase()));
  return (
    <section className="panel" data-tour="people">
      <div className="panel-head">
        <div>
          <p className="eyebrow">{t("peopleEyebrow")}</p>
          <h3>{t("peopleTitle")}</h3>
          <p className="muted">{t("peopleHelp")}</p>
        </div>
      </div>
      <div className="search-row">
        <input value={q} onChange={(e) => setQ(e.target.value)} placeholder={t("searchPeople")} aria-label={t("searchPeople")} />
      </div>
      {people === null ? (
        <Skeleton />
      ) : shown.length === 0 ? (
        <Empty title={t("noPeople")} text="" />
      ) : (
        <div className="people-list">
          {(all || q.trim() ? shown : shown.slice(0, 5)).map((p) => (
            <div className={p.is_active ? "person" : "person off"} key={p.id}>
              <PhotoView id={p.photo_id} alt="" className="photo-mini" />
              <div className="person-main">
                <b>{p.name}</b>
                <small>
                  {t(ROLE_KEY[p.role])}
                  {hospital(p.facility_id) ? ` · ${hospital(p.facility_id)}` : ""} · {p.email || p.phone}
                </small>
                <small>
                  {p.has_code ? `🔒 ${t("hasCode")}` : `○ ${t("noCodeYet")}`}
                  {!p.is_active ? ` · ${t("switchedOffLabel")}` : ""}
                </small>
              </div>
              <div className="person-actions">
                <button className="link-btn" disabled={busyId === p.id} onClick={() => act(p, "reset")}>
                  {t("resetCode")}
                </button>
                {p.id !== me?.id && (
                  <button className={p.is_active ? "link-btn danger-link" : "link-btn"} disabled={busyId === p.id} onClick={() => act(p, "active")}>
                    {p.is_active ? t("switchOff") : t("switchOn")}
                  </button>
                )}
              </div>
            </div>
          ))}
          {!all && !q.trim() && shown.length > 5 && (
            <button className="secondary-btn" onClick={() => setAll(true)}>
              {t("showAll")} ({shown.length})
            </button>
          )}
        </div>
      )}
    </section>
  );
}
