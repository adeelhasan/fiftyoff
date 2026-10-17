// Onboarding 4: the week's best, by email (D73, D74). No account; no notification prompt (push is Head start).
import { Image } from 'expo-image';
import { Text, View } from 'react-native';

import { StepFrame, useFinish } from '@/components/Onboarding';
import { WeeklySignup, weeklyStatus } from '@/components/WeeklySignup';
import { KeepaLine } from '@/components/ui';
import { api } from '@/lib/api';
import { money } from '@/lib/format';
import { usePrefs } from '@/lib/prefs';
import { C, F, T } from '@/lib/tokens';
import { useApi } from '@/lib/useApi';

export default function Weekly() {
  const finish = useFinish();
  const { prefs } = usePrefs();
  const { data } = useApi('today', api.today);
  const sample = [
    ...(data?.featured.slice(0, 2).map((d) => ({ img: d.image, price: d.price, title: d.title, badge: `${d.pct_off}% OFF`, gone: false })) ?? []),
    ...(data?.gone.slice(0, 1).map((g) => ({ img: g.image, price: g.last_price, title: g.title, badge: 'SOLD', gone: true })) ?? []),
  ];

  return (
    <StepFrame
      step={4}
      title="The week's best, by email"
      next={finish}
      nextLabel={prefs.weekly ? 'Start browsing' : 'Not now'}
      nextKind={prefs.weekly ? 'primary' : 'plain'}
      footer={<Text style={[T.small, { textAlign: 'center' }]}>Want them the moment they land? That's Head start, on fiftyoff.app.</Text>}>
      {sample.length ? (
        <View style={{ backgroundColor: C.kraft, padding: 14 }}>
          <View style={{ backgroundColor: C.slip, padding: 12, gap: 8 }}>
            <Text style={T.label}>The week's best</Text>
            {sample.map((r, i) => (
              <View key={i} style={{ flexDirection: 'row', alignItems: 'center', gap: 10, borderTopWidth: 1, borderStyle: 'dashed', borderColor: C.rule, paddingTop: 8 }}>
                {r.img ? <Image source={r.img} contentFit="contain" style={{ width: 40, height: 40, opacity: r.gone ? 0.45 : 1 }} /> : null}
                <Text style={{ flex: 1, fontFamily: F.text, fontSize: 14, color: C.ink }} numberOfLines={1}>
                  <Text style={[T.smallStrong, T.tnum]}>{money(r.price)}</Text> {r.title}
                </Text>
                <Text style={[T.label, { borderWidth: 1.5, borderColor: r.gone ? C.gone : C.stamp, color: r.gone ? C.goneInk : C.stamp, paddingHorizontal: 6 }]}>
                  {r.badge}
                </Text>
              </View>
            ))}
          </View>
        </View>
      ) : null}
      <Text style={T.body}>Once a week, the best deals we found, and which ones already sold.</Text>
      {prefs.weekly ? (
        <View style={{ backgroundColor: C.goodTint, borderWidth: 1.5, borderColor: C.good, padding: 14, gap: 4 }}>
          <Text style={[T.bodyStrong, { color: C.goodInk }]}>✓ {prefs.weekly.email}</Text>
          <Text style={[T.small, { color: C.goodInk }]}>{weeklyStatus(prefs.weekly.state)}</Text>
        </View>
      ) : (
        <WeeklySignup />
      )}
      <KeepaLine style={{ paddingHorizontal: 0, paddingVertical: 0 }} />
    </StepFrame>
  );
}
