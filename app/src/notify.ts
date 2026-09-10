// Scheduling the notification plan on this device (§21).
//
// THE DECISION IS THE SERVER'S, THE DELIVERY IS THE PHONE'S. api/engines/
// notify.py decides what is worth saying — it has the whole record in front of
// it and it is a versioned engine with tests. This file only turns that list
// into scheduled local notifications.
//
// The split is not tidiness. There is no scheduler on the API (Phase 0, risk
// #3), so a server-pushed reminder has nothing to send it. A local one fires
// three days from now at six in the evening with the phone in aeroplane mode
// on a mountain, which is the situation the feature exists for.
//
// OFF BY DEFAULT, AND THE PROMPT IS NOT ON LAUNCH. An app that asks for
// notification permission before the user has done anything is an app that gets
// "Don't Allow" and then has no way back. This is a toggle in Profile, and the
// system prompt appears when somebody turns it on — at which point they have
// asked for it and the answer is usually yes.

import * as Notifications from 'expo-notifications';
import Storage from 'expo-sqlite/kv-store';

import { NotificationPlan, getNotificationPlan } from './api';

const ENABLED = 'vo.notify.enabled.v1';

/** Local date, from the DEVICE. The server cannot know which day it is where
 *  the runner is standing, and "the evening before" is a local idea. */
function localToday(): string {
  const d = new Date();
  const pad = (n: number) => String(n).padStart(2, '0');
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
}

export async function notificationsEnabled(): Promise<boolean> {
  try { return (await Storage.getItem(ENABLED)) === '1'; } catch { return false; }
}

export async function setNotificationsEnabled(on: boolean): Promise<void> {
  try { await Storage.setItem(ENABLED, on ? '1' : '0'); } catch { /* best effort */ }
}

/** Ask the OS. Returns whether we may actually post anything. */
export async function requestPermission(): Promise<boolean> {
  const existing = await Notifications.getPermissionsAsync();
  if (existing.granted) return true;
  // canAskAgain is false once the user has said no — asking again does nothing
  // and returns denied, so the caller needs to send them to Settings instead.
  if (!existing.canAskAgain) return false;
  const asked = await Notifications.requestPermissionsAsync();
  return !!asked.granted;
}

export async function cancelAll(): Promise<void> {
  try { await Notifications.cancelAllScheduledNotificationsAsync(); }
  catch { /* nothing scheduled */ }
}

export type SyncResult = { scheduled: number; reason?: string };

/**
 * Cancel everything and reschedule from the server's plan.
 *
 * CANCEL-ALL-THEN-RESCHEDULE, rather than diffing. The plan is a pure function
 * of the record (the engine's test asserts two runs produce identical keys and
 * dates), so rescheduling from scratch is idempotent and there is no local
 * state to drift. Diffing would be less work for the OS and one more thing that
 * can be subtly wrong.
 */
export async function syncNotifications(): Promise<SyncResult> {
  if (!(await notificationsEnabled())) return { scheduled: 0, reason: 'off' };
  if (!(await requestPermission())) return { scheduled: 0, reason: 'denied' };

  let plan: NotificationPlan;
  try {
    plan = await getNotificationPlan(localToday());
  } catch {
    // NOTHING IS CANCELLED ON A FAILED FETCH. Losing signal must not silently
    // wipe reminders that were already scheduled — that is the exact moment
    // they matter most.
    return { scheduled: 0, reason: 'offline' };
  }

  await cancelAll();

  let scheduled = 0;
  for (const n of plan.notifications) {
    // Built in LOCAL time from the plan's date and hour, which is what makes a
    // reminder survive flying to the race — the server never sends a timestamp.
    const [y, m, d] = n.on.split('-').map(Number);
    const when = new Date(y, m - 1, d, n.hour, 0, 0, 0);
    if (when.getTime() <= Date.now()) continue;   // never schedule the past
    try {
      await Notifications.scheduleNotificationAsync({
        identifier: n.key,
        content: {
          title: n.title,
          body: n.body,
          data: { kind: n.kind, subject_type: n.subject_type,
                  subject_id: n.subject_id },
        },
        trigger: { type: Notifications.SchedulableTriggerInputTypes.DATE,
                   date: when },
      });
      scheduled++;
    } catch {
      // One bad entry must not cost the rest of the plan.
    }
  }
  return { scheduled };
}

/** Turning it on: permission, then an immediate sync so the toggle does
 *  something visible rather than promising something for later. */
export async function enableNotifications(): Promise<SyncResult> {
  await setNotificationsEnabled(true);
  const result = await syncNotifications();
  if (result.reason === 'denied') await setNotificationsEnabled(false);
  return result;
}

export async function disableNotifications(): Promise<void> {
  await setNotificationsEnabled(false);
  await cancelAll();
}
