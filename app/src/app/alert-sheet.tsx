// "Tell me when one lands" (D73): free gets the weekly email; Head start adds an alert for the word.
import { router, useLocalSearchParams } from 'expo-router';
import { useState } from 'react';
import { ScrollView, Text, TextInput, View } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';

import { HeadStartInfo, Toggle } from '@/components/alerts';
import { WeeklySignup, weeklyStatus } from '@/components/WeeklySignup';
import { Button, TextLink } from '@/components/ui';
import { usePrefs } from '@/lib/prefs';
import { KEYWORD_LIMIT, useSession } from '@/lib/session';
import { C, F, GUTTER, T } from '@/lib/tokens';

export default function AlertSheet() {
  const { kw = '' } = useLocalSearchParams<{ kw?: string }>();
  const { session } = useSession();
  return (
    <SafeAreaView style={{ flex: 1, backgroundColor: C.slip }} edges={['bottom']}>
      <ScrollView contentContainerStyle={{ padding: GUTTER + 4, gap: 16 }} keyboardShouldPersistTaps="handled">
        <View style={{ flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center' }}>
          <Text style={T.label}>{session.tier === 'plus' ? 'Head start' : kw ? `"${kw}"` : 'Alerts'}</Text>
          <TextLink label="Close" onPress={() => router.back()} />
        </View>
        {session.tier === 'plus' ? <Plus initial={kw} /> : <Free kw={kw} />}
      </ScrollView>
    </SafeAreaView>
  );
}

function Free({ kw }: { kw: string }) {
  const { prefs } = usePrefs();
  return (
    <>
      <Text style={[T.title, { fontSize: 36, lineHeight: 41 }]}>The week's best, by email</Text>
      <Text style={T.body}>Free: one email a week with the best deals we found, live ones first, and the ones that already sold.</Text>
      {prefs.weekly ? (
        <View style={{ backgroundColor: C.goodTint, borderWidth: 1.5, borderColor: C.good, padding: 14, gap: 4 }}>
          <Text style={[T.bodyStrong, { color: C.goodInk }]}>✓ {prefs.weekly.email}</Text>
          <Text style={[T.small, { color: C.goodInk }]}>{weeklyStatus(prefs.weekly.state)}</Text>
        </View>
      ) : (
        <WeeklySignup />
      )}
      <View style={{ borderTopWidth: 1, borderStyle: 'dashed', borderColor: C.rule, paddingTop: 14, gap: 10 }}>
        {kw ? <Text style={T.bodyStrong}>Want "{kw}" the moment it lands?</Text> : null}
        <HeadStartInfo />
        <TextLink label="Already on Head start? Sign in" onPress={() => router.push('/sign-in')} />
      </View>
    </>
  );
}

function Plus({ initial }: { initial: string }) {
  const { session } = useSession();
  const [word, setWord] = useState(initial);
  const [push, setPush] = useState(true);
  const [email, setEmail] = useState(true);
  return (
    <>
      <Text style={[T.title, { fontSize: 36, lineHeight: 41 }]}>Tell me when one lands</Text>
      <View style={{ gap: 6 }}>
        <Text nativeID="kw-label" style={T.bodyStrong}>
          Words to look for
        </Text>
        <TextInput
          accessibilityLabelledBy="kw-label"
          value={word}
          onChangeText={setWord}
          autoCapitalize="none"
          autoCorrect={false}
          style={{ height: 48, borderWidth: 1.5, borderColor: C.ink, borderRadius: 2, paddingHorizontal: 12, fontFamily: F.text, fontSize: 16, color: C.ink }}
        />
        <Text style={T.small}>Matched like search: a title or brand with a word starting "{word || '…'}".</Text>
      </View>
      <View style={{ backgroundColor: C.slipMuted }}>
        <Toggle label="Push on this iPhone" value={push} onChange={setPush} />
        <Toggle label="Email" hint={session.email ?? ''} value={email} onChange={setEmail} />
      </View>
      <Button label="Start this alert" disabled={!word.trim() || session.stub} onPress={() => router.back()} />
      <Text style={[T.small, { textAlign: 'center' }]}>
        {session.stub
          ? 'Preview: saving alerts arrives with sign-in.'
          : `As soon as we see one. Keeps going until you stop it. ${session.keywords.length} of ${KEYWORD_LIMIT} alerts in use.`}
      </Text>
    </>
  );
}
