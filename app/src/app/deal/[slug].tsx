// The deal page, pushed over the list so back returns to the same spot (D71's reason, native). A bar pinned to the
// bottom always shows the price and the way to Amazon (D65). A unit that went shows "It already went" instead.
import { Image } from 'expo-image';
import { router, useLocalSearchParams } from 'expo-router';
import { SymbolView } from 'expo-symbols';
import { useEffect } from 'react';
import { Linking, Pressable, ScrollView, Share, Text, View } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';

import { DealCard } from '@/components/DealCard';
import { BackLink, Button, Empty, ErrorState, GoneStamp, Grade, KeepaLine, Loading, Stamp, TextLink, s } from '@/components/ui';
import { api, countOpen } from '@/lib/api';
import { SITE } from '@/lib/config';
import { GRADE_HINT, ago, amazonUrl, asinOf, minutesSince, money } from '@/lib/format';
import { useShelves, shelfName } from '@/lib/shelves';
import { C, F, GUTTER, T } from '@/lib/tokens';
import type { Deal, Gone, ProductResponse } from '@/lib/types';
import { useApi } from '@/lib/useApi';

export default function DealScreen() {
  const { slug } = useLocalSearchParams<{ slug: string; s?: string }>();
  const asin = asinOf(slug);
  const { data, error, reload } = useApi(`product:${asin}`, () => api.product(asin));

  useEffect(() => {
    countOpen(asin);
  }, [asin]);

  return (
    <SafeAreaView style={s.screen} edges={['top']}>
      <View style={{ flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center', paddingHorizontal: GUTTER }}>
        <BackLink label="Back" />
        <Pressable
          accessibilityRole="button"
          accessibilityLabel="Share"
          onPress={() => Share.share({ url: `${SITE}/deal/${slug}/`, message: `${SITE}/deal/${slug}/` })}
          style={{ width: 44, height: 44, alignItems: 'center', justifyContent: 'center' }}>
          <SymbolView name={{ ios: 'square.and.arrow.up', android: 'share', web: 'share' }} size={22} tintColor={C.stamp} />
        </Pressable>
      </View>
      {data ? (
        data.deal ? (
          <Live deal={data.deal} related={data} />
        ) : data.gone ? (
          <WentAway gone={data.gone} related={data.same_shelf} />
        ) : (
          <Empty title="We can't find that deal" line="It may have sold, or Amazon moved the listing." action="See all deals" onAction={() => router.navigate('/deals')} />
        )
      ) : error ? (
        <ErrorState onRetry={reload} />
      ) : (
        <Loading />
      )}
    </SafeAreaView>
  );
}

function Live({ deal: d, related }: { deal: Deal; related: ProductResponse }) {
  const shelves = useShelves();
  const shelf = shelves.get(d.shelf);
  const checked = ago(minutesSince(d.confirmed_at));
  const usual = d.usual_price && d.usual_price > d.price ? d.usual_price : null;
  const open = () => Linking.openURL(amazonUrl(d));
  return (
    <>
      <ScrollView contentContainerStyle={{ paddingBottom: 24 }}>
        <View style={{ height: 250, backgroundColor: C.slip, padding: 16 }}>
          {d.image ? <Image source={d.image} contentFit="contain" style={{ flex: 1 }} accessibilityLabel={d.title} /> : null}
          <Stamp pct={d.pct_off} size="big" />
        </View>
        <View style={{ backgroundColor: C.slip, borderTopWidth: 1, borderStyle: 'dashed', borderColor: C.rule, padding: GUTTER, gap: 10 }}>
          <Text style={T.label}>
            {shelf ? `${shelf.aisle_name} › ${shelf.name}` : shelfName(d.shelf, shelves)}
          </Text>
          <Text style={{ fontFamily: F.textSemi, fontSize: 22, lineHeight: 29, color: C.ink }}>{d.title}</Text>
          <View style={{ flexDirection: 'row', alignItems: 'baseline', gap: 10, flexWrap: 'wrap' }}>
            <Text style={{ fontFamily: F.textBold, fontSize: 30, color: C.ink, ...T.tnum }}>{money(d.price)}</Text>
            {usual ? <Text style={[T.body, { color: C.ink2 }, T.tnum]}>Usually {money(usual)}</Text> : null}
          </View>
          <View style={{ flexDirection: 'row', alignItems: 'center', gap: 10 }}>
            <Grade condition={d.condition} size={16} />
            <Text style={[T.small, { fontSize: 15 }]}>{GRADE_HINT[d.condition] ?? ''}</Text>
          </View>
          {d.size ? <Text style={T.small}>Size {d.size}.</Text> : null}
          {d.variants > 1 || d.units > 1 ? (
            <Text style={[T.small, { fontSize: 15 }]}>
              {d.variants > 1 ? `Comes in ${d.variants} ${d.fit ? 'sizes' : 'versions'}; the price is the lowest. ` : ''}
              {d.units > 1 ? `${d.units} units listed.` : ''}
            </Text>
          ) : null}
          <Text style={[T.small, { fontSize: 15 }]}>
            {checked ? `Last checked ${checked}. It may have sold since.` : 'It may have sold since we last checked.'}
          </Text>
        </View>

        <View style={{ padding: GUTTER, gap: 22 }}>
          <Button
            kind="outline"
            label="Tell me when one lands"
            onPress={() => router.push({ pathname: '/alert-sheet', params: { kw: d.brand ?? '' } })}
            icon={<SymbolView name={{ ios: 'bell', android: 'notifications', web: 'notifications' }} size={18} tintColor={C.stamp} />}
          />
          {related.same_shelf.length ? (
            <View style={{ gap: 10 }}>
              <View style={{ flexDirection: 'row', justifyContent: 'space-between', alignItems: 'baseline' }}>
                <Text style={[T.h3, { flexShrink: 1 }]}>
                  {related.same_size ? `More in size ${related.same_size}` : 'More on this shelf'}
                </Text>
                <TextLink label="See all" onPress={() => router.push({ pathname: '/shelf/[id]', params: { id: d.shelf } })} />
              </View>
              <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={{ gap: 12 }}>
                {related.same_shelf.map((r) => (
                  <DealCard key={r.id} deal={r} surface="related" width={150} />
                ))}
              </ScrollView>
            </View>
          ) : null}
        </View>
        <KeepaLine style={{ paddingTop: 0 }} />
      </ScrollView>

      <SafeAreaView edges={['bottom']} style={{ backgroundColor: C.slip, borderTopWidth: 1, borderColor: C.rule }}>
        <View style={{ flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', gap: 12, paddingHorizontal: GUTTER, paddingTop: 10, paddingBottom: 6 }}>
          <View>
            <Text style={{ fontFamily: F.textBold, fontSize: 22, color: C.ink, ...T.tnum }}>{money(d.price)}</Text>
            <Text style={T.small}>
              {d.condition} · {d.pct_off}% off
            </Text>
          </View>
          <Button label="On Amazon ↗" onPress={open} style={{ height: 50, paddingHorizontal: 22 }} />
        </View>
      </SafeAreaView>
    </>
  );
}

function WentAway({ gone: g, related }: { gone: Gone; related: Deal[] }) {
  const shelves = useShelves();
  return (
    <ScrollView contentContainerStyle={{ paddingBottom: 24 }}>
      <View style={{ paddingHorizontal: GUTTER, gap: 18 }}>
        <View style={{ backgroundColor: C.slipMuted, flexDirection: 'row', gap: 14, padding: 12, alignItems: 'center' }}>
          <View style={{ width: 112, height: 112, backgroundColor: C.slip, alignItems: 'center', justifyContent: 'center' }}>
            {g.image ? <Image source={g.image} contentFit="contain" style={{ width: '92%', height: '92%', opacity: 0.4 }} /> : null}
            <GoneStamp size={28} />
          </View>
          <View style={{ flex: 1, gap: 4 }}>
            <Text style={T.bodyStrong} numberOfLines={3}>
              {g.title}
            </Text>
            <Text style={[T.small, T.tnum]}>
              Last price {money(g.last_price)} · {g.pct_off}% off
            </Text>
            <Text style={T.small}>{g.condition}</Text>
          </View>
        </View>
        <View style={{ gap: 8 }}>
          <Text style={{ fontFamily: F.textBold, fontSize: 24, color: C.ink }}>This one's gone.</Text>
          <Text style={[T.body, { color: C.ink2 }]}>
            Our checks stopped finding it on Amazon. Usually that means it sold. Most units are the only one of their kind.
          </Text>
        </View>
        <Button label="Tell me when one lands" onPress={() => router.push({ pathname: '/alert-sheet', params: { kw: g.brand ?? '' } })} />
      </View>
      {related.length ? (
        <View style={{ gap: 10, paddingTop: 26 }}>
          <Text style={[T.h3, { paddingHorizontal: GUTTER }]}>Live in {shelfName(g.shelf, shelves)}</Text>
          <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={{ paddingHorizontal: GUTTER, gap: 12 }}>
            {related.map((r) => (
              <DealCard key={r.id} deal={r} surface="related" width={150} />
            ))}
          </ScrollView>
        </View>
      ) : null}
      <KeepaLine />
    </ScrollView>
  );
}
