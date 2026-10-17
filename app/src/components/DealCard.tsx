// The deal card (design/README.md, D65, D68, D70): photo with the % stamp, grade and variant tag; shelf label; price
// running into the title. The card opens the deal page; a separate strip goes straight to Amazon.
import { Image } from 'expo-image';
import { router } from 'expo-router';
import { Linking, Pressable, Text, View, type StyleProp, type ViewStyle } from 'react-native';

import { amazonUrl, money, variantTag } from '@/lib/format';
import { C, F, T } from '@/lib/tokens';
import type { Deal, Gone } from '@/lib/types';

import { GoneStamp, Grade, KraftTag, Stamp } from './ui';

export function openDeal(d: Deal, surface: string) {
  router.push({ pathname: '/deal/[slug]', params: { slug: d.slug, s: surface } });
}

export function DealCard({
  deal: d,
  surface,
  shelf,
  width,
  style,
}: {
  deal: Deal;
  surface: string;
  shelf?: string; // shelf label; left out inside a shelf row
  width?: number; // fixed width in a horizontal row; otherwise fills its column
  style?: StyleProp<ViewStyle>;
}) {
  const muted = d.condition === 'Acceptable';
  const tag = d.size && d.fit ? d.size : variantTag(d);
  return (
    <View style={[{ backgroundColor: muted ? C.slipMuted : C.slip, width }, style]}>
      <Pressable
        accessibilityRole="link"
        accessibilityLabel={`${d.pct_off}% off, ${money(d.price)}, ${d.title}, ${d.condition}`}
        onPress={() => openDeal(d, surface)}
        style={({ pressed }) => ({ opacity: pressed ? 0.85 : 1 })}>
        <View style={{ aspectRatio: 1, padding: 8, backgroundColor: C.slip }}>
          {d.image ? (
            <Image
              source={d.image}
              contentFit="contain"
              style={{ flex: 1, opacity: muted ? 0.85 : 1 }}
              transition={120}
              accessibilityIgnoresInvertColors
            />
          ) : null}
          <Stamp pct={d.pct_off} muted={muted} />
          {tag ? <KraftTag style={{ position: 'absolute', top: 8, right: 6 }}>{tag}</KraftTag> : null}
          <Grade condition={d.condition} style={{ position: 'absolute', right: 6, bottom: 6 }} />
        </View>
        <View style={{ borderTopWidth: 1, borderStyle: 'dashed', borderColor: C.rule, padding: 10, paddingBottom: 8, gap: 4 }}>
          {shelf ? (
            <Text style={T.label} numberOfLines={1}>
              {shelf}
            </Text>
          ) : null}
          <Text style={{ fontFamily: F.text, fontSize: 14, lineHeight: 18, color: C.ink }} numberOfLines={2}>
            <Text style={T.price}>{money(d.price)}</Text> {d.title}
          </Text>
        </View>
      </Pressable>
      <Pressable
        accessibilityRole="link"
        accessibilityLabel={`Open ${d.title} on Amazon`}
        onPress={() => Linking.openURL(amazonUrl(d))}
        style={({ pressed }) => ({
          height: 44,
          borderTopWidth: 1,
          borderColor: C.ruleSoft,
          alignItems: 'flex-end',
          justifyContent: 'center',
          paddingHorizontal: 10,
          marginTop: 'auto',
          backgroundColor: pressed ? C.stampTint : 'transparent',
        })}>
        <Text style={{ fontFamily: F.textSemi, fontSize: 14, color: C.stamp }}>Amazon ↗</Text>
      </Pressable>
    </View>
  );
}

/** A gone unit: greyed, GONE stamp, last price. Not a link (gone units get no deal page, D66). */
export function GoneMini({ gone: g, width = 130, line }: { gone: Gone; width?: number; line: string }) {
  return (
    <View style={{ width, backgroundColor: C.slipMuted }}>
      <View style={{ height: 110, alignItems: 'center', justifyContent: 'center', backgroundColor: C.slip }}>
        {g.image ? (
          <Image source={g.image} contentFit="contain" style={{ width: '80%', height: 90, opacity: 0.4 }} />
        ) : null}
        <GoneStamp />
      </View>
      <View style={{ padding: 10, gap: 2 }}>
        <Text style={T.small} numberOfLines={1}>
          <Text style={[T.smallStrong, T.tnum]}>{money(g.last_price)}</Text> {g.title}
        </Text>
        <Text style={[T.small, T.tnum]}>{line}</Text>
      </View>
    </View>
  );
}
