// The offline write queue — for pack states, and deliberately only for those.
//
// §20 asks for offline-first and names the packing list. Phase 1 gave every
// screen a read-through cache, which covers looking at your pack with no
// signal. It does not cover the thing you actually DO on that screen: ticking
// items off. Before this file, a tap in a car park with no bars updated the row
// optimistically, failed, and then `pack.refresh()` put it straight back —
// so the one interaction the app exists for was the one that did not survive
// losing signal.
//
// SCOPED TO ONE OPERATION, ON PURPOSE. A general mutation queue is a sync
// engine: ordering, conflict resolution, partial failure, replay semantics.
// Building a bad one is worse than not having it. Pack state is the operation
// §20 names, it happens in exactly the place there is no signal, and it has a
// property that makes queueing genuinely simple rather than merely tempting:
//
//   SETTING A STATE IS IDEMPOTENT AND LAST-WRITE-WINS. Two taps on the same
//   item do not need to both be sent — only the final state matters. So the
//   queue collapses by item id and can never grow past the number of items on
//   the list, however long the signal is out.
//
// Everything else (adding gear, generating a pack, writing a review) still
// requires a connection and says so. That is honest: those are creations, and
// a creation queued for six hours is a thing the user has forgotten they did.

import Storage from 'expo-sqlite/kv-store';

import { PackState, setPackItemState } from './api';

const KEY = 'vo.queue.packstate.v1';

export type Pending = {
  adventureId: string;
  itemId: string;
  state: PackState;
  /** When the tap happened, not when it syncs. Used only for display. */
  at: number;
};

/** Keyed by itemId — see the note on collapsing above. */
type Queue = Record<string, Pending>;

async function read(): Promise<Queue> {
  try {
    const raw = await Storage.getItem(KEY);
    return raw ? (JSON.parse(raw) as Queue) : {};
  } catch {
    return {};
  }
}

async function write(q: Queue): Promise<void> {
  try { await Storage.setItem(KEY, JSON.stringify(q)); } catch { /* best effort */ }
}

/** A network failure, as opposed to the server saying no.
 *
 *  THE DISTINCTION IS THE WHOLE RETRY POLICY. api.ts throws a plain Error with
 *  no status when fetch itself failed, and attaches `status` when the server
 *  answered. A 404 means the item was deleted on another device and retrying it
 *  forever would keep a dead row in the queue until reinstall; a dropped
 *  connection means try again in a minute. */
function isOffline(e: any): boolean {
  return typeof e?.status !== 'number';
}

export async function enqueue(adventureId: string, itemId: string,
                              state: PackState): Promise<void> {
  const q = await read();
  q[itemId] = { adventureId, itemId, state, at: Date.now() };
  await write(q);
}

export async function pendingCount(): Promise<number> {
  return Object.keys(await read()).length;
}

export async function pendingFor(adventureId: string): Promise<Pending[]> {
  return Object.values(await read()).filter(p => p.adventureId === adventureId);
}

/** Applies queued states over a freshly-fetched list.
 *
 *  Without this, opening the Pack screen while still offline shows the SERVER's
 *  states — i.e. the app forgetting what you just did, which is worse than not
 *  having queued it at all. */
export function overlay<T extends { id: string; state: PackState }>(
  items: T[], pending: Pending[]): T[] {
  if (!pending.length) return items;
  const by = new Map(pending.map(p => [p.itemId, p.state]));
  return items.map(i => (by.has(i.id) ? { ...i, state: by.get(i.id)! } : i));
}

export type FlushResult = { sent: number; dropped: number; left: number };

/** Send what is queued. Safe to call often; does nothing when empty.
 *
 *  Stops at the FIRST network failure rather than trying the rest: if the
 *  connection is gone it is gone for all of them, and hammering a dead radio is
 *  how a phone's battery disappears on a mountain. */
export async function flush(): Promise<FlushResult> {
  const q = await read();
  const items = Object.values(q);
  if (!items.length) return { sent: 0, dropped: 0, left: 0 };

  let sent = 0;
  let dropped = 0;
  for (const p of items) {
    try {
      await setPackItemState(p.adventureId, p.itemId, p.state);
      delete q[p.itemId];
      sent++;
    } catch (e: any) {
      if (isOffline(e)) break;
      // The server answered and refused. Retrying will not change its mind.
      delete q[p.itemId];
      dropped++;
    }
  }
  await write(q);
  return { sent, dropped, left: Object.keys(q).length };
}

export async function clearQueue(): Promise<void> {
  try { await Storage.removeItem(KEY); } catch { /* nothing to clear */ }
}
