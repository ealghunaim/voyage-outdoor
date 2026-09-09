// The persisted read-through cache.
//
// WHY THIS EXISTS IN COMMIT ONE. VoyageOS has no cache at all: every screen
// fetches on mount, so a dead connection is a blank screen everywhere. §20
// asks for offline-first — the current adventure, its pack list, the gear on
// it, and the emergency information available with no signal — and that is not
// a thing you add to thirty screens afterwards. It is a thing the data layer
// either does or does not do.
//
// Backed by expo-sqlite/kv-store: the same API as AsyncStorage, with
// synchronous accessors, and it is the store Expo SDK 54 documents for this.
// Not SecureStore — that is for the session, has a small value ceiling, and
// hits the keychain on every read.
//
// WHAT THIS IS NOT: a query library. There is no request dedupe, no background
// revalidation window, no mutation invalidation graph. Those are worth having
// and none of them are worth a dependency in Phase 1. The shape below —
// read cache, render, fetch, write cache, render again — is the 80% and it is
// forty lines.

import { useCallback, useEffect, useRef, useState } from 'react';
import Storage from 'expo-sqlite/kv-store';

const PREFIX = 'vo.cache.';

type Envelope<T> = { v: 1; at: number; data: T };

/** Bumped when a cached shape changes in a way old entries cannot satisfy.
 *  Entries written under a different version are ignored rather than migrated —
 *  a cache is by definition rebuildable, and a migration for one is work that
 *  buys a single cold fetch. */
const SHAPE = 1;

export async function readCache<T>(key: string): Promise<Envelope<T> | null> {
  try {
    const raw = await Storage.getItem(PREFIX + key);
    if (!raw) return null;
    const parsed = JSON.parse(raw) as Envelope<T>;
    return parsed?.v === SHAPE ? parsed : null;
  } catch {
    // A corrupt entry is not an error worth surfacing — it is a cache miss.
    return null;
  }
}

export async function writeCache<T>(key: string, data: T): Promise<void> {
  try {
    const envelope: Envelope<T> = { v: SHAPE, at: Date.now(), data };
    await Storage.setItem(PREFIX + key, JSON.stringify(envelope));
  } catch {
    // Never let a failed write fail the request that succeeded.
  }
}

export async function dropCache(key: string): Promise<void> {
  try { await Storage.removeItem(PREFIX + key); } catch { /* nothing to drop */ }
}

/** Everything under the cache prefix. Called on sign-out.
 *
 *  One person's locker must not be readable from another person's session on a
 *  shared phone, and a cache that outlives the session is exactly that. */
export async function clearCache(): Promise<void> {
  try {
    const keys = await Storage.getAllKeys();
    await Promise.all(keys.filter(k => k.startsWith(PREFIX))
                          .map(k => Storage.removeItem(k)));
  } catch { /* best effort */ }
}

/** What the hook holds. `key` is part of the state so that state left over
 *  from a previous key is recognisable as stale without a reset. */
type Entry<T> = {
  key: string | null;
  data: T | null;
  loading: boolean;
  error: string | null;
  stale: boolean;
};

export type Cached<T> = {
  data: T | null;
  /** True while a network fetch is in flight AND there is nothing to show. */
  loading: boolean;
  /** Non-null when the last fetch failed. Coexists with `data`: showing stale
   *  gear beside "couldn't refresh" is more useful than showing neither. */
  error: string | null;
  /** The data on screen came from disk and has not been confirmed this session. */
  stale: boolean;
  refresh: () => Promise<void>;
  /** Write through, for a mutation that already knows the new value. Saves the
   *  round trip AND keeps the cache honest — the alternative is dropping the
   *  key and showing a spinner over data the app is holding. */
  set: (data: T) => void;
};

/**
 * Render from disk immediately, then confirm over the network.
 *
 * `key` must identify the DATA, not the screen — two screens showing the
 * locker share a key and therefore share the cache entry.
 */
export function useCached<T>(key: string | null,
                             fetcher: () => Promise<T>): Cached<T> {
  // ONE STATE OBJECT, CARRYING ITS OWN KEY.
  //
  // The obvious shape — four useStates plus `setLoading(true)` in the effect
  // when the key changes — is a synchronous setState inside an effect, which
  // React 19 flags because it renders twice for every navigation. Stamping the
  // key onto the state instead makes "loading" a comparison rather than an
  // assignment: state belonging to the previous key IS the loading state, and
  // nothing has to be reset.
  const [entry, setEntry] = useState<Entry<T>>(
    { key: null, data: null, loading: true, error: null, stale: false });

  // The fetcher is almost always an inline arrow, so it is a new function on
  // every render. Kept in a ref rather than in the dependency list, which would
  // re-run the effect forever — updated in an effect rather than during render,
  // because a ref written during render is not safe under concurrent rendering.
  const fetchRef = useRef(fetcher);
  useEffect(() => { fetchRef.current = fetcher; });

  const alive = useRef(true);
  useEffect(() => {
    alive.current = true;
    return () => { alive.current = false; };
  }, []);

  const load = useCallback(async (useDisk: boolean) => {
    if (!key) return;

    if (useDisk) {
      const hit = await readCache<T>(key);
      // Only fills an EMPTY slot. If the network already answered — which it
      // can, on a fast connection with a slow disk — the fresh value must not
      // be replaced by the stale one.
      if (hit && alive.current) {
        setEntry(prev => (prev.key === key && prev.data !== null ? prev : {
          key, data: hit.data, loading: false, error: null, stale: true,
        }));
      }
    }

    try {
      const fresh = await fetchRef.current();
      if (!alive.current) return;
      setEntry({ key, data: fresh, loading: false, error: null, stale: false });
      writeCache(key, fresh);
    } catch (e: any) {
      if (!alive.current) return;
      // The error joins whatever is on screen rather than replacing it. Stale
      // gear beside "couldn't refresh" beats an empty screen with an error on
      // it — which is the whole reason this layer exists.
      setEntry(prev => ({
        key,
        data: prev.key === key ? prev.data : null,
        loading: false,
        error: e?.message ?? 'Could not refresh.',
        stale: prev.key === key ? prev.stale : false,
      }));
    }
  }, [key]);

  useEffect(() => { load(true); }, [load]);

  const current = entry.key === key;
  return {
    data: current ? entry.data : null,
    loading: !current || entry.loading,
    error: current ? entry.error : null,
    stale: current ? entry.stale : false,
    refresh: () => load(false),
    set: (next: T) => {
      if (!key) return;
      setEntry({ key, data: next, loading: false, error: null, stale: false });
      writeCache(key, next);
    },
  };
}
