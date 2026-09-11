import React, { useState } from 'react';
import { Alert, Text, View } from 'react-native';

import { Me, getMe, patchPreferences } from '../api';
import { getEmail, signOut } from '../auth';
import { useCached } from '../cache';
import {
  Banner, Btn, Card, Chip, H, Label, Loading, Muted, Row, Screen, Toggle,
} from '../components/ui';
import { APP_VERSION } from '../config';
import {
  SyncResult, disableNotifications, enableNotifications, lastSync,
  notificationsEnabled, permissionStatus,
} from '../notify';
import { S, T, useTheme } from '../theme';

export default function Profile({ onSignedOut }: { onSignedOut: () => void }) {
  const { P, mode } = useTheme();
  const me = useCached<Me>('me', getMe);
  const [busy, setBusy] = useState(false);

  const prefs = me.data?.preferences;

  const setUnit = async (key: 'distance_unit' | 'weight_unit', value: string) => {
    setBusy(true);
    try {
      const next = await patchPreferences({ [key]: value });
      me.set(next);
    } catch {
      // Silent: the chip snaps back because the cache was not written, which
      // is the honest signal that nothing changed.
    } finally {
      setBusy(false);
    }
  };

  const confirmSignOut = () => {
    Alert.alert('Sign out?', 'Your locker stays on the server. The copy on this phone is cleared.',
      [{ text: 'Cancel', style: 'cancel' },
       { text: 'Sign out', style: 'destructive',
         onPress: async () => { await signOut(); onSignedOut(); } }]);
  };

  if (me.loading) return <Loading />;

  return (
    <Screen>
      <H>Profile</H>
      {me.stale && <Banner text="Saved copy — reconnecting." />}

      <Card style={{ gap: S[1] }}>
        <Label>Account</Label>
        <Row label="Email" value={me.data?.profile?.email ?? getEmail() ?? '—'} />
        <Row label="Name" value={me.data?.profile?.name ?? 'Not set'} />
      </Card>

      <Card style={{ gap: S[3] }}>
        <Label>Units</Label>
        <View style={{ gap: S[2] }}>
          <Muted>Distance</Muted>
          <View style={{ flexDirection: 'row', gap: S[2] }}>
            {(['km', 'mi'] as const).map(u => (
              <Chip key={u} label={u} selected={prefs?.distance_unit === u}
                    onPress={() => !busy && setUnit('distance_unit', u)} />
            ))}
          </View>
        </View>
        <View style={{ gap: S[2] }}>
          <Muted>Weight</Muted>
          <View style={{ flexDirection: 'row', gap: S[2] }}>
            {(['g', 'oz'] as const).map(u => (
              <Chip key={u} label={u} selected={prefs?.weight_unit === u}
                    onPress={() => !busy && setUnit('weight_unit', u)} />
            ))}
          </View>
        </View>
      </Card>

      <NotificationsCard />

      <Card style={{ gap: S[2] }}>
        <Label>Appearance</Label>
        <Row label="Theme" value={`Following your device · ${mode}`} />
        <Muted>
          An in-app override is a Phase 6 preference. Both palettes already
          exist, so adding it is one setting rather than a redesign.
        </Muted>
      </Card>

      <Card style={{ gap: S[1] }}>
        <Label>About</Label>
        <Row label="Version" value={APP_VERSION || '—'} />
        <Row label="Phase" value="6 — Polish" />
        <Row label="Activity" value="Trail running" />
      </Card>

      <Btn kind="quiet" label="Sign out" tone={P.danger} onPress={confirmSignOut} />
    </Screen>
  );
}


/**
 * The notification switch (§21).
 *
 * OFF UNTIL SOMEBODY ASKS. The system permission prompt appears when this is
 * turned on, not at launch — an app that asks before it has done anything gets
 * "Don't Allow", and iOS never asks again. By the time a runner comes here they
 * know what the app is for.
 *
 * What it can and cannot send is stated plainly rather than implied. Two of
 * §21's five kinds are missing for structural reasons, and a settings screen
 * that quietly omits them leaves someone waiting for a weather alert that is
 * never coming.
 */
function NotificationsCard() {
  const { P } = useTheme();
  const [on, setOn] = useState(false);
  const [busy, setBusy] = useState(false);
  const [note, setNote] = useState<string | null>(null);
  const [status, setStatus] = useState<string>('');
  const [last, setLast] = useState<SyncResult | null>(null);

  // READ THE OS, not just our own preference. The two disagree the moment
  // somebody denies the app in iOS Settings, and without this the card keeps
  // saying "on" over a phone that will never ring.
  React.useEffect(() => {
    notificationsEnabled().then(setOn);
    permissionStatus().then(setStatus);
    lastSync().then(setLast);
  }, []);

  const toggle = async (next: boolean) => {
    setBusy(true);
    setNote(null);
    try {
      if (!next) {
        await disableNotifications();
        setOn(false);
        return;
      }
      const result = await enableNotifications();
      if (result.reason === 'denied') {
        setOn(false);
        setNote('iOS is blocking notifications for this app. Settings → '
                + 'Voyage Outdoor → Notifications.');
      } else if (result.reason === 'offline') {
        setOn(true);
        setNote('On — but the plan could not be fetched just now. It will '
                + 'schedule next time you have signal.');
      } else if (result.reason === 'error') {
        setOn(true);
        setNote(`On, but nothing could be scheduled: ${result.detail}`);
      } else {
        setOn(true);
        setNote(result.scheduled
          ? `On. ${result.scheduled} reminder(s) scheduled.`
          : 'On. Nothing to remind you about yet — which usually means '
            + 'everything is packed.');
      }
      setLast(await lastSync());
      setStatus(await permissionStatus());
    } finally {
      setBusy(false);
    }
  };

  return (
    <Card style={{ gap: S[3] }}>
      <Label>Notifications</Label>
      <Toggle label="Packing and maintenance reminders" value={on}
              onChange={v => !busy && toggle(v)} />
      <Muted>
        A nudge a week, two days and one day before an adventure — and one the
        evening before if a critical item is still unverified. It stops the
        moment your pack is finished.
      </Muted>
      {/* Said out loud. Two of the five kinds §21 lists are not here, and
          leaving that to be discovered is how somebody waits for a weather
          alert that was never going to arrive. */}
      <Muted>
        Weather-change and new-release alerts are not included yet: the first
        needs a scheduler on the server, the second needs a product catalog.
      </Muted>
      {!!note && <Text style={[T.caption, { color: P.textSec }]}>{note}</Text>}

      {/* THE STATE, not the intention. A card that reports only its own switch
          position cannot explain a phone that never rings — and "permission:
          blocked in iOS Settings" is the answer to the only question somebody
          in that situation is asking. */}
      <Row label="iOS permission" value={status || '…'} />
      {!!last && (
        <Row label="Last check"
             value={last.reason
               ? `${last.reason}${last.detail ? ` — ${last.detail}` : ''}`
               : `${last.scheduled} scheduled`} />
      )}
    </Card>
  );
}
