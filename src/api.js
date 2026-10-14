// Talks to the SahyogCare backend (see backend/README.md and docs/API_SPEC.md).
//
// In development, Vite forwards /api to the backend on http://127.0.0.1:8000
// (vite.config.js). For a deployed frontend, set VITE_API_URL at build time,
// e.g. VITE_API_URL=https://sahyogcare-api.onrender.com/api/v1

import { readLS, removeLS, writeLS } from "./i18n.jsx";

const BASE = (import.meta.env.VITE_API_URL || "/api/v1").replace(/\/$/, "");
const AUTH_KEY = "sahyogcare_auth";

export class ApiError extends Error {
  constructor(status, code, message, details = {}) {
    super(message);
    this.status = status;
    this.code = code;
    this.details = details;
  }
}

function loadAuth() {
  try {
    return JSON.parse(readLS(AUTH_KEY) || "null");
  } catch {
    return null;
  }
}

let auth = loadAuth();

function saveAuth(next) {
  auth = next;
  if (next) writeLS(AUTH_KEY, JSON.stringify(next));
  else removeLS(AUTH_KEY);
}

export function currentUser() {
  return auth?.user || null;
}

export function logout() {
  saveAuth(null);
}

async function send(method, path, body, { token, headers } = {}) {
  let res;
  try {
    res = await fetch(`${BASE}${path}`, {
      method,
      headers: {
        ...(body !== undefined ? { "Content-Type": "application/json" } : {}),
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
        ...headers,
      },
      body: body !== undefined ? JSON.stringify(body) : undefined,
    });
  } catch {
    throw new ApiError(0, "NETWORK", "Cannot reach the SahyogCare server. Check your connection.");
  }
  const data = await res.json().catch(() => null);
  if (!res.ok) {
    const e = data?.error || {};
    throw new ApiError(res.status, e.code || "HTTP_ERROR", e.message || `Request failed (${res.status})`, e.details || {});
  }
  return data;
}

let refreshing = null;

async function refreshTokens() {
  if (!auth?.refresh) throw new ApiError(401, "AUTH_REQUIRED", "Please log in again.");
  refreshing ??= send("POST", "/auth/refresh", { refresh_token: auth.refresh })
    .then((t) => saveAuth({ access: t.access_token, refresh: t.refresh_token, user: t.user }))
    .finally(() => {
      refreshing = null;
    });
  return refreshing;
}

// Logged-in request; renews the 15-minute access token once if it has expired.
export async function request(method, path, body, options = {}) {
  try {
    return await send(method, path, body, { ...options, token: auth?.access });
  } catch (e) {
    if (e.status !== 401 || !auth?.refresh) throw e;
    try {
      await refreshTokens();
    } catch {
      saveAuth(null);
      window.dispatchEvent(new Event("sahyog:logout"));
      throw new ApiError(401, "AUTH_REQUIRED", "Your session has ended. Please log in again.");
    }
    return send(method, path, body, { ...options, token: auth?.access });
  }
}

export const api = {
  get: (path) => request("GET", path),
  post: (path, body, options) => request("POST", path, body ?? {}, options),
  patch: (path, body) => request("PATCH", path, body ?? {}),
};

// ---------- login ----------

// `who` is an email address or a 10-digit mobile number (phone login needs the SMS service).
const identity = (who) => (/^[6-9]\d{9}$/.test(who.trim()) ? { phone: who.trim() } : { email: who });

export const requestCode = (who) => send("POST", "/auth/otp/request", identity(who));
export const loginMethods = () => send("GET", "/auth/methods");

export async function verifyCode(who, code) {
  const t = await send("POST", "/auth/otp/verify", { ...identity(who), code });
  saveAuth({ access: t.access_token, refresh: t.refresh_token, user: t.user });
  return t.user;
}

// Fetch the logged-in user again (e.g. to see whether the coordinator approved them).
export async function refreshMe() {
  const user = await request("GET", "/me");
  if (auth) saveAuth({ ...auth, user });
  return user;
}

// ---------- public (no login) ----------

export const getDistricts = () => send("GET", "/public/districts");

export const lookupReferral = (code, phoneLast4) =>
  send("POST", "/public/referral-status", { code, phone_last4: phoneLast4 });

// ---------- the patient's own sign-in (Health ID + last 4 phone digits) ----------

const PATIENT_KEY = "sahyog_patient_token";
export const patientToken = () => readLS(PATIENT_KEY);
export const patientLogout = () => removeLS(PATIENT_KEY);

export async function patientLogin(code, phoneLast4) {
  const t = await send("POST", "/public/patient-login", { code, phone_last4: phoneLast4 });
  writeLS(PATIENT_KEY, t.token);
  return t;
}

export const patientApi = {
  get: (path) => send("GET", path, undefined, { token: patientToken() }),
  post: (path, body) => send("POST", path, body ?? {}, { token: patientToken() }),
};

// ---------- photos ----------

// Shrink a camera photo on the phone (max 900 px, JPEG) before sending it.
export function shrinkPhoto(file, maxSide = 900, quality = 0.72) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onerror = () => reject(new Error("Could not read the photo."));
    reader.onload = () => {
      const img = new Image();
      img.onerror = () => reject(new Error("This file is not a photo."));
      img.onload = () => {
        const scale = Math.min(1, maxSide / Math.max(img.width, img.height));
        const canvas = document.createElement("canvas");
        canvas.width = Math.round(img.width * scale);
        canvas.height = Math.round(img.height * scale);
        canvas.getContext("2d").drawImage(img, 0, 0, canvas.width, canvas.height);
        resolve(canvas.toDataURL("image/jpeg", quality));
      };
      img.src = reader.result;
    };
    reader.readAsDataURL(file);
  });
}

export async function uploadPhoto(file, ownerType, ownerId) {
  const dataUrl = await shrinkPhoto(file);
  return api.post("/photos", { data_url: dataUrl, owner_type: ownerType, owner_id: ownerId || null });
}

// Photos need the login token, so they are fetched and shown as a local object URL.
export async function photoUrl(photoId, asPatient = false) {
  const token = asPatient ? patientToken() : auth?.access;
  const get = (tok) => fetch(`${BASE}/photos/${photoId}`, { headers: tok ? { Authorization: `Bearer ${tok}` } : {} });
  let res = await get(token);
  if (res.status === 401 && !asPatient && auth?.refresh) {
    await refreshTokens();
    res = await get(auth?.access);
  }
  if (!res.ok) throw new ApiError(res.status, "PHOTO", "Photo not available.");
  return URL.createObjectURL(await res.blob());
}

// ---------- helpers ----------

export const newKey = () =>
  globalThis.crypto?.randomUUID?.() || `${Date.now()}-${Math.random().toString(36).slice(2)}`;

export const qs = (params) => {
  const p = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) if (v !== undefined && v !== null && v !== "") p.set(k, v);
  const s = p.toString();
  return s ? `?${s}` : "";
};
