import React, { useState } from 'react';
import {
  ActivityIndicator, Pressable, ScrollView, Switch, Text, TextInput, View,
  ViewStyle,
} from 'react-native';

import { RA, S, T, TAP, tint, useTheme } from '../theme';

/** Every interactive control routes through here or meets TAP itself.
 *  §19 asks for controls usable with light gloves; 48 is the floor. */
export function Btn({ label, onPress, kind = 'primary', disabled, busy, tone }: {
  label: string;
  onPress: () => void;
  kind?: 'primary' | 'ghost' | 'quiet';
  disabled?: boolean;
  busy?: boolean;
  tone?: string;
}) {
  const { P } = useTheme();
  const accent = tone ?? P.brand;
  const bg = kind === 'primary' ? accent
    : kind === 'ghost' ? tint(accent, 0.12)
    : 'transparent';
  const fg = kind === 'primary' ? P.onBrand : accent;
  const off = disabled || busy;
  return (
    <Pressable
      onPress={onPress}
      disabled={off}
      accessibilityRole="button"
      accessibilityState={{ disabled: !!off, busy: !!busy }}
      style={({ pressed }) => [{
        minHeight: TAP,
        borderRadius: RA.md,
        paddingHorizontal: S[5],
        alignItems: 'center',
        justifyContent: 'center',
        flexDirection: 'row',
        gap: S[2],
        // Disabled goes neutral rather than translucent brand: a faded accent
        // composites into a *different colour*, which reads as a second brand
        // rather than as an inert control.
        backgroundColor: off ? P.sunken : bg,
        borderWidth: kind === 'quiet' ? 1 : 0,
        borderColor: P.hairline,
        opacity: pressed && !off ? 0.85 : 1,
      }]}>
      {busy && <ActivityIndicator size="small" color={off ? P.textMuted : fg} />}
      <Text style={[T.title, { color: off ? P.textMuted : fg }]}>{label}</Text>
    </Pressable>
  );
}

export function Card({ children, style, onPress }: {
  children: React.ReactNode; style?: ViewStyle; onPress?: () => void;
}) {
  const { P, E } = useTheme();
  const body = (
    <View style={[{
      backgroundColor: P.card,
      borderRadius: RA.xl,
      padding: S[5],
      borderWidth: 1,
      borderColor: P.hairline,
    }, E.mid, style]}>
      {children}
    </View>
  );
  if (!onPress) return body;
  return (
    <Pressable onPress={onPress} style={({ pressed }) => ({ opacity: pressed ? 0.9 : 1 })}>
      {body}
    </Pressable>
  );
}

export function Screen({ children, scroll = true, padded = true }: {
  children: React.ReactNode; scroll?: boolean; padded?: boolean;
}) {
  const { P } = useTheme();
  const style = { flex: 1, backgroundColor: P.pageBg };
  const inner = padded ? { padding: S[4], paddingBottom: S[12], gap: S[3] } : undefined;
  if (!scroll) return <View style={[style, inner]}>{children}</View>;
  return (
    <ScrollView style={style} contentContainerStyle={inner}
                keyboardShouldPersistTaps="handled">
      {children}
    </ScrollView>
  );
}

export function H({ children, level = 1 }: { children: React.ReactNode; level?: 1 | 2 }) {
  const { P } = useTheme();
  return <Text style={[level === 1 ? T.h1 : T.h2, { color: P.textPri }]}>{children}</Text>;
}

export function Label({ children }: { children: React.ReactNode }) {
  const { P } = useTheme();
  return (
    <Text style={[T.label, { color: P.textMuted, textTransform: 'uppercase' }]}>
      {children}
    </Text>
  );
}

export function Muted({ children }: { children: React.ReactNode }) {
  const { P } = useTheme();
  return <Text style={[T.caption, { color: P.textMuted }]}>{children}</Text>;
}

/** A labelled value. The locker is a spec sheet more than it is a feed, so
 *  this is the most-used component in the app. */
export function Row({ label, value, tone }: {
  label: string; value: React.ReactNode; tone?: string;
}) {
  const { P } = useTheme();
  return (
    <View style={{ flexDirection: 'row', justifyContent: 'space-between',
                   alignItems: 'baseline', gap: S[4], paddingVertical: S[1] }}>
      <Text style={[T.caption, { color: P.textMuted, flexShrink: 1 }]}>{label}</Text>
      {typeof value === 'string' || typeof value === 'number'
        ? <Text style={[T.body, { color: tone ?? P.textPri, textAlign: 'right', flexShrink: 1 }]}>
            {value}
          </Text>
        : value}
    </View>
  );
}

export function Pill({ label, tone, filled }: {
  label: string; tone?: string; filled?: boolean;
}) {
  const { P } = useTheme();
  const accent = tone ?? P.textMuted;
  return (
    <View style={{
      paddingHorizontal: S[3], paddingVertical: S[1] + 1, borderRadius: RA.pill,
      backgroundColor: filled ? accent : tint(accent, 0.14),
      alignSelf: 'flex-start',
    }}>
      <Text style={[T.label, { color: filled ? P.onBrand : accent }]}>{label}</Text>
    </View>
  );
}

