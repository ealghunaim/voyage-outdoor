import Constants from 'expo-constants';

const extra = (Constants.expoConfig?.extra ?? {}) as Record<string, string>;

export const API_URL = extra.apiUrl ?? '';
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
