// The transport, and every endpoint the app knows about.
//
// req() is forked from VoyageOS, including two fixes that were each a shipped
// bug there: a 204 response must not go through res.json() (JSON.parse('')
// throws, which is how deleting a thing succeeded and reported a crash), and a
// FastAPI `detail` can be an object (which arrived as "[object Object]" in
// front of users).

import { getToken, refreshSession } from './auth';
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

export type ActivitySchema = {
  version: string;
  gear: Record<string, Record<string, FieldSpec>>;
  adventure: Record<string, FieldSpec>;
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
  const token = getToken();
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

  if (res.status === 401 && token) {
    // One refresh, one retry. A second 401 after a fresh token means the
    // session is genuinely gone rather than merely stale.
    if (!_retried && await refreshSession()) return req(path, options, true);
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

export const logUsage = (gearId: string, body: object): Promise<UsageEntry> =>
  req(`/v1/gear/${gearId}/usage`, { method: 'POST', body: JSON.stringify(body) });

export const deleteUsage = (usageId: string): Promise<null> =>
  req(`/v1/gear/usage/${usageId}`, { method: 'DELETE' });

export const logMaintenance = (gearId: string, body: object): Promise<MaintenanceEntry> =>
  req(`/v1/gear/${gearId}/maintenance`, { method: 'POST', body: JSON.stringify(body) });

export const deleteMaintenance = (eventId: string): Promise<null> =>
  req(`/v1/gear/maintenance/${eventId}`, { method: 'DELETE' });
