// The transport, and every endpoint the app knows about.
//
// req() is forked from VoyageOS, including two fixes that were each a shipped
// bug there: a 204 response must not go through res.json() (JSON.parse('')
// throws, which is how deleting a thing succeeded and reported a crash), and a
// FastAPI `detail` can be an object (which arrived as "[object Object]" in
// front of users).

import { getToken, hasSession, refreshSession } from './auth';
import * as CFG from './config';

const API_URL = CFG.API_URL;
const APP_KEY = CFG.APP_KEY;

let onAuthFail: (() => void) | null = null;
export function setAuthFailHandler(fn: () => void) { onAuthFail = fn; }

// ── types ───────────────────────────────────────────────────────────────────

export type FieldSpec = {
  type: 'string' | 'text' | 'int' | 'number' | 'bool' | 'enum' | 'multi_enum' | 'string_list';
  label: string;
  unit?: string;
  options?: string[];
  required?: boolean;
  min?: number;
  max?: number;
};

/** How a category records use, decided by the server's registry rather than by
 *  the screen. 'distance' logs a run and sums kilometres; 'sessions' logs an
 *  outing and counts them; 'none' is consumed and accumulates nothing. */
export type UsageKind = 'distance' | 'sessions' | 'none';

export type ActivitySchema = {
  version: string;
  gear: Record<string, Record<string, FieldSpec>>;
  adventure: Record<string, FieldSpec>;
  usage: Record<string, UsageKind>;
  /** Categories that genuinely have a `size`. Anything absent is measured some
   *  other way — poles by length, flasks by volume — and must not be offered
   *  the generic size box beside its real field. */
  sized: string[];
};

export type Activity = { key: string; name: string; built: boolean; sort: number };

export type GearCategory = {
  key: string; name: string; activity_key: string | null;
  parent_key: string | null; sort: number;
};

export type GearStatus = 'active' | 'retired' | 'lost' | 'damaged';

export type GearItem = {
  id: string;
  name: string;
  brand: string | null;
  model: string | null;
  category_key: string | null;
  activity_key: string | null;
  size: string | null;
  color: string | null;
  weight_g: number | null;
  purchase_date: string | null;
  purchase_price_cents: number | null;
  currency: string | null;
  serial_number: string | null;
  notes: string | null;
  /** Null until the Phase 3 gear-health engine exists. The UI must render that
   *  as "not yet measured", never as 0% — see §12 on uncertain estimates. */
  condition_pct: number | null;
  status: GearStatus;
  favorite: boolean;
  attributes: Record<string, any>;
  tags: string[];
  retired_at: string | null;
  created_at: string;
};

export type UsageEntry = {
  id: string; gear_item_id: string; adventure_id: string | null;
  occurred_on: string; distance_m: number | null; duration_s: number | null;
  conditions: Record<string, any>; notes: string | null;
};

export type MaintenanceEntry = {
  id: string; gear_item_id: string; kind: string; occurred_on: string;
  notes: string | null; cost_cents: number | null; next_due_on: string | null;
};

export type GearDetail = GearItem & {
  usage: UsageEntry[];
  maintenance: MaintenanceEntry[];
  totals: {
    sessions: number; distance_m: number; duration_s: number;
    last_used_on: string | null;
  };
};

export type AdventureStatus =
  'draft' | 'planned' | 'active' | 'completed' | 'archived';

export type Adventure = {
  id: string;
  activity_key: string;
  subtype: string | null;
  title: string;
  place_name: string | null;
  country_code: string | null;
  lat: number | null;
  lng: number | null;
  start_date: string;
  end_date: string;
  status: AdventureStatus;
  attributes: Record<string, any>;
  created_at: string;
};

export type WeatherDay = {
  id: string;
  forecast_date: string;
  temp_min: number | null;
  temp_max: number | null;
  /** NULL means the provider has no opinion, NOT that rain is impossible.
   *  MET Norway carries no precipitation probability at all, so anything
   *  reading this must render null as "—" rather than as 0%. */
  precip_prob: number | null;
  wind_kph: number | null;
  uv: number | null;
  provider: string;
  fetched_at: string;
};

export type AdventureDetail = Adventure & {
  weather: WeatherDay[];
  usage: any[];
};

export type Place = {
  name: string;
  admin: string | null;
  country: string | null;
  country_code: string | null;
  lat: number;
  lng: number;
  elevation_m: number | null;
};

/** Why a weather refresh produced nothing, when it produced nothing.
 *  Each of these is an ordinary state rather than a failure, which is why the
 *  server answers with a reason instead of an error code. */
