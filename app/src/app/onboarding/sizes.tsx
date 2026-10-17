// Onboarding 3: your sizes (D74, D75). Who you shop for (one or both) decides which size groups show; every group
// takes several picks. The values come from /api/v1/sizes, so each one has deals behind it.
import { router, useLocalSearchParams } from 'expo-router';
import { Text, View } from 'react-native';

import { StepFrame } from '@/components/Onboarding';
import { Loading, PickChip, Segments, TextLink } from '@/components/ui';
import { api } from '@/lib/api';
import { NO_SIZES, usePrefs } from '@/lib/prefs';
import { T } from '@/lib/tokens';
import type { MySizes } from '@/lib/types';
import { useApi } from '@/lib/useApi';

type Who = 'women' | 'men';

/** Which picker groups each shopper sees. Letter sizes carry no wearer (D59), so both see them. */
const GROUPS: Record<string, { name: string; who: Who[] }> = {
  letter: { name: 'Tops and dresses · S, M, L', who: ['women', 'men'] },
  num: { name: "Women's pants and dresses · numbered", who: ['women'] },
  'shoe-women': { name: "Women's shoes · US", who: ['women'] },
  waist: { name: "Men's pants · waist", who: ['men'] },
  length: { name: "Men's pants · inseam", who: ['men'] },
  'shoe-men': { name: "Men's shoes · US", who: ['men'] },
};

/** A picker group + value -> where it lives in MySizes ("shoe-men", "10.5" -> shoe "men-10.5"), as web/lib/mySizes.ts. */
function slot(group: string, v: string): [keyof MySizes, string] {
  return group.startsWith('shoe-') ? ['shoe', `${group.slice(5)}-${v}`] : [group as keyof MySizes, v];
}

export default function YourSizes() {
  const { edit } = useLocalSearchParams<{ edit?: string }>();
  const { prefs, set } = usePrefs();
  const { data } = useApi('sizes', api.sizes);
  const who = prefs.shopFor;
  const finishStep = () => (edit ? router.back() : router.push('/onboarding/weekly'));

  const pickWho = (w: Who) => {
    const next = { ...who, [w]: !who[w] };
    // Turning a shopper off drops the sizes only they would use.
    const sizes: MySizes = { ...prefs.sizes };
    if (!next.women) {
      sizes.num = [];
      sizes.shoe = sizes.shoe.filter((x) => !x.startsWith('women-'));
    }
    if (!next.men) {
      sizes.waist = [];
      sizes.length = [];
      sizes.shoe = sizes.shoe.filter((x) => !x.startsWith('men-'));
    }
    if (!next.women && !next.men) sizes.letter = [];
    set({ shopFor: next, sizes });
  };

  const toggle = (group: string, v: string) => {
    const [k, val] = slot(group, v);
    const cur = prefs.sizes[k];
    set({ sizes: { ...prefs.sizes, [k]: cur.includes(val) ? cur.filter((x) => x !== val) : [...cur, val] } });
  };

  const shown = (data?.groups ?? []).filter((g) => GROUPS[g.id]?.who.some((w) => who[w]));

  return (
    <StepFrame
      step={3}
      edit={!!edit}
      title="Your sizes"
      lead="Some of our best deals are in clothing and shoes. Tell us your sizes and we'll show the ones that fit."
      next={finishStep}
      footer={
        edit ? (
          <TextLink label="Clear my sizes" onPress={() => set({ sizes: NO_SIZES, shopFor: { women: false, men: false } })} style={{ textAlign: 'center' }} />
        ) : (
          <TextLink label="I don't buy clothes here" onPress={() => router.push('/onboarding/weekly')} style={{ textAlign: 'center', color: '#222326' }} />
        )
      }>
      <View style={{ gap: 8 }}>
        <Text style={T.label}>I shop for · pick one or both</Text>
        <Segments<Who>
          options={[
            { id: 'women', label: `${who.women ? '✓ ' : ''}Women's` },
            { id: 'men', label: `${who.men ? '✓ ' : ''}Men's` },
          ]}
          isOn={(w) => who[w]}
          onPick={pickWho}
        />
      </View>
      {!data && (who.women || who.men) ? <Loading /> : null}
      {shown.map((g) => (
        <View key={g.id} style={{ gap: 8 }}>
          <Text style={T.label}>{GROUPS[g.id].name}</Text>
          <View style={{ flexDirection: 'row', flexWrap: 'wrap', gap: 6 }}>
            {g.values.map(({ v }) => {
              const [k, val] = slot(g.id, v);
              return <PickChip key={v} label={v} on={prefs.sizes[k].includes(val)} onPress={() => toggle(g.id, v)} />;
            })}
          </View>
        </View>
      ))}
      {who.women || who.men ? (
        <Text style={T.small}>Pick as many as you like: between sizes, or shopping for someone else too. Kept on this phone only.</Text>
      ) : null}
    </StepFrame>
  );
}
