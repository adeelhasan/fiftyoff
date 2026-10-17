// Alerts (D73): free = the week's best by email; Head start = alerts for your own words, by email and push.
import { router } from 'expo-router';
import { useState } from 'react';
import { ScrollView, Text, View } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';

import { HeadStartInfo, Toggle } from '@/components/alerts';
import { WeeklySignup, weeklyStatus } from '@/components/WeeklySignup';
import { Button, TextLink, s } from '@/components/ui';
import { usePrefs } from '@/lib/prefs';
import { KEYWORD_LIMIT, useSession } from '@/lib/session';
import { C, F, GUTTER, T } from '@/lib/tokens';

export default function Alerts() {
  const { session } = useSession();
  return (
    <SafeAreaView style={s.screen} edges={['top']}>
      <ScrollView contentContainerStyle={{ padding: GUTTER, paddingTop: 8, gap: 18, paddingBottom: 32 }}>
        <View style={{ gap: 6 }}>
          <Text style={T.title}>Alerts</Text>
          <Text style={T.label}>
            {session.tier === 'plus' ? `${session.keywords.length} of ${KEYWORD_LIMIT} · Head start` : 'Free'}
          </Text>
        </View>
        {session.tier === 'plus' ? <HeadStart /> : <Free />}
      </ScrollView>
    </SafeAreaView>
  );
}

function Free() {
  const { prefs, set } = usePrefs();
  return (
    <>
      <View style={{ backgroundColor: C.slip, padding: 16, gap: 12 }}>
        <Text style={T.h3}>The week's best</Text>
        <Text style={T.small}>One email a week: the best deals we found, and which ones already sold.</Text>
        {prefs.weekly ? (
          <>
            <Text style={T.bodyStrong}>{prefs.weekly.email}</Text>
            <Text style={T.small}>{weeklyStatus(prefs.weekly.state)}</Text>
            <TextLink label="Stop the weekly email" onPress={() => set({ weekly: null })} style={{ color: C.ink2 }} />
          </>
        ) : (
          <WeeklySignup />
        )}
      </View>
      <HeadStartInfo />
      <Button kind="outline" label="Already on Head start? Sign in" onPress={() => router.push('/sign-in')} />
    </>
  );
}

function HeadStart() {
  const { session } = useSession();
  const [push, setPush] = useState(true);
  const [email, setEmail] = useState(true);
  return (
    <>
      {session.stub ? <Text style={[T.small, { color: C.warnInk }]}>Preview: sample alerts, not saved.</Text> : null}
      {session.keywords.map((k) => (
        <View key={k.id} style={{ backgroundColor: C.slip, paddingHorizontal: 16, paddingTop: 12, gap: 6 }}>
          <View style={{ flexDirection: 'row', justifyContent: 'space-between', alignItems: 'baseline' }}>
            <Text style={{ fontFamily: F.textBold, fontSize: 18, color: C.ink }}>"{k.word}"</Text>
            <Text style={T.label}>{k.sentThisWeek ? `${k.sentThisWeek} this week` : 'None yet'}</Text>
          </View>
          {k.last ? <Text style={T.small}>Last: {k.last}</Text> : null}
          <View style={{ flexDirection: 'row', gap: 18, borderTopWidth: 1, borderStyle: 'dashed', borderColor: C.rule }}>
            <TextLink label="Edit" onPress={() => router.push({ pathname: '/alert-sheet', params: { kw: k.word } })} />
            <TextLink label="Stop" onPress={() => {}} style={{ color: C.ink2 }} />
          </View>
        </View>
      ))}
      <Button kind="outline" label="+ Add words" onPress={() => router.push('/alert-sheet')} />
      <View style={{ backgroundColor: C.slip }}>
        <Text style={[T.label, { padding: 16, paddingBottom: 4 }]}>How we tell you</Text>
        <Toggle label="Push on this iPhone" value={push} onChange={setPush} />
        <Toggle label="Email" hint={session.email ?? ''} value={email} onChange={setEmail} />
      </View>
    </>
  );
}
