// The one tab that exists in the navigation and not yet in the product.
//
// It is here rather than hidden because §18 fixes the five tabs, and a
// navigation shape that changes between phases retrains the user twice. What
// they must not do is pretend: each one says what it will hold and which phase
// builds it, which is more useful than a spinner that never resolves.

import React from 'react';
import { Text, View } from 'react-native';

import { Card, Label, Screen } from '../components/ui';
import { S, T, useTheme } from '../theme';

function Soon({ title, body, phase }: { title: string; body: string; phase: string }) {
  const { P } = useTheme();
  return (
    <Screen>
      <View style={{ paddingTop: S[6], gap: S[2] }}>
        <Text style={[T.display, { color: P.textPri }]}>{title}</Text>
      </View>
      <Card style={{ gap: S[3] }}>
        <Label>{phase}</Label>
        <Text style={[T.body, { color: P.textSec }]}>{body}</Text>
      </Card>
    </Screen>
  );
}

export function Discover() {
  return (
    <Soon
      title="Discover"
      phase="Phase 5"
      body="Product discovery needs a product database, and sourcing one is a research spike rather than an assumed dependency. Until then your locker is filled by hand, which is the honest state — an empty feed dressed up as a full one would be worse."
    />
  );
}
