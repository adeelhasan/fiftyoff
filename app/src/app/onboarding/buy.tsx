// Onboarding 2: what you buy. Shelves to put first on Today, and the condition you're happy with (D74, option B).
import { router, useLocalSearchParams } from 'expo-router';
import { Text, View } from 'react-native';

import { StepFrame } from '@/components/Onboarding';
import { Loading, PickChip, Segments } from '@/components/ui';
import { api } from '@/lib/api';
import { COND_OPTIONS } from '@/lib/format';
import { usePrefs } from '@/lib/prefs';
import { C, T } from '@/lib/tokens';
import { useApi } from '@/lib/useApi';

export default function WhatYouBuy() {
  const { edit } = useLocalSearchParams<{ edit?: string }>();
  const { prefs, set } = usePrefs();
  const { data } = useApi('today', api.today);

  // Today's shelves (every front shelf with live deals), grouped by aisle in the order they come.
  const groups = new Map<string, { id: string; name: string; live: number }[]>();
  for (const s of data?.shelves ?? []) {
    const g = groups.get(s.aisle_name) ?? [];
    g.push({ id: s.id, name: s.name, live: s.live });
    groups.set(s.aisle_name, g);
  }
  const toggle = (id: string) =>
    set({ shelves: prefs.shelves.includes(id) ? prefs.shelves.filter((x) => x !== id) : [...prefs.shelves, id] });

  return (
    <StepFrame
      step={2}
      edit={!!edit}
      title="What do you buy?"
      lead="We'll put these shelves first on Today. Pick as many as you like."
      next={() => router.push('/onboarding/sizes')}>
      {data ? null : <Loading />}
      {[...groups.entries()].map(([aisle, shelves]) => (
        <View key={aisle} style={{ gap: 8 }}>
          <Text style={T.label}>{aisle}</Text>
          <View style={{ flexDirection: 'row', flexWrap: 'wrap', gap: 8 }}>
            {shelves.map((s) => (
              <PickChip key={s.id} label={s.name} on={prefs.shelves.includes(s.id)} onPress={() => toggle(s.id)} />
            ))}
          </View>
        </View>
      ))}
      <View style={{ gap: 8, borderTopWidth: 1, borderStyle: 'dashed', borderColor: C.rule, paddingTop: 14 }}>
        <Text style={T.label}>Condition</Text>
        <Segments options={COND_OPTIONS} isOn={(id) => prefs.cond === id} onPick={(cond) => set({ cond })} />
        <Text style={T.small}>{COND_OPTIONS.find((c) => c.id === prefs.cond)?.hint} Every unit is graded by Amazon.</Text>
      </View>
    </StepFrame>
  );
}
