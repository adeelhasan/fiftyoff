// All deals: search entry, filter chips, a 2-column grid that loads more as you scroll.
import { router } from 'expo-router';
import { SymbolView } from 'expo-symbols';
import { useState } from 'react';
import { FlatList, Pressable, ScrollView, Text, View } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';

import { DealCard } from '@/components/DealCard';
import { OptionSheet } from '@/components/OptionSheet';
import { Chip, Empty, ErrorState, KeepaLine, Loading, s } from '@/components/ui';
import { api } from '@/lib/api';
import { COND_OPTIONS, condIds, count, type CondPref } from '@/lib/format';
import { usePrefs } from '@/lib/prefs';
import { useShelves, shelfName } from '@/lib/shelves';
import { usePaged } from '@/lib/useApi';
import { C, F, GUTTER, T } from '@/lib/tokens';
import type { AisleCount, Deal, PriceBand, Sort } from '@/lib/types';

const PAGE = 40;
const SORTS: { id: Sort; label: string }[] = [
  { id: 'newest', label: 'Newest first' },
  { id: 'discount', label: 'Biggest discount' },
  { id: 'price-asc', label: 'Lowest price' },
  { id: 'price-desc', label: 'Highest price' },
];
const PRICES: { id: PriceBand; label: string }[] = [
  { id: 'any', label: 'Any price' },
  { id: 'under-100', label: 'Under $100' },
  { id: '100-300', label: '$100–300' },
  { id: '300-plus', label: '$300+' },
];

type Sheet = 'sort' | 'cond' | 'price' | 'aisle' | null;

export default function AllDeals() {
  const { prefs, set } = usePrefs();
  const shelves = useShelves();
  const [sort, setSort] = useState<Sort>('newest');
  const [price, setPrice] = useState<PriceBand>('any');
  const [aisle, setAisle] = useState<string>('');
  const [sheet, setSheet] = useState<Sheet>(null);

  const [aisles, setAisles] = useState<AisleCount[]>([]);
  const query = { cond: condIds(prefs.cond), sort, price, aisle: aisle || undefined, limit: PAGE };
  const list = usePaged<Deal>(JSON.stringify(query), (offset) =>
    api.deals({ ...query, offset }).then((r) => {
      setAisles(r.aisles);
      return { items: r.deals, total: r.count };
    }),
  );
  const { items: deals, total, error, busy, more } = list;

  const aisleName = aisles.find((a) => a.id === aisle)?.name;
  const header = (
    <View style={{ gap: 14, paddingBottom: 14 }}>
      <View style={{ paddingHorizontal: GUTTER, gap: 6, paddingTop: 8 }}>
        <Text style={T.title}>All deals</Text>
        <Text style={[T.label, T.tnum]}>{total === null ? ' ' : `${count(total)} live`}</Text>
      </View>
      <Pressable
        accessibilityRole="search"
        onPress={() => router.push('/search')}
        style={{
          marginHorizontal: GUTTER,
          height: 44,
          flexDirection: 'row',
          alignItems: 'center',
          gap: 8,
          backgroundColor: C.slip,
          borderWidth: 1.5,
          borderColor: C.rule,
          borderRadius: 2,
          paddingHorizontal: 12,
        }}>
        <SymbolView name={{ ios: 'magnifyingglass', android: 'search', web: 'search' }} size={18} tintColor={C.ink2} />
        <Text style={{ fontFamily: F.text, fontSize: 15, color: C.ink2 }}>Search, e.g. robot vacuum</Text>
      </Pressable>
      <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={{ paddingHorizontal: GUTTER, gap: 8 }}>
        <Chip label={`${SORTS.find((x) => x.id === sort)?.label} ▾`} on onPress={() => setSheet('sort')} />
        <Chip label={COND_OPTIONS.find((c) => c.id === prefs.cond)?.label ?? 'Condition'} on={prefs.cond !== 'good'} onPress={() => setSheet('cond')} />
        <Chip label={price === 'any' ? 'Price' : PRICES.find((p) => p.id === price)!.label} on={price !== 'any'} onPress={() => setSheet('price')} />
        <Chip label={aisleName ?? 'Aisle'} on={!!aisle} onPress={() => setSheet('aisle')} />
        <Chip label="Clothes & Shoes" onPress={() => router.push('/sizes')} />
      </ScrollView>
    </View>
  );

  return (
    <SafeAreaView style={s.screen} edges={['top']}>
      <FlatList
        data={deals}
        keyExtractor={(d) => d.id}
        numColumns={2}
        columnWrapperStyle={{ gap: 12, paddingHorizontal: GUTTER }}
        contentContainerStyle={{ gap: 12, paddingBottom: 24 }}
        ListHeaderComponent={header}
        renderItem={({ item }) => (
          <View style={{ flex: 1, maxWidth: '50%' }}>
            <DealCard deal={item} surface="deals" shelf={shelfName(item.shelf, shelves)} style={{ flex: 1 }} />
          </View>
        )}
        onEndReached={more}
        onEndReachedThreshold={0.6}
        ListEmptyComponent={
          error ? (
            <ErrorState onRetry={list.retry} />
          ) : total === 0 ? (
            <Empty
              title="Nothing here right now"
              line="Try a wider price or condition, or another aisle."
              action="Clear filters"
              onAction={() => {
                setPrice('any');
                setAisle('');
              }}
            />
          ) : (
            <Loading />
          )
        }
        ListFooterComponent={
          <>
            {busy && deals.length ? <Loading /> : null}
            {deals.length ? <KeepaLine /> : null}
          </>
        }
      />

      {sheet === 'sort' ? <OptionSheet title="Sort" options={SORTS} value={sort} onPick={setSort} onClose={() => setSheet(null)} /> : null}
      {sheet === 'cond' ? (
        <OptionSheet<CondPref>
          title="Condition"
          options={COND_OPTIONS}
          value={prefs.cond}
          onPick={(cond) => set({ cond })}
          onClose={() => setSheet(null)}
        />
      ) : null}
      {sheet === 'price' ? <OptionSheet title="Price" options={PRICES} value={price} onPick={setPrice} onClose={() => setSheet(null)} /> : null}
      {sheet === 'aisle' ? (
        <OptionSheet
          title="Aisle"
          options={[{ id: '', label: 'Every aisle' }, ...aisles.map((a) => ({ id: a.id, label: `${a.name} · ${count(a.count)}` }))]}
          value={aisle}
          onPick={setAisle}
          onClose={() => setSheet(null)}
        />
      ) : null}
    </SafeAreaView>
  );
}
