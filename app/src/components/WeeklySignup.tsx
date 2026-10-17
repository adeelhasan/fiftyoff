// The free weekly email sign-up (D73, D74): onboarding step 4, the alert sheet, the Alerts tab. Email only, no account.
import { useState } from 'react';
import { Linking, Text, TextInput, View } from 'react-native';

import { api } from '@/lib/api';
import { SITE } from '@/lib/config';
import { usePrefs } from '@/lib/prefs';
import { C, F, T } from '@/lib/tokens';

import { Button } from './ui';

const EMAIL = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

export function WeeklySignup({ onDone, cta = "Send me the week's best" }: { onDone?: () => void; cta?: string }) {
  const { prefs, set } = usePrefs();
  const [email, setEmail] = useState(prefs.weekly?.email ?? '');
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState('');
  const ok = EMAIL.test(email.trim());

  const submit = async () => {
    setBusy(true);
    setErr('');
    try {
      const state = await api.weekly(email.trim().toLowerCase());
      set({ weekly: { email: email.trim().toLowerCase(), state } });
      onDone?.();
    } catch {
      setErr("That didn't go through. Try again in a moment.");
    } finally {
      setBusy(false);
    }
  };

  return (
    <View style={{ gap: 10 }}>
      <Text nativeID="weekly-email" style={T.bodyStrong}>
        Email
      </Text>
      <TextInput
        accessibilityLabelledBy="weekly-email"
        value={email}
        onChangeText={setEmail}
        placeholder="you@example.com"
        placeholderTextColor={C.ink2}
        autoCapitalize="none"
        autoComplete="email"
        keyboardType="email-address"
        textContentType="emailAddress"
        returnKeyType="send"
        onSubmitEditing={() => ok && submit()}
        style={{
          height: 48,
          borderWidth: 1.5,
          borderColor: C.rule,
          borderRadius: 2,
          backgroundColor: C.slip,
          paddingHorizontal: 12,
          fontFamily: F.text,
          fontSize: 16,
          color: C.ink,
        }}
      />
      {err ? <Text style={[T.small, { color: C.warnInk }]}>{err}</Text> : null}
      <Button label={busy ? 'Sending…' : cta} onPress={submit} disabled={!ok || busy} />
      <Text style={T.small}>
        One email a week; stop it from any email. See our{' '}
        <Text style={{ color: C.stamp }} onPress={() => Linking.openURL(`${SITE}/privacy/`)}>
          Privacy policy
        </Text>
        .
      </Text>
    </View>
  );
}

/** What we tell someone after they signed up (honest about the stub). */
export function weeklyStatus(state: 'sent' | 'saved'): string {
  return state === 'sent'
    ? 'Check your inbox: one tap on the link confirms it.'
    : "Saved on this phone. We'll email you a link to confirm when the weekly email starts.";
}
