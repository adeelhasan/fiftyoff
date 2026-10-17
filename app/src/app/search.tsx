// Search (D54): live matches, then the ones that went this week, and "Tell me when one lands".
import { Image } from 'expo-image';
import { router } from 'expo-router';
import { SymbolView } from 'expo-symbols';
import { useEffect, useState } from 'react';
import { FlatList, Pressable, Text, TextInput, View } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';

import { openDeal } from '@/components/DealCard';
import { Empty, ErrorState, GoneStamp, Grade, KeepaLine, Loading, Stamp, TextLink, s } from '@/components/ui';
import { api } from '@/lib/api';
import { ago, condIds, minutesSince, money } from '@/lib/format';
import { usePrefs } from '@/lib/prefs';
import { useShelves, shelfName } from '@/lib/shelves';
import { C, F, GUTTER, T } from '@/lib/tokens';
import type { Deal, Gone } from '@/lib/types';
import { useApi } from '@/lib/useApi';

type Row = { kind: 'deal'; d: Deal } | { kind: 'gone'; g: Gone } | { kind: 'label'; text: string };

export default function Search() {
  const { prefs } = usePrefs();
  const shelves = useShelves();
  const [q, setQ] = useState('');
  const term = q.trim();
  const [debounced, setDebounced] = useState('');
  useEffect(() => {
    const t = setTimeout(() => setDebounced(term), 300);
    return () => clearTimeout(t);
  }, [term]);
  const active = debounced.length >= 2 && debounced === term;
  const { data, error, loading: busy, reload } = useApi(
    active ? `search:${debounced}:${prefs.cond}` : null,
    () => api.deals({ q: debounced, cond: condIds(prefs.cond), limit: 60 }),
  );
  const res = active ? data : null;

  const gone = res?.gone ?? [];
  const rows: Row[] = res
    ? [
        ...res.deals.map((d) => ({ kind: 'deal' as const, d })),
        ...(gone.length ? [{ kind: 'label' as const, text: 'Gone' }, ...gone.map((g) => ({ kind: 'gone' as const, g }))] : []),
      ]
    : [];

  return (
    <SafeAreaView style={s.screen} edges={['top']}>
      <View style={{ flexDirection: 'row', alignItems: 'center', gap: 10, paddingHorizontal: GUTTER, paddingVertical: 8 }}>
        <View
          style={{
            flex: 1,
            height: 44,
            flexDirection: 'row',
            alignItems: 'center',
            gap: 8,
            backgroundColor: C.slip,
            borderWidth: 2,
            borderColor: C.ink,
            borderRadius: 2,
            paddingHorizontal: 12,
          }}>
          <SymbolView name={{ ios: 'magnifyingglass', android: 'search', web: 'search' }} size={18} tintColor={C.ink2} />
          <TextInput
            accessibilityLabel="Search deals"
            autoFocus
            value={q}
            onChangeText={setQ}
            placeholder="Search, e.g. robot vacuum"
            placeholderTextColor={C.ink2}
            returnKeyType="search"
            autoCorrect={false}
            style={{ flex: 1, fontFamily: F.text, fontSize: 16, color: C.ink }}
          />
        </View>
        <TextLink label="Cancel" onPress={() => router.back()} style={{ fontSize: 16 }} />
      </View>

      <FlatList
        data={rows}
        keyboardShouldPersistTaps="handled"
        keyExtractor={(r, i) => (r.kind === 'deal' ? r.d.id : r.kind === 'gone' ? `g${r.g.id}` : `l${i}`)}
        contentContainerStyle={{ paddingHorizontal: GUTTER, gap: 10, paddingBottom: 24 }}
        ListHeaderComponent={
          res ? (
            <View style={{ gap: 12, paddingBottom: 4 }}>
              <Text style={T.label}>
                {res.count} live{gone.length ? ` · ${gone.length} gone this week` : ''}
              </Text>
              <Pressable
                accessibilityRole="button"
                onPress={() => router.push({ pathname: '/alert-sheet', params: { kw: term } })}
                style={{
                  flexDirection: 'row',
                  alignItems: 'center',
                  justifyContent: 'space-between',
                  gap: 12,
                  backgroundColor: C.slip,
                  borderWidth: 1.5,
                  borderColor: C.stamp,
                  padding: 14,
                }}>
                <View style={{ flexShrink: 1, gap: 2 }}>
                  <Text style={T.bodyStrong}>Tell me when one lands</Text>
                  <Text style={T.small}>For "{term}". Takes an email address.</Text>
                </View>
                <SymbolView name={{ ios: 'bell', android: 'notifications', web: 'notifications' }} size={22} tintColor={C.stamp} />
              </Pressable>
            </View>
          ) : undefined
        }
        renderItem={({ item }) =>
          item.kind === 'label' ? (
            <Text style={[T.label, { paddingTop: 6 }]}>{item.text}</Text>
          ) : item.kind === 'deal' ? (
            <ResultRow d={item.d} shelf={shelfName(item.d.shelf, shelves)} />
          ) : (
            <GoneRow g={item.g} />
          )
        }
        ListEmptyComponent={
          error && active ? (
            <ErrorState onRetry={reload} />
          ) : active && busy ? (
            <Loading />
          ) : res ? (
            <Empty title="Nothing here right now" line={`No live deal matches "${term}". Tap above to hear when one lands.`} />
          ) : (
            <Text style={[T.small, { paddingTop: 8 }]}>Words from the title or brand: "dyson", "galaxy ring", "rug".</Text>
          )
        }
        ListFooterComponent={rows.length ? <KeepaLine style={{ paddingHorizontal: 0 }} /> : undefined}
      />
    </SafeAreaView>
  );
}

