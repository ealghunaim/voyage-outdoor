import React, { useState } from 'react';
import { Alert, View } from 'react-native';

import { Me, getMe, patchPreferences } from '../api';
import { getEmail, signOut } from '../auth';
import { useCached } from '../cache';
import { Banner, Btn, Card, Chip, H, Label, Loading, Muted, Row, Screen } from '../components/ui';
import { APP_VERSION } from '../config';
import { S, useTheme } from '../theme';

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
        <Row label="Phase" value="1 — Foundation" />
        <Row label="Activity" value="Trail running" />
      </Card>

      <Btn kind="quiet" label="Sign out" tone={P.danger} onPress={confirmSignOut} />
    </Screen>
  );
}
