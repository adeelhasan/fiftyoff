import Constants from 'expo-constants';
import { router } from 'expo-router';
import { Linking, Pressable, ScrollView, Text, View } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';

import { Button, KeepaLine, Segments, s } from '@/components/ui';
import { SITE } from '@/lib/config';
import { COND_OPTIONS } from '@/lib/format';
import { anySizes, describeSizes, usePrefs } from '@/lib/prefs';
import { useSession, type Tier } from '@/lib/session';
import { useShelves, shelfName } from '@/lib/shelves';
import { C, F, GUTTER, T } from '@/lib/tokens';

export default function Settings() {
  const { prefs, set, reset } = usePrefs();
  const { session, preview, signOut } = useSession();
  const shelves = useShelves();
  const plus = session.tier === 'plus';

  return (
    <SafeAreaView style={s.screen} edges={['top']}>
      <ScrollView contentContainerStyle={{ padding: GUTTER, paddingTop: 8, gap: 18, paddingBottom: 32 }}>
        <Text style={T.title}>Settings</Text>

        <View style={{ backgroundColor: C.slip, padding: 16, gap: 8 }}>
          <View style={{ flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center' }}>
            <Text style={T.label}>Your plan</Text>
            <Text style={[T.label, { backgroundColor: C.stampTint, color: C.stampDeep, paddingHorizontal: 8, paddingVertical: 2 }]}>
              {plus ? 'Head start' : 'Free'}
            </Text>
          </View>
          {plus ? (
            <Text style={T.body}>Alerts for your own words, by email and push, as soon as we see a deal.</Text>
          ) : (
            <>
              <Text style={T.body}>
                {prefs.weekly ? `The week's best, by email, to ${prefs.weekly.email}.` : "The week's best, by email: not signed up."}
              </Text>
              <Text style={T.small}>Head start adds alerts for your own words, by email and push, as soon as we see a deal.</Text>
              {session.tier === 'signed-out' ? (
                <Button kind="outline" label="Already on Head start? Sign in" onPress={() => router.push('/sign-in')} style={{ marginTop: 4 }} />
              ) : null}
            </>
          )}
        </View>

        <Group title="What you see">
          <Row
            label="Shelves first on Today"
            value={prefs.shelves.length ? prefs.shelves.map((id) => shelfName(id, shelves)).join(', ') : 'None'}
            onPress={() => router.push({ pathname: '/onboarding/buy', params: { edit: '1' } })}
          />
          <View style={{ padding: 16, gap: 8, borderTopWidth: 1, borderColor: C.ruleSoft }}>
            <Text style={T.body}>Condition</Text>
            <Segments options={COND_OPTIONS} isOn={(id) => prefs.cond === id} onPick={(cond) => set({ cond })} />
            <Text style={T.small}>{COND_OPTIONS.find((c) => c.id === prefs.cond)?.hint}</Text>
          </View>
          <Row
            label="Sizes"
            value={anySizes(prefs.sizes) ? describeSizes(prefs.sizes) : 'Not set'}
            onPress={() => router.push({ pathname: '/onboarding/sizes', params: { edit: '1' } })}
          />
        </Group>

        <Group title="Account">
          <Row label="Weekly email" value={prefs.weekly?.email ?? 'Not signed up'} onPress={() => router.navigate('/alerts')} />
          {session.tier === 'signed-out' ? (
            <Row label="Sign in" onPress={() => router.push('/sign-in')} />
          ) : (
            <>
              <Row label="Signed in" value={session.email ?? ''} />
              <Row label="Sign out" onPress={signOut} />
              <Row label="Delete my account" onPress={() => {}} danger />
            </>
          )}
        </Group>

        <Group title="About">
          <Row label="How we price" onPress={() => Linking.openURL(`${SITE}/how-we-price/`)} />
          <Row label="Privacy" onPress={() => Linking.openURL(`${SITE}/privacy/`)} />
          <Row label="Contact" onPress={() => Linking.openURL(`${SITE}/contact/`)} />
        </Group>

        {__DEV__ ? (
          <Group title="Development">
            <View style={{ padding: 16, gap: 8 }}>
              <Text style={T.small}>Preview the account states (no accounts exist yet).</Text>
              <Segments<Tier>
                options={[
                  { id: 'signed-out', label: 'Signed out' },
                  { id: 'free', label: 'Free' },
                  { id: 'plus', label: 'Head start' },
                ]}
                isOn={(t) => session.tier === t}
                onPick={preview}
              />
            </View>
            <Row
              label="Start onboarding again"
              onPress={() => {
                reset();
                router.replace('/onboarding');
              }}
            />
          </Group>
        ) : null}

        <Text style={[T.small, { textAlign: 'center' }]}>fiftyOff {Constants.expoConfig?.version ?? ''}</Text>
        <KeepaLine style={{ paddingHorizontal: 0, justifyContent: 'center' }} />
      </ScrollView>
    </SafeAreaView>
  );
}

function Group({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <View style={{ backgroundColor: C.slip }}>
      <Text style={[T.label, { padding: 16, paddingBottom: 4 }]}>{title}</Text>
      {children}
    </View>
  );
}

function Row({ label, value, onPress, danger }: { label: string; value?: string; onPress?: () => void; danger?: boolean }) {
  return (
    <Pressable
      accessibilityRole={onPress ? 'button' : undefined}
      disabled={!onPress}
      onPress={onPress}
      style={({ pressed }) => ({
        minHeight: 48,
        paddingHorizontal: 16,
        paddingVertical: 10,
        borderTopWidth: 1,
        borderColor: C.ruleSoft,
        flexDirection: 'row',
        alignItems: 'center',
        justifyContent: 'space-between',
        gap: 12,
        backgroundColor: pressed ? C.stampTint : 'transparent',
      })}>
      <Text style={[T.body, danger && { color: C.warnInk }]}>{label}</Text>
      <Text style={{ flexShrink: 1, textAlign: 'right', fontFamily: F.text, fontSize: 15, color: C.ink2 }} numberOfLines={2}>
        {value ?? ''}
        {onPress ? ' ›' : ''}
      </Text>
    </Pressable>
  );
}