export type WeatherResult = {
  stored: number;
  reason: 'fetched' | 'fresh' | 'no_location' | 'beyond_horizon' | 'unavailable';
  detail?: string;
  provider?: string;
  days?: WeatherDay[];
};

export type Classification =
  'required' | 'recommended' | 'optional' | 'not_needed' | 'missing';

/** What the person has done about an item — deliberately separate from the
 *  classification, which is what the engine decided. Conflating them loses the
 *  ability to say "you were told to bring this and you have not." */
export type PackState =
  | 'not_selected' | 'selected' | 'packed' | 'verified'
  | 'in_use' | 'returned' | 'missing' | 'damaged';

export type PackItem = {
  id: string;
  gear_item_id: string | null;
  name: string;
  category_key: string | null;
  qty: number;
  classification: Classification;
  state: PackState;
  critical: boolean;
  /** Which rule produced this line. Provenance, not decoration — it is what
   *  makes "why is this here" answerable. */
  rule_key: string | null;
  reason: string | null;
  source: 'rule' | 'mandatory' | 'manual';
  sort: number;
};

export type PackWarningRow = {
  id: string;
  gear_item_id: string | null;
  key: string;
  severity: 'note' | 'caution' | 'critical';
  message: string;
  rule_key: string;
  detail: Record<string, any>;
};

export type Readiness = {
  required_total: number;
  required_packed: number;
  required_verified: number;
  remaining: number;
  critical_total: number;
  critical_unverified: number;
  missing_total: number;
  /** Null when nothing is required yet. NOT 100 — an empty pack is not a
   *  ready one, and rendering 100% over an unplanned adventure is exactly the
   *  false reassurance the engines exist to avoid. */
  percent: number | null;
  ready: boolean;
};

export type Pack = {
  list: { id: string; ruleset_version: string; generated_at: string;
          generation_snapshot: Record<string, any> } | null;
  items: PackItem[];
  warnings: PackWarningRow[];
  readiness: Readiness;
};

export type Me = {
  profile: { id: string; email: string | null; name: string | null;
             unit_system: 'metric' | 'imperial'; locale: string } | null;
  preferences: { user_id: string; distance_unit: 'km' | 'mi';
                 weight_unit: 'g' | 'oz'; notification_daily_cap: number } | null;
};

// ── transport ───────────────────────────────────────────────────────────────

function readableDetail(detail: unknown, status: number): string {
  if (typeof detail === 'string' && detail) return detail;
  if (detail && typeof detail === 'object') {
    const m = (detail as any).message;
    if (typeof m === 'string' && m) return m;
    try { return JSON.stringify(detail); } catch { /* fall through */ }
  }
  return `HTTP ${status}`;
}

/** Not res.json(). A 204 carries an empty body and JSON.parse('') throws. */
function readBody(status: number, text: string): any {
  if (status === 204 || !text) return null;
  try { return JSON.parse(text); } catch { return text; }
}

export async function req(path: string, options: RequestInit = {},
                         _retried = false): Promise<any> {
  // AN EXPIRED TOKEN IS NOT A MISSING SESSION.
  //
  // getToken() answers '' once the access token is within 30s of expiry, and
  // the old code then sent no Authorization header at all — so the server
  // answered 401 and the refresh branch below, which required `token` to be
  // truthy, never ran. After an hour the app sat on cached data with "Sign in
  // required" until it was relaunched, and the offline cache made that look
  // like a network blip rather than a broken session. VoyageOS ships the same
  // bug at the same line.
  let token = getToken();
  if (!token && hasSession()) {
    if (await refreshSession()) token = getToken();
  }
  let res: Response;
  try {
    res = await fetch(`${API_URL}${path}`, {
      ...options,
      headers: {
        'Content-Type': 'application/json',
        ...(APP_KEY ? { 'x-voyage-key': APP_KEY } : {}),
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
        ...(options.headers ?? {}),
      },
    });
  } catch {
    throw new Error("Can't reach Voyage Outdoor — check your connection.");
  }

  // No `&& token` guard. A 401 is a 401 whether or not this call managed to
  // attach a token — that condition was the bug.
  if (res.status === 401) {
    // One refresh, one retry. A second 401 after a fresh token means the
    // session is genuinely gone rather than merely stale.
    if (!_retried && hasSession() && await refreshSession()) {
      return req(path, options, true);
    }
    onAuthFail?.();
    throw new Error('Session expired — sign in again.');
  }

  if (!res.ok) {
    let body: any = null;
    try { body = await res.json(); } catch { /* not every error has a body */ }
    const err: Error & { code?: string; status?: number } =
      new Error(readableDetail(body?.detail, res.status));
    err.status = res.status;
    const detail = body?.detail;
    if (detail && typeof detail === 'object' && typeof detail.code === 'string') {
      err.code = detail.code;
    }
    throw err;
  }

  return readBody(res.status, await res.text());
}

