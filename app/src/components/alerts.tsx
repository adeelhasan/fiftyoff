import { Switch, Text, View } from 'react-native';

import { KEYWORD_LIMIT } from '@/lib/session';
import { C, F, T } from '@/lib/tokens';

export function HeadStartInfo() {
  return (
    <View style={{ backgroundColor: C.kraft, padding: 16, gap: 8 }}>
      <Text style={[T.label, { color: C.kraftInk }]}>Head start</Text>
      <Text style={{ fontFamily: F.textSemi, fontSize: 17, lineHeight: 23, color: C.kraftInk }}>
        Alerts for your own words, the moment we see a deal.
      </Text>
      <Text style={{ fontFamily: F.text, fontSize: 15, lineHeight: 21, color: C.kraftInk }}>
        Up to {KEYWORD_LIMIT} words like "espresso" or "galaxy ring", by email and push on this iPhone. Most good units sell
        within a day; this is how you get to them first.
      </Text>
    </View>
  );
}

export function Toggle({ label, hint, value, onChange }: { label: string; hint?: string; value: boolean; onChange: (v: boolean) => void }) {
  return (
    <View
      style={{
        minHeight: 52,
        paddingHorizontal: 16,
        borderTopWidth: 1,
        borderColor: C.ruleSoft,
        flexDirection: 'row',
        alignItems: 'center',
        justifyContent: 'space-between',
      }}>
      <View>
        <Text style={T.body}>{label}</Text>
        {hint ? <Text style={T.small}>{hint}</Text> : null}
      </View>
      <Switch accessibilityLabel={label} value={value} onValueChange={onChange} trackColor={{ true: C.good }} />
    </View>
  );
}
