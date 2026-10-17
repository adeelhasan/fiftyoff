// A shelf: every live card on it, then what went from it this week (D66).
import { useLocalSearchParams } from 'expo-router';
import { FlatList, ScrollView, Text, View } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';

import { DealCard, GoneMini } from '@/components/DealCard';
import { BackLink, Empty, ErrorState, KeepaLine, Loading, s } from '@/components/ui';
import { api } from '@/lib/api';
import { ago, condAllows, minutesSince } from '@/lib/format';
import { usePrefs } from '@/lib/prefs';
import { GUTTER, T } from '@/lib/tokens';
import { useApi } from '@/lib/useApi';

export default function ShelfScreen() {
  const { id } = useLocalSearchParams<{ id: string }>();
  const { prefs } = usePrefs();
  const { data, error, reload } = useApi(`shelf:${id}`, () => api.shelf(id));
  const deals = (data?.deals ?? []).filter((d) => condAllows(prefs.cond, d.condition));

  return (
    <SafeAreaView style={s.screen} edges={['top']}>
      <View style={{ paddingHorizontal: GUTTER }}>
        <BackLink label="Back" />
      </View>
      <FlatList
        data={deals}
        keyExtractor={(d) => d.id}
        numColumns={2}
        columnWrapperStyle={{ gap: 12, paddingHorizontal: GUTTER }}
        contentContainerStyle={{ gap: 12, paddingBottom: 24 }}
        ListHeaderComponent={
          data ? (
            <View style={{ paddingHorizontal: GUTTER, gap: 6, paddingBottom: 6 }}>
              <Text style={T.label}>{data.shelf.aisle_name}</Text>
              <Text style={T.title}>{data.shelf.name}</Text>
              {data.shelf.description ? <Text style={T.small}>{data.shelf.description}</Text> : null}
              <Text style={T.label}>{data.shelf.live} live</Text>
            </View>
          ) : undefined
        }
        renderItem={({ item }) => (
          <View style={{ flex: 1, maxWidth: '50%' }}>
            <DealCard deal={item} surface="shelf" style={{ flex: 1 }} />
          </View>
        )}
        ListEmptyComponent={
          error ? <ErrorState onRetry={reload} /> : data ? <Empty title="Nothing here right now" line="Try a wider condition in Settings." /> : <Loading />
        }
        ListFooterComponent={
          data?.gone.length ? (
            <View style={{ gap: 12, paddingTop: 22 }}>
              <Text style={[T.h3, { paddingHorizontal: GUTTER }]}>Recently gone from {data.shelf.name}</Text>
              <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={{ paddingHorizontal: GUTTER, gap: 10 }}>
                {data.gone.map((g) => (
                  <GoneMini key={g.id} gone={g} line={`${g.pct_off}% off · ${ago(minutesSince(g.gone_at))}`} />
                ))}
              </ScrollView>
              <KeepaLine />
            </View>
          ) : deals.length ? (
            <KeepaLine />
          ) : undefined
        }
      />
    </SafeAreaView>
  );
}