const qs = (params: Record<string, any>): string => {
  const parts = Object.entries(params)
    .filter(([, v]) => v !== undefined && v !== null && v !== '')
    .map(([k, v]) => `${k}=${encodeURIComponent(String(v))}`);
  return parts.length ? `?${parts.join('&')}` : '';
};

// ── endpoints ───────────────────────────────────────────────────────────────

export const getMe = (): Promise<Me> => req('/v1/me');

export const patchProfile = (body: object): Promise<Me> =>
  req('/v1/me', { method: 'PATCH', body: JSON.stringify(body) });

export const patchPreferences = (body: object): Promise<Me> =>
  req('/v1/me/preferences', { method: 'PATCH', body: JSON.stringify(body) });

export const listActivities = (): Promise<Activity[]> => req('/v1/activities');

export const getActivitySchema = (key: string): Promise<ActivitySchema> =>
  req(`/v1/activities/${key}/schema`);

export const listCategories = (activityKey?: string): Promise<GearCategory[]> =>
  req(`/v1/gear-categories${qs({ activity_key: activityKey })}`);

export type GearFilters = {
  status?: GearStatus | 'all';
  activity_key?: string;
  category_key?: string;
  favorite?: boolean;
  q?: string;
};

export const listGear = (f: GearFilters = {}): Promise<GearItem[]> =>
  req(`/v1/gear${qs(f)}`);

export const getGear = (id: string): Promise<GearDetail> => req(`/v1/gear/${id}`);

export const createGear = (body: object): Promise<GearItem> =>
  req('/v1/gear', { method: 'POST', body: JSON.stringify(body) });

export const updateGear = (id: string, body: object): Promise<GearItem> =>
  req(`/v1/gear/${id}`, { method: 'PATCH', body: JSON.stringify(body) });

export const deleteGear = (id: string): Promise<null> =>
  req(`/v1/gear/${id}`, { method: 'DELETE' });

// ── adventures ──────────────────────────────────────────────────────────────

export const listAdventures = (opts: { status?: AdventureStatus | 'all';
                                       upcoming?: boolean } = {}):
  Promise<Adventure[]> => req(`/v1/adventures${qs(opts)}`);

export const getAdventure = (id: string): Promise<AdventureDetail> =>
  req(`/v1/adventures/${id}`);

export const createAdventure = (body: object): Promise<Adventure> =>
  req('/v1/adventures', { method: 'POST', body: JSON.stringify(body) });

export const updateAdventure = (id: string, body: object): Promise<Adventure> =>
  req(`/v1/adventures/${id}`, { method: 'PATCH', body: JSON.stringify(body) });

export const deleteAdventure = (id: string): Promise<null> =>
  req(`/v1/adventures/${id}`, { method: 'DELETE' });

export const searchPlaces = (q: string): Promise<Place[]> =>
  req(`/v1/places${qs({ q })}`);

export const refreshWeather = (id: string, force = false): Promise<WeatherResult> =>
  req(`/v1/adventures/${id}/weather${qs({ force })}`, { method: 'POST' });

export type AttentionItem = {
  id: string; name: string; category_key: string | null;
  state: 'inspect' | 'past_expected';
  condition_pct: number | null;
  /** Written by the engine. A prompt to inspect, never a failure date. */
  message: string;
  detail: Record<string, any>;
};

export const gearNeedingAttention = (): Promise<{ items: AttentionItem[]; checked: number }> =>
  req('/v1/gear/attention');

// ── the pack ────────────────────────────────────────────────────────────────

export const getPack = (adventureId: string): Promise<Pack> =>
  req(`/v1/adventures/${adventureId}/pack`);

export const generatePack = (adventureId: string): Promise<Pack> =>
  req(`/v1/adventures/${adventureId}/pack`, { method: 'POST' });

export const setPackItemState = (adventureId: string, itemId: string,
                                 state: PackState): Promise<PackItem> =>
  req(`/v1/adventures/${adventureId}/pack/items/${itemId}`,
      { method: 'PATCH', body: JSON.stringify({ state }) });

