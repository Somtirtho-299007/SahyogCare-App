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
};

// ---------- login ----------

export const requestCode = (email) => send("POST", "/auth/otp/request", { email });

export async function verifyCode(email, code) {
  const t = await send("POST", "/auth/otp/verify", { email, code });
  saveAuth({ access: t.access_token, refresh: t.refresh_token, user: t.user });
  return t.user;
}

// ---------- public (no login) ----------

export const lookupReferral = (code, phoneLast4) =>
  send("POST", "/public/referral-status", { code, phone_last4: phoneLast4 });

// ---------- helpers ----------

export const newKey = () =>
  globalThis.crypto?.randomUUID?.() || `${Date.now()}-${Math.random().toString(36).slice(2)}`;

export const qs = (params) => {
  const p = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) if (v !== undefined && v !== null && v !== "") p.set(k, v);
  const s = p.toString();
  return s ? `?${s}` : "";
};