function ResultRow({ d, shelf }: { d: Deal; shelf: string }) {
  return (
    <Pressable
      accessibilityRole="link"
      onPress={() => openDeal(d, 'search')}
      style={({ pressed }) => ({ flexDirection: 'row', gap: 12, backgroundColor: C.slip, padding: 10, opacity: pressed ? 0.85 : 1 })}>
      <View style={{ width: 104, height: 104 }}>
        {d.image ? <Image source={d.image} contentFit="contain" style={{ flex: 1 }} /> : null}
        <Stamp pct={d.pct_off} size="small" />
      </View>
      <View style={{ flex: 1, gap: 6 }}>
        <Text style={T.label} numberOfLines={1}>
          {shelf}
        </Text>
        <Text style={{ fontFamily: F.text, fontSize: 15, lineHeight: 20, color: C.ink }} numberOfLines={3}>
          <Text style={T.price}>{money(d.price)}</Text> {d.title}
        </Text>
        <Grade condition={d.condition} style={{ alignSelf: 'flex-start' }} />
      </View>
    </Pressable>
  );
}

function GoneRow({ g }: { g: Gone }) {
  return (
    <View style={{ flexDirection: 'row', gap: 12, backgroundColor: C.slipMuted, padding: 10 }}>
      <View style={{ width: 104, height: 104, backgroundColor: C.slip, alignItems: 'center', justifyContent: 'center' }}>
        {g.image ? <Image source={g.image} contentFit="contain" style={{ width: '90%', height: '90%', opacity: 0.4 }} /> : null}
        <GoneStamp />
      </View>
      <View style={{ flex: 1, gap: 6 }}>
        <Text style={[T.small, { lineHeight: 20 }]} numberOfLines={3}>
          <Text style={[T.smallStrong, T.tnum]}>{money(g.last_price)}</Text> {g.title}
        </Text>
        <Text style={[T.small, T.tnum]}>
          {g.pct_off}% off · {g.condition} · gone {ago(minutesSince(g.gone_at))}
        </Text>
      </View>
    </View>
  );
}