export const addPackItem = (adventureId: string, body: object): Promise<PackItem> =>
  req(`/v1/adventures/${adventureId}/pack/items`,
      { method: 'POST', body: JSON.stringify(body) });

export const removePackItem = (adventureId: string, itemId: string): Promise<null> =>
  req(`/v1/adventures/${adventureId}/pack/items/${itemId}`, { method: 'DELETE' });

// ── the AI layer (Phase 4) ──────────────────────────────────────────────────
//
// EVERY CALL BELOW IS ADDITIVE. None of it feeds a classification, a warning or
// a readiness figure — those arrive already decided from the engines above. A
// screen that fails to load a narrative shows a pack; a screen that fails to
// load a pack shows nothing, and the difference is deliberate.

export type Narrative = {
  narrative: string | null;
  /** The pack moved under the paragraph — items packed, or the prompt itself
   *  changed. Not an error: the text is still what was true when written. */
  stale: boolean;
  model: string | null;
  prompt_version: string | null;
  generated_at: string | null;
  cost_usd?: number;
};

export const getNarrative = (adventureId: string): Promise<Narrative> =>
  req(`/v1/adventures/${adventureId}/pack/narrative`);

export const writeNarrative = (adventureId: string): Promise<Narrative> =>
  req(`/v1/adventures/${adventureId}/pack/narrative`, { method: 'POST' });

export type AskAnswer = {
  answer: string;
  model: string;
  cost_usd: number;
  grounded_in: { gear_items: number; adventures: number; pack: boolean };
};

export const ask = (question: string, adventureId?: string): Promise<AskAnswer> =>
  req('/v1/ask', {
    method: 'POST',
    body: JSON.stringify({ question, adventure_id: adventureId ?? null }),
  });

// ── race kit import (§24) ───────────────────────────────────────────────────

/** `text` is the checklist line; `detail` is the page's prose about it. They
 *  are separate because a pack list of twenty-three paragraphs is not a pack
 *  list — see api/racekit/extract.py for what the first version produced. */
export type KitItem = {
  text: string;
  detail: string | null;
  condition: string | null;
};

export type RaceKitDraft = {
  id: string;
  status: 'draft' | 'accepted' | 'discarded';
  adventure_id: string | null;
  source_kind: 'url' | 'paste';
  source_url: string | null;
  source_chars: number | null;
  fetched_at: string;
  race_name: string | null;
  edition: string | null;
  event: string | null;
  extracted: {
    race_name: string | null; edition: string | null; event: string | null;
    items: KitItem[]; recommended: string[]; note: string | null;
  };
  accepted_items: string[] | null;
  accepted_at: string | null;
  model: string | null;
  created_at: string;
};

export const createKitDraft = (body: { url?: string; text?: string;
                                       adventure_id?: string }):
  Promise<RaceKitDraft> =>
  req('/v1/race-kit/drafts', { method: 'POST', body: JSON.stringify(body) });

export const acceptKitDraft = (draftId: string, adventureId: string,
                               items: string[], mode: 'replace' | 'append' = 'replace'):
  Promise<{ adventure: Adventure; pack: Pack; import: RaceKitDraft }> =>
  req(`/v1/race-kit/drafts/${draftId}/accept`, {
    method: 'POST',
    body: JSON.stringify({ adventure_id: adventureId, items, mode }),
  });

export const discardKitDraft = (draftId: string): Promise<null> =>
  req(`/v1/race-kit/drafts/${draftId}`, { method: 'DELETE' });

/** Where an adventure's mandatory kit came from. Null when it was typed in by
 *  hand — which is a legitimate answer, not a missing one. */
export const getKitProvenance = (adventureId: string): Promise<RaceKitDraft | null> =>
  req(`/v1/adventures/${adventureId}/race-kit`);

// ── gear usage ──────────────────────────────────────────────────────────────

export const logUsage = (gearId: string, body: object): Promise<UsageEntry> =>
  req(`/v1/gear/${gearId}/usage`, { method: 'POST', body: JSON.stringify(body) });

export const deleteUsage = (usageId: string): Promise<null> =>
  req(`/v1/gear/usage/${usageId}`, { method: 'DELETE' });

export const logMaintenance = (gearId: string, body: object): Promise<MaintenanceEntry> =>
  req(`/v1/gear/${gearId}/maintenance`, { method: 'POST', body: JSON.stringify(body) });

export const deleteMaintenance = (eventId: string): Promise<null> =>
  req(`/v1/gear/maintenance/${eventId}`, { method: 'DELETE' });
