// Onboarding 1: what this is, shown with a real deal from today's best.
import { Image } from 'expo-image';
import { router } from 'expo-router';
import { Text, View } from 'react-native';

import { StepFrame } from '@/components/Onboarding';
import { Grade, Stamp, Wordmark, KeepaLine } from '@/components/ui';
import { api } from '@/lib/api';
import { money } from '@/lib/format';
import { C, F, T } from '@/lib/tokens';
import { useApi } from '@/lib/useApi';

export default function WhatThisIs() {
  const { data } = useApi('today', api.today);
  const d = data?.featured[0];
  const shelf = d ? data?.shelves.find((s) => s.id === d.shelf)?.name : undefined;
  return (
    <StepFrame step={1} next={() => router.push('/onboarding/buy')}>
      <Wordmark size={32} />
      {d ? (
        <View style={{ backgroundColor: C.slip }}>
          <View style={{ height: 240, padding: 12 }}>
            {d.image ? <Image source={d.image} contentFit="contain" style={{ flex: 1 }} accessibilityLabel={d.title} /> : null}
            <Stamp pct={d.pct_off} size="big" />
            <Grade condition={d.condition} size={16} style={{ position: 'absolute', right: 10, bottom: 10 }} />
          </View>
          <View style={{ borderTopWidth: 1, borderStyle: 'dashed', borderColor: C.rule, padding: 14, gap: 6 }}>
            {shelf ? <Text style={T.label}>{shelf}</Text> : null}
            <Text style={{ fontFamily: F.text, fontSize: 15, lineHeight: 20, color: C.ink }} numberOfLines={2}>
              <Text style={[T.price, { fontSize: 19 }]}>{money(d.price)}</Text> {d.title}
            </Text>
            {d.usual_price && d.usual_price > d.price ? <Text style={[T.small, T.tnum]}>Usually {money(d.usual_price)}</Text> : null}
          </View>
        </View>
      ) : (
        <View style={{ height: 320, backgroundColor: C.slip }} />
      )}
      <Text style={{ fontFamily: F.textBold, fontSize: 26, lineHeight: 32, color: C.ink }}>
        Open-box and used items from Amazon, at about half the usual price.
      </Text>
      <Text style={[T.body, { color: C.ink2 }]}>
        Sold and shipped by Amazon, with its normal returns. We compare each price with what the product usually sells for,
        not an inflated list price.
      </Text>
      <KeepaLine style={{ paddingHorizontal: 0, paddingVertical: 0 }} />
    </StepFrame>
  );
}
