// Sign in with an emailed code (D74: Clerk, email code only). The code step is drawn; Clerk fills it in M3.
import { router } from 'expo-router';
import { useState } from 'react';
import { ScrollView, Text, TextInput, View } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';

import { Button, TextLink } from '@/components/ui';
import { useSession } from '@/lib/session';
import { C, F, GUTTER, T } from '@/lib/tokens';

const input = {
  height: 48,
  borderWidth: 1.5,
  borderColor: C.ink,
  borderRadius: 2,
  backgroundColor: C.slip,
  paddingHorizontal: 12,
  fontFamily: F.text,
  fontSize: 16,
  color: C.ink,
} as const;

export default function SignIn() {
  const { session } = useSession();
  const [email, setEmail] = useState('');
  const [step, setStep] = useState<'email' | 'code'>('email');
  const [code, setCode] = useState('');

  return (
    <SafeAreaView style={{ flex: 1, backgroundColor: C.ground }} edges={['bottom']}>
      <ScrollView contentContainerStyle={{ padding: GUTTER + 4, gap: 18 }} keyboardShouldPersistTaps="handled">
        <View style={{ flexDirection: 'row', justifyContent: 'flex-end' }}>
          <TextLink label="Close" onPress={() => router.back()} />
        </View>
        <Text style={T.title}>Sign in</Text>
        {step === 'email' ? (
          <>
            <Text style={[T.body, { color: C.ink2 }]}>No password. We email you a 6-digit code.</Text>
            <View style={{ gap: 6 }}>
              <Text nativeID="si-email" style={T.bodyStrong}>
                Email
              </Text>
              <TextInput
                accessibilityLabelledBy="si-email"
                value={email}
                onChangeText={setEmail}
                autoCapitalize="none"
                autoComplete="email"
                keyboardType="email-address"
                textContentType="emailAddress"
                style={input}
              />
            </View>
            <Button label="Email me a code" disabled={!email.includes('@')} onPress={() => setStep('code')} />
          </>
        ) : (
          <>
            <Text style={[T.body, { color: C.ink2 }]}>
              We sent a code to <Text style={{ fontFamily: F.textSemi, color: C.ink }}>{email}</Text>. It works for 10 minutes.
            </Text>
            <View style={{ gap: 6 }}>
              <Text nativeID="si-code" style={T.bodyStrong}>
                Code
              </Text>
              <TextInput
                accessibilityLabelledBy="si-code"
                value={code}
                onChangeText={(v) => setCode(v.replace(/\D/g, '').slice(0, 6))}
                keyboardType="number-pad"
                textContentType="oneTimeCode"
                autoComplete="one-time-code"
                style={[input, { letterSpacing: 6, fontFamily: F.mono, fontSize: 22 }]}
              />
            </View>
            <Button label="Sign in" disabled={code.length < 6 || session.stub} onPress={() => router.back()} />
            <TextLink label="Use a different address" onPress={() => setStep('email')} />
          </>
        )}
        {session.stub ? (
          <Text style={[T.small, { color: C.warnInk }]}>
            Sign-in opens with Head start. The week's best needs no account: sign up from the Alerts tab.
          </Text>
        ) : null}
        <Text style={T.small}>Signing in brings your Head start alerts and push to this iPhone. Your picks here stay as they are.</Text>
      </ScrollView>
    </SafeAreaView>
  );
}