export function Chip({ label, selected, onPress }: {
  label: string; selected: boolean; onPress: () => void;
}) {
  const { P } = useTheme();
  return (
    <Pressable
      onPress={onPress}
      accessibilityRole="button"
      accessibilityState={{ selected }}
      hitSlop={8}
      style={{
        minHeight: 38, justifyContent: 'center',
        paddingHorizontal: S[4], borderRadius: RA.pill, borderWidth: 1,
        borderColor: selected ? P.brand : P.hairlineStrong,
        backgroundColor: selected ? P.brand : P.card,
      }}>
      <Text style={[T.caption, { color: selected ? P.onBrand : P.textPri }]}>{label}</Text>
    </Pressable>
  );
}

export function Field({ label, value, onChange, placeholder, secure, keyboardType,
                        unit, multiline, autoComplete, textContentType }: {
  label: string;
  value: string;
  onChange: (t: string) => void;
  placeholder?: string;
  secure?: boolean;
  keyboardType?: 'default' | 'email-address' | 'numeric' | 'decimal-pad';
  unit?: string;
  multiline?: boolean;
  autoComplete?: 'email' | 'password' | 'password-new' | 'off';
  textContentType?: 'emailAddress' | 'password' | 'newPassword' | 'none';
}) {
  const { P } = useTheme();
  const [reveal, setReveal] = useState(false);
  const masked = !!secure && !reveal;
  return (
    <View style={{ gap: S[2] }}>
      <View style={{ flexDirection: 'row', justifyContent: 'space-between' }}>
        <Label>{label}</Label>
        {!!unit && <Muted>{unit}</Muted>}
      </View>
      <View style={{ justifyContent: 'center' }}>
        <TextInput
          style={[T.body, {
            backgroundColor: P.sunken,
            borderRadius: RA.md,
            paddingHorizontal: S[4],
            paddingVertical: S[3],
            paddingRight: secure ? 64 : S[4],
            color: P.textPri,
            textAlignVertical: multiline ? 'top' : 'center',
            // TAP is the floor for a single line; a multiline box needs room
            // to look like one before it is typed into.
            minHeight: multiline ? 96 : TAP,
          }]}
          value={value}
          onChangeText={onChange}
          placeholder={placeholder}
          placeholderTextColor={P.textMuted}
          autoCapitalize={keyboardType === 'email-address' ? 'none' : 'sentences'}
          autoCorrect={false}
          secureTextEntry={masked}
          keyboardType={keyboardType}
          multiline={multiline}
          autoComplete={autoComplete}
          textContentType={textContentType}
        />
        {secure && (
          <Pressable
            onPress={() => setReveal(r => !r)}
            hitSlop={12}
            accessibilityRole="button"
            accessibilityLabel={masked ? 'Show password' : 'Hide password'}
            style={{ position: 'absolute', right: S[4] }}>
            <Text style={[T.caption, { color: P.brand }]}>{masked ? 'Show' : 'Hide'}</Text>
          </Pressable>
        )}
      </View>
    </View>
  );
}

export function Toggle({ label, value, onChange }: {
  label: string; value: boolean; onChange: (v: boolean) => void;
}) {
  const { P } = useTheme();
  return (
    <View style={{ flexDirection: 'row', alignItems: 'center',
                   justifyContent: 'space-between', minHeight: TAP }}>
      <Text style={[T.body, { color: P.textPri, flexShrink: 1 }]}>{label}</Text>
      <Switch value={value} onValueChange={onChange}
              trackColor={{ true: P.brand, false: P.hairlineStrong }} />
    </View>
  );
}

/** Loud enough to be read, quiet enough not to be the page.
 *  §9: calm interface — no excessive warning colours. */
export function Banner({ text, tone = 'info' }: {
  text: string; tone?: 'info' | 'warn' | 'error';
}) {
  const { P } = useTheme();
  const accent = tone === 'error' ? P.danger : tone === 'warn' ? P.warningInk : P.brand;
  return (
    <View style={{
      backgroundColor: tint(accent, 0.10), borderRadius: RA.md,
      padding: S[3], borderLeftWidth: 3, borderLeftColor: accent,
    }}>
      <Text style={[T.caption, { color: accent }]}>{text}</Text>
    </View>
  );
}

export function Empty({ title, body, action }: {
  title: string; body: string; action?: React.ReactNode;
}) {
  const { P } = useTheme();
  return (
    <View style={{ alignItems: 'center', gap: S[3], paddingVertical: S[12],
                   paddingHorizontal: S[5] }}>
      <Text style={[T.h2, { color: P.textPri, textAlign: 'center' }]}>{title}</Text>
      <Text style={[T.body, { color: P.textMuted, textAlign: 'center' }]}>{body}</Text>
      {action}
    </View>
  );
}

export function Loading({ label }: { label?: string }) {
  const { P } = useTheme();
  return (
    <View style={{ paddingVertical: S[12], alignItems: 'center', gap: S[3] }}>
      <ActivityIndicator color={P.brand} />
      {!!label && <Muted>{label}</Muted>}
    </View>
  );
}
