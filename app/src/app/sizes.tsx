// Clothes & shoes in the person's sizes (D59, D75). Sizes live on the phone; "Change" opens the sizes step.
import { router } from 'expo-router';
import { FlatList, Text, View } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';

import { DealCard } from '@/components/DealCard';
import { BackLink, Button, Empty, ErrorState, KeepaLine, Loading, TextLink, s } from '@/components/ui';
import { api } from '@/lib/api';
import { count } from '@/lib/format';
import { anySizes, describeSizes, usePrefs } from '@/lib/prefs';
import { useShelves, shelfName } from '@/lib/shelves';
import { usePaged } from '@/lib/useApi';
import { C, F, GUTTER, T } from '@/lib/tokens';
import type { Deal } from '@/lib/types';

const editSizes = () => router.push({ pathname: '/onboarding/sizes', params: { edit: '1' } });

export default function Sizes() {
  const { prefs } = usePrefs();
  const shelves = useShelves();
  const has = anySizes(prefs.sizes);
  const key = JSON.stringify(prefs.sizes);
  const list = usePaged<Deal>(has ? key : null, (offset) =>
    api.sized(prefs.sizes, offset).then((r) => ({ items: r.deals, total: r.count })),
  );
  const { items: deals, total, error, busy } = list;

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
        onEndReached={list.more}
        onEndReachedThreshold={0.6}
        ListHeaderComponent={
          <View style={{ gap: 14, paddingBottom: 4 }}>
            <View style={{ paddingHorizontal: GUTTER, gap: 6 }}>
              <Text style={T.title}>Clothes & shoes</Text>
              {has ? <Text style={[T.label, T.tnum]}>{total === null ? ' ' : `${count(total)} live in your sizes`}</Text> : null}
            </View>
            {has ? (
              <View
                style={{
                  marginHorizontal: GUTTER,
                  backgroundColor: C.slip,
                  padding: 12,
                  flexDirection: 'row',
                  alignItems: 'center',
                  justifyContent: 'space-between',
                  gap: 10,
                }}>
                <Text style={{ flex: 1, fontFamily: F.textSemi, fontSize: 15, color: C.ink, ...T.tnum }}>{describeSizes(prefs.sizes)}</Text>
                <TextLink label="Change" onPress={editSizes} />
              </View>
            ) : null}
          </View>
        }
        renderItem={({ item }) => (
          <View style={{ flex: 1, maxWidth: '50%' }}>
            <DealCard deal={item} surface="sizes" shelf={shelfName(item.shelf, shelves)} style={{ flex: 1 }} />
          </View>
        )}
        ListEmptyComponent={
          !has ? (
            <View style={{ padding: GUTTER, gap: 12 }}>
              <Text style={T.body}>Some of our best deals are in clothing and shoes. Tell us your sizes and we'll show the ones that fit.</Text>
              <Button label="Pick my sizes" onPress={editSizes} />
            </View>
          ) : error ? (
            <ErrorState onRetry={list.retry} />
          ) : total === 0 ? (
            <Empty title="Nothing in your sizes right now" line="Add a size or two, or look again tomorrow." action="Change sizes" onAction={editSizes} />
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
    </SafeAreaView>
  );
}
