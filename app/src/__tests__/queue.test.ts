/**
 * The offline write queue (§20).
 *
 * THE APP HAD 281 TESTS AND NONE OF THEM WERE JAVASCRIPT. Everything
 * deterministic lived on the server, so that was defensible until Phase 6 put
 * real logic on the device: what to do when a write fails, what the screen
 * shows while it waits, and which failures are worth retrying. §27 lists
 * testing as a Phase 6 item; this is what it was for.
 *
 * The queue is also the hardest thing here to verify by hand — it needs no
 * signal, which is the one condition a simulator will not give you on demand.
 */
import Storage from 'expo-sqlite/kv-store';

import {
  clearQueue, enqueue, flush, overlay, pendingCount, pendingFor,
} from '../queue';

// The API module is the only thing the queue reaches out to. Mocked so a failure
// can be made to look like a dropped connection or a refusing server on demand.
jest.mock('../api', () => ({ setPackItemState: jest.fn() }));
// eslint-disable-next-line @typescript-eslint/no-var-requires
const { setPackItemState } = require('../api');

// kv-store, in memory. Nothing here is testing SQLite.
jest.mock('expo-sqlite/kv-store', () => {
  const mem: Record<string, string> = {};
  return {
    __esModule: true,
    default: {
      getItem: jest.fn(async (k: string) => mem[k] ?? null),
      setItem: jest.fn(async (k: string, v: string) => { mem[k] = v; }),
      removeItem: jest.fn(async (k: string) => { delete mem[k]; }),
      getAllKeys: jest.fn(async () => Object.keys(mem)),
    },
  };
});

/** A dropped connection: api.ts throws a bare Error with no `status`. */
const offline = () => Object.assign(new Error("Can't reach Voyage Outdoor"), {});
/** The server answered and refused. */
const refused = (status: number) =>
  Object.assign(new Error('Not on this pack list'), { status });

beforeEach(async () => {
  await clearQueue();
  (setPackItemState as jest.Mock).mockReset();
});

test('a queued change survives and comes back out', async () => {
  await enqueue('adv1', 'item1', 'packed');
  expect(await pendingCount()).toBe(1);
  expect(await pendingFor('adv1')).toEqual([
    expect.objectContaining({ itemId: 'item1', state: 'packed' }),
  ]);
});

test('two taps on the same item collapse to the last one', async () => {
  // The property the whole design rests on: setting a state is idempotent and
  // last-write-wins, so the queue can never grow past the length of the list
  // however long the signal is out.
  await enqueue('adv1', 'item1', 'selected');
  await enqueue('adv1', 'item1', 'packed');
  await enqueue('adv1', 'item1', 'verified');
  const pending = await pendingFor('adv1');
  expect(pending).toHaveLength(1);
  expect(pending[0].state).toBe('verified');
});

test('changes for another adventure are not returned', async () => {
  await enqueue('adv1', 'item1', 'packed');
  await enqueue('adv2', 'item2', 'packed');
  expect(await pendingFor('adv1')).toHaveLength(1);
  expect(await pendingCount()).toBe(2);
});

test('overlay shows what you did, not what the server last knew', async () => {
  // Without this, reopening the pack while still offline shows the server's
  // states — the app forgetting the taps you just made, which is worse than
  // never having queued them.
  const items = [
    { id: 'a', state: 'not_selected' as const },
    { id: 'b', state: 'not_selected' as const },
  ];
  const merged = overlay(items, [
    { adventureId: 'adv1', itemId: 'b', state: 'packed', at: 1 },
  ]);
  expect(merged.map(i => i.state)).toEqual(['not_selected', 'packed']);
  // And it must not mutate what it was given.
  expect(items[1].state).toBe('not_selected');
});

test('overlay with nothing pending returns the same array', async () => {
  const items = [{ id: 'a', state: 'packed' as const }];
  expect(overlay(items, [])).toBe(items);
});

test('flush sends what is queued and empties it', async () => {
  (setPackItemState as jest.Mock).mockResolvedValue({});
  await enqueue('adv1', 'item1', 'packed');
  await enqueue('adv1', 'item2', 'verified');

  const result = await flush();
  expect(result).toEqual({ sent: 2, dropped: 0, left: 0 });
  expect(setPackItemState).toHaveBeenCalledTimes(2);
  expect(await pendingCount()).toBe(0);
});

test('a dropped connection keeps the change and stops trying', async () => {
  // Hammering a dead radio is how a phone's battery disappears on a mountain —
  // if the connection is gone it is gone for all of them.
  (setPackItemState as jest.Mock).mockRejectedValue(offline());
  await enqueue('adv1', 'item1', 'packed');
  await enqueue('adv1', 'item2', 'packed');
  await enqueue('adv1', 'item3', 'packed');

  const result = await flush();
  expect(result.sent).toBe(0);
  expect(result.dropped).toBe(0);
  expect(result.left).toBe(3);
  expect(setPackItemState).toHaveBeenCalledTimes(1);   // stopped at the first
  expect(await pendingCount()).toBe(3);
});

test('a server that refuses drops the change rather than retrying forever', async () => {
  // A 404 means the item was deleted on another device. Retrying that keeps a
  // dead row in the queue until the app is reinstalled.
  (setPackItemState as jest.Mock).mockRejectedValue(refused(404));
  await enqueue('adv1', 'gone', 'packed');

  const result = await flush();
  expect(result).toEqual({ sent: 0, dropped: 1, left: 0 });
  expect(await pendingCount()).toBe(0);
});

test('a refusal does not cost the changes behind it', async () => {
  (setPackItemState as jest.Mock)
    .mockRejectedValueOnce(refused(404))
    .mockResolvedValueOnce({});
  await enqueue('adv1', 'gone', 'packed');
  await enqueue('adv1', 'fine', 'packed');

  const result = await flush();
  expect(result.dropped).toBe(1);
  expect(result.sent).toBe(1);
  expect(result.left).toBe(0);
});

test('flushing an empty queue does nothing and calls nothing', async () => {
  const result = await flush();
  expect(result).toEqual({ sent: 0, dropped: 0, left: 0 });
  expect(setPackItemState).not.toHaveBeenCalled();
});

test('signing out must leave nothing behind', async () => {
  // An unsent pack state belonging to the previous person would otherwise sync
  // into the NEXT person's account the moment signal returned.
  await enqueue('adv1', 'item1', 'packed');
  await clearQueue();
  expect(await pendingCount()).toBe(0);
});

test('a corrupt queue reads as empty rather than throwing', async () => {
  await (Storage as any).setItem('vo.queue.packstate.v1', '{not json');
  expect(await pendingCount()).toBe(0);
  expect(await flush()).toEqual({ sent: 0, dropped: 0, left: 0 });
});
