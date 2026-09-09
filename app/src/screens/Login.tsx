import React, { useState } from 'react';
import { KeyboardAvoidingView, Platform, Text, View } from 'react-native';

import { requestPasswordReset, signIn, signUp } from '../auth';
import { Banner, Btn, Field, H, Muted, Screen } from '../components/ui';
import { configured } from '../config';
import { S, T, useTheme } from '../theme';

export default function Login({ onDone }: { onDone: () => void }) {
  const { P } = useTheme();
  const [mode, setMode] = useState<'in' | 'up'>('in');
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  const cfg = configured();

  const submit = async () => {
    setError(null);
    setNotice(null);
    setBusy(true);
    try {
      if (mode === 'in') {
        await signIn(email.trim(), password);
        onDone();
      } else {
        const result = await signUp(email.trim(), password);
        if (result === 'authed') onDone();
        else setNotice('Check your inbox to confirm the address, then sign in.');
      }
    } catch (e: any) {
      setError(e?.message ?? 'That did not work.');
    } finally {
      setBusy(false);
    }
  };

  const forgot = async () => {
    if (!email.trim()) { setError('Enter your email first.'); return; }
    try {
      await requestPasswordReset(email.trim(), 'voyageoutdoor://reset');
      // The same message whether or not the address exists. A form that
      // distinguishes them is an account-enumeration oracle.
      setNotice('If that address has an account, a reset link is on its way.');
    } catch (e: any) {
      setError(e?.message ?? 'Could not send that.');
    }
  };

  return (
    <KeyboardAvoidingView style={{ flex: 1 }}
                          behavior={Platform.OS === 'ios' ? 'padding' : undefined}>
      <Screen>
        <View style={{ paddingTop: S[12], gap: S[2] }}>
          <H>Voyage Outdoor</H>
          <Text style={[T.body, { color: P.textSec }]}>
            Tell it what you are doing. It knows what you own.
          </Text>
        </View>

        {!cfg.ok && (
          <Banner tone="error"
                  text={`This build is missing ${cfg.missing.join(', ')} in app.json → extra. It cannot reach anything until those are filled in.`} />
        )}

        <View style={{ gap: S[4], paddingTop: S[6] }}>
          <Field label="Email" value={email} onChange={setEmail}
                 keyboardType="email-address" autoComplete="email"
                 textContentType="emailAddress" placeholder="you@example.com" />
          <Field label="Password" value={password} onChange={setPassword} secure
                 autoComplete={mode === 'in' ? 'password' : 'password-new'}
                 textContentType={mode === 'in' ? 'password' : 'newPassword'}
                 placeholder={mode === 'up' ? 'At least 8 characters' : ''} />

          {!!error && <Banner tone="error" text={error} />}
          {!!notice && <Banner text={notice} />}

          <Btn label={mode === 'in' ? 'Sign in' : 'Create account'}
               onPress={submit} busy={busy}
               disabled={!cfg.ok || !email.trim() || password.length < 6} />

          <Btn kind="quiet"
               label={mode === 'in' ? 'Create an account' : 'I already have an account'}
               onPress={() => { setMode(m => (m === 'in' ? 'up' : 'in')); setError(null); }} />

          {mode === 'in' && (
            <Btn kind="quiet" label="Forgot password" onPress={forgot} />
          )}
        </View>

        <View style={{ paddingTop: S[6] }}>
          <Muted>
            A Voyage Outdoor account is separate from VoyageOS. Linking the two
            is a later decision, not this one.
          </Muted>
        </View>
      </Screen>
    </KeyboardAvoidingView>
  );
}
