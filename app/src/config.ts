import Constants from 'expo-constants';

const extra = (Constants.expoConfig?.extra ?? {}) as Record<string, string>;

/** Point a dev build at a local API without editing app.json.
 *
 *      EXPO_PUBLIC_API_URL=http://localhost:8000 npx expo start
 *
 *  WHY THIS EXISTS. The alternative is editing `extra.apiUrl` and remembering
 *  to put it back, and "remembering to put it back" is how a build ships
 *  pointing at a laptop. This repo already has scripts/check_config.py because
 *  render.yaml once still named a deleted Supabase project for exactly that
 *  reason — a value edited for a test and left behind.
 *
 *  EXPO_PUBLIC_ variables are inlined at BUILD time, so an unset one compiles
 *  to undefined and app.json wins. A release build made without the variable
 *  cannot carry a localhost URL no matter what the shell had in it.
 *
 *  WHERE THE VALUE COMES FROM NOW: eas.json, not your shell.
 *
 *  The `development` and `simulator` profiles set EXPO_PUBLIC_API_URL to
 *  localhost:8000; `preview` and `production` set no env at all, so they can
 *  only resolve to extra.apiUrl below. That split is the reason eas.json is
 *  worth reading — but EAS validates that file strictly and rejects comment
 *  keys, so the explanation lives here, beside the fallback it protects.
 *
 *  The fallback is SILENT, which is correct for a release and a trap in
 *  development. This project got bitten by the read-only half of it: a dev
 *  client restarted without the variable quietly changed servers mid-session,
 *  a locker went from 19 items to 9 between two screenshots, and the first
 *  conclusion was that data had been deleted. Nothing had. The Profile
 *  screen's "Server" row exists because of that afternoon. */
export const API_URL = process.env.EXPO_PUBLIC_API_URL || extra.apiUrl || '';
export const APP_KEY = extra.appKey ?? '';
export const SUPABASE_URL = extra.supabaseUrl ?? '';
export const SUPABASE_ANON_KEY = extra.supabaseAnonKey ?? '';

/** The version this build reports, read from app.json rather than typed.
 *
 *  VoyageOS shipped a hand-written `v1.0-dev` to the App Store and every paying
 *  customer saw a build labelled "dev" for an entire release. A version string
 *  is only correct until the first time somebody forgets it. */
export const APP_VERSION = Constants.expoConfig?.version ?? '';

/** Whether the app has enough configuration to reach anything.
 *
 *  Checked at boot so a missing key produces one honest screen instead of a
 *  cascade of failed requests that each look like a network problem. */
export function configured(): { ok: boolean; missing: string[] } {
  const missing: string[] = [];
  if (!API_URL) missing.push('apiUrl');
  if (!SUPABASE_URL) missing.push('supabaseUrl');
  if (!SUPABASE_ANON_KEY) missing.push('supabaseAnonKey');
  return { ok: missing.length === 0, missing };
}
