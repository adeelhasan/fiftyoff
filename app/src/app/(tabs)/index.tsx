// Today (D62, D63, D65, D66): tagline and counts, Worth a look, the person's shelves first, every other shelf,
// Recently gone last.
import { router } from 'expo-router';
import { SymbolView } from 'expo-symbols';
import { Pressable, RefreshControl, ScrollView, Text, View } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';

import { DealCard, GoneMini } from '@/components/DealCard';
import { ErrorState, KeepaLine, Loading, SectionHead, TextLink, Wordmark, s } from '@/components/ui';
import { api } from '@/lib/api';
import { ago, condAllows, count, minutesSince } from '@/lib/format';
import { anySizes, usePrefs } from '@/lib/prefs';
import { C, GUTTER, T } from '@/lib/tokens';
import type { Deal, Shelf } from '@/lib/types';
import { useApi } from '@/lib/useApi';

const CARD_W = 160;

export default function Today() {
  const { prefs } = usePrefs();
  const { data, error, loading, reload } = useApi('today', api.today);
  const sized = useApi(anySizes(prefs.sizes) ? `sized:${JSON.stringify(prefs.sizes)}` : null, () => api.sized(prefs.sizes));
  const keep = (d: Deal) => condAllows(prefs.cond, d.condition);

  const picked = new Set(prefs.shelves);
  const rows = data?.shelves ?? [];
  const mine = prefs.shelves.map((id) => rows.find((r) => r.id === id)).filter((r): r is (typeof rows)[number] => !!r);
  const rest = rows.filter((r) => !picked.has(r.id));

  return (
    <SafeAreaView style={s.screen} edges={['top']}>
      <ScrollView
        contentContainerStyle={{ paddingBottom: 24, gap: 34 }}
        refreshControl={<RefreshControl refreshing={loading && !!data} onRefresh={reload} tintColor={C.stamp} />}>
        <View style={{ paddingHorizontal: GUTTER, paddingTop: 8, gap: 14 }}>
          <View style={{ flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between' }}>
            <Wordmark size={34} />
            <Pressable
              accessibilityRole="button"
              accessibilityLabel="Search"
              onPress={() => router.push('/search')}
              style={{ width: 44, height: 44, alignItems: 'center', justifyContent: 'center' }}>
              <SymbolView name={{ ios: 'magnifyingglass', android: 'search', web: 'search' }} size={24} tintColor={C.ink} />
            </Pressable>
          </View>
          <View style={{ gap: 6 }}>
            <Text style={[T.title, { fontSize: 40, lineHeight: 46 }]}>Deals like no other.</Text>
            <Text style={T.small}>Amazon Resale, open-box and used, at half off or better. Sold and shipped by Amazon.</Text>
          </View>
          {data ? (
            <View>
              <TextLink
                label={`${count(data.count)} DEALS ON ${data.shelf_count} SHELVES · SEE ALL →`}
                onPress={() => router.navigate('/deals')}
                style={[T.label, { color: C.stamp, fontSize: 13 }]}
              />
              <TextLink
                label={
                  sized.data ? `${count(sized.data.count)} IN YOUR SIZES · CLOTHES & SHOES →` : 'CLOTHES & SHOES IN YOUR SIZES →'
                }
                onPress={() => router.push('/sizes')}
                style={[T.label, { color: C.stamp, fontSize: 13 }]}
              />
            </View>
          ) : null}
        </View>

        {error && !data ? <ErrorState onRetry={reload} /> : null}
        {!data && !error ? <Loading /> : null}

        {data ? (
          <>
            {data.featured.filter(keep).length ? (
              <View style={{ gap: 12 }}>
                <SectionHead title="Worth a look" sub="Seen in the last 24 h" />
                <CardRow deals={data.featured.filter(keep)} surface="featured" withShelf={rows} />
              </View>
            ) : null}

            {mine.map((r, i) => (
              <ShelfRow
                key={r.id}
                shelf={r}
                deals={r.deals.filter(keep)}
                label={i === 0 ? 'Your shelves' : undefined}
                onEdit={i === 0 ? () => router.push({ pathname: '/onboarding/buy', params: { edit: '1' } }) : undefined}
              />
            ))}
            {rest.map((r, i) => (
              <ShelfRow key={r.id} shelf={r} deals={r.deals.filter(keep)} label={i === 0 ? 'Every shelf' : undefined} />
            ))}

            {data.gone.length ? (
              <View style={{ gap: 12 }}>
                <SectionHead title="Recently gone" />
                <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={{ paddingHorizontal: GUTTER, gap: 10 }}>
                  {data.gone.map((g) => (
                    <GoneMini key={g.id} gone={g} line={`${g.pct_off}% off · ${ago(minutesSince(g.gone_at))}`} />
                  ))}
                </ScrollView>
              </View>
            ) : null}
            <KeepaLine style={{ paddingVertical: 0 }} />
          </>
        ) : null}
      </ScrollView>
    </SafeAreaView>
  );
}

function CardRow({ deals, surface, withShelf }: { deals: Deal[]; surface: string; withShelf?: (Shelf & { deals: Deal[] })[] }) {
  const names = new Map((withShelf ?? []).map((r) => [r.id, r.name]));
  return (
    <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={{ paddingHorizontal: GUTTER, gap: 12 }}>
      {deals.map((d) => (
        <DealCard key={d.id} deal={d} surface={surface} width={CARD_W} shelf={withShelf ? names.get(d.shelf) : undefined} />
      ))}
    </ScrollView>
  );
}

function ShelfRow({
  shelf,
  deals,
  label,
  onEdit,
}: {
  shelf: Shelf;
  deals: Deal[];
  label?: string;
  onEdit?: () => void;
}) {
  if (!deals.length) return null;
  return (
    <View style={{ gap: 12 }}>
      {label ? (
        <View style={{ paddingHorizontal: GUTTER, flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center' }}>
          <Text style={T.label}>{label}</Text>
          {onEdit ? <TextLink label="Edit" onPress={onEdit} /> : null}
        </View>
      ) : null}
      <View style={{ paddingHorizontal: GUTTER, flexDirection: 'row', alignItems: 'flex-end', justifyContent: 'space-between' }}>
        <View style={{ flexShrink: 1, gap: 4 }}>
          <Text style={[T.h2, { fontSize: 28 }]}>{shelf.name}</Text>
          <Text style={T.label}>{shelf.live} live</Text>
        </View>
        <TextLink label="See all" onPress={() => router.push({ pathname: '/shelf/[id]', params: { id: shelf.id } })} />
      </View>
      <CardRow deals={deals} surface="shelf" />
    </View>
  );
}
