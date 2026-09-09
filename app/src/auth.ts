// Supabase Auth over plain REST — no supabase-js.
//
// The SDK would bring a realtime client, a storage client and a postgrest
// client for the four endpoints this app actually calls, and it wants an
// AsyncStorage adapter to persist a session that belongs in the keychain
// instead. Tokens go to expo-secure-store; the publishable key is designed to
// ship in a binary, and sessions are what we protect.
//
// Forked from VoyageOS, pointed at a DIFFERENT project (§0.3 — separate auth,
// no shared users table).

import * as SecureStore from 'expo-secure-store';

import { clearCache } from './cache';
import * as CFG from './config';

const SB_URL = CFG.SUPABASE_URL;
const SB_KEY = CFG.SUPABASE_ANON_KEY;

let access = '';
let refreshTok = '';
let expiresAt = 0;           // epoch seconds
let email = '';
let userId = '';

const K = { a: 'vo_access', r: 'vo_refresh', e: 'vo_exp', m: 'vo_email', u: 'vo_uid' };

function headers() {
  return { apikey: SB_KEY, 'Content-Type': 'application/json' };
}

/** The user id out of the JWT, without a library.
 *
 *  NOT verification — the server does that, against Supabase, on every request.
 *  This only reads a claim the app already holds so a refresh response that
 *  omits `user` does not clear an id we knew a moment ago. */
function userIdFromToken(token: string): string {
  try {
    const payload = token.split('.')[1];
    if (!payload) return '';
    const pad = payload.length % 4 ? '='.repeat(4 - (payload.length % 4)) : '';
    const normalised = payload.replace(/-/g, '+').replace(/_/g, '/') + pad;
    return JSON.parse(globalThis.atob(normalised))?.sub ?? '';
  } catch {
    return '';
  }
}

async function persist(json: any): Promise<void> {
  access = json.access_token ?? '';
  refreshTok = json.refresh_token ?? '';
  expiresAt = Math.floor(Date.now() / 1000) + (json.expires_in ?? 3600);
  await SecureStore.setItemAsync(K.a, access);
  await SecureStore.setItemAsync(K.r, refreshTok);
  await SecureStore.setItemAsync(K.e, String(expiresAt));
  if (json.user?.email) {
    email = json.user.email;
    await SecureStore.setItemAsync(K.m, email);
  }
  const id = json.user?.id ?? userIdFromToken(access);
  if (id) { userId = id; await SecureStore.setItemAsync(K.u, id); }
}

export function hasAuthKeys(): boolean { return !!(SB_URL && SB_KEY); }
export function getEmail(): string { return email; }
export function getUserId(): string { return userId; }

/** The access token, or '' when it is within 30 seconds of expiry.
 *
 *  The margin matters: a token that is valid when checked and expired when it
 *  arrives produces a 401 the user sees as a random sign-out. */
export function getToken(): string {
  return expiresAt > Date.now() / 1000 + 30 ? access : '';
}

export async function loadSession(): Promise<'authed' | 'anon' | 'nokeys'> {
  if (!hasAuthKeys()) return 'nokeys';
  access = (await SecureStore.getItemAsync(K.a)) ?? '';
  refreshTok = (await SecureStore.getItemAsync(K.r)) ?? '';
  expiresAt = Number((await SecureStore.getItemAsync(K.e)) ?? 0);
  email = (await SecureStore.getItemAsync(K.m)) ?? '';
  userId = (await SecureStore.getItemAsync(K.u)) ?? '';
  if (!refreshTok) return 'anon';
  if (getToken()) return 'authed';
  return (await refreshSession()) ? 'authed' : 'anon';
}

/** Is there a session to refresh at all? Distinct from getToken(), which
 *  answers "is the ACCESS token usable right now" — an expired access token
 *  with a live refresh token is an ordinary state, not a signed-out one. */
export function hasSession(): boolean {
  return !!refreshTok;
}

/** The one in-flight refresh, shared by every caller.
 *
 *  SUPABASE ROTATES REFRESH TOKENS: each successful refresh invalidates the
 *  one that was used. Four screens mounting at once and each calling this
 *  would fire four refreshes with the same token — the first wins and the
 *  other three get an invalidated token back, which signs the user out on app
 *  open. Sharing the promise makes concurrent callers await one request. */
let inFlight: Promise<boolean> | null = null;

export function refreshSession(): Promise<boolean> {
  if (!refreshTok) return Promise.resolve(false);
  if (inFlight) return inFlight;
  inFlight = doRefresh().finally(() => { inFlight = null; });
  return inFlight;
}

async function doRefresh(): Promise<boolean> {
  try {
    const res = await fetch(`${SB_URL}/auth/v1/token?grant_type=refresh_token`, {
      method: 'POST', headers: headers(),
      body: JSON.stringify({ refresh_token: refreshTok }),
    });
    const json = await res.json();
    if (!res.ok || !json.access_token) { await signOut(); return false; }
    await persist(json);
    return true;
  } catch {
    // A network failure is NOT a dead session. Returning false without signing
    // out leaves the stored refresh token in place, so the next attempt — on a
    // train, when signal returns — can still succeed.
    return false;
  }
}

function authError(json: any): string {
  return json?.error_description || json?.msg || json?.message || 'Authentication failed.';
}

export async function signIn(mail: string, password: string): Promise<void> {
  const res = await fetch(`${SB_URL}/auth/v1/token?grant_type=password`, {
    method: 'POST', headers: headers(),
    body: JSON.stringify({ email: mail, password }),
  });
  const json = await res.json();
  if (!res.ok || !json.access_token) throw new Error(authError(json));
  await persist(json);
}

export async function signUp(mail: string, password: string): Promise<'authed' | 'confirm'> {
  const res = await fetch(`${SB_URL}/auth/v1/signup`, {
    method: 'POST', headers: headers(),
    body: JSON.stringify({ email: mail, password }),
  });
  const json = await res.json();
  if (!res.ok) throw new Error(authError(json));
  if (json.access_token) { await persist(json); return 'authed'; }
  return 'confirm';                       // email confirmation is on
}

/** Ask Supabase to email a recovery link.
 *
 *  Says nothing about whether the address exists, deliberately: a reset form
 *  that distinguishes "sent" from "no such account" is an account-enumeration
 *  oracle. The caller shows one message either way. */
export async function requestPasswordReset(mail: string, redirectTo: string): Promise<void> {
  const res = await fetch(
    `${SB_URL}/auth/v1/recover?redirect_to=${encodeURIComponent(redirectTo)}`,
    { method: 'POST', headers: headers(), body: JSON.stringify({ email: mail }) });
  if (!res.ok) throw new Error(`Could not send the reset email (HTTP ${res.status}).`);
}

export async function signOut(): Promise<void> {
  // The cache goes with the session. A locker left on disk after sign-out is
  // one person's gear readable from the next person's session on a shared
  // phone — and phones get shared at trailheads more than anywhere else.
  await clearCache();
  access = ''; refreshTok = ''; expiresAt = 0; email = ''; userId = '';
  await Promise.all([K.a, K.r, K.e, K.m, K.u].map(k => SecureStore.deleteItemAsync(k)));
}
