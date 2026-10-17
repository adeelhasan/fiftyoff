// The frame every onboarding step shares: Back / Skip, a title, the body, step dots and the main button. In edit mode
// (opened from Settings or Clothes & shoes) it shows only Back and a Done button.
import { router } from 'expo-router';
import type { ReactNode } from 'react';
import { ScrollView, Text, View } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';

import { usePrefs } from '@/lib/prefs';
import { C, GUTTER, T } from '@/lib/tokens';

import { Button, TextLink } from './ui';

export const STEPS = 4;

/** Leave onboarding: whatever was picked stays, the rest keeps its defaults. */
export function useFinish() {
  const { set } = usePrefs();
  return () => {
    set({ onboarded: true });
    router.replace('/');
  };
}

export function StepFrame({
  step,
  edit,
  title,
  lead,
  children,
  next,
  nextLabel = 'Next',
  nextKind = 'primary',
  footer,
  scroll = true,
}: {
  step: number;
  edit?: boolean;
  title?: string;
  lead?: string;
  children: ReactNode;
  next: () => void;
  nextLabel?: string;
  nextKind?: 'primary' | 'plain';
  footer?: ReactNode;
  scroll?: boolean;
}) {
  const finish = useFinish();
  const Body = scroll ? ScrollView : View;
  return (
    <SafeAreaView style={{ flex: 1, backgroundColor: C.ground }}>
      <View style={{ flexDirection: 'row', justifyContent: 'space-between', paddingHorizontal: 20 }}>
        {step > 1 || edit ? <TextLink label="Back" onPress={() => router.back()} style={{ fontSize: 16 }} /> : <View />}
        {edit ? null : <TextLink label="Skip" onPress={finish} style={{ fontSize: 16 }} />}
      </View>
      <Body style={{ flex: 1 }} contentContainerStyle={scroll ? { paddingHorizontal: 20, paddingBottom: 16, gap: 18 } : undefined}>
        <View style={{ gap: 8, paddingTop: 6 }}>
          {title ? <Text style={[T.title, { fontSize: 40, lineHeight: 46 }]}>{title}</Text> : null}
          {lead ? <Text style={T.body}>{lead}</Text> : null}
        </View>
        {children}
      </Body>
      <View style={{ paddingHorizontal: 20, paddingTop: 10, paddingBottom: 8, gap: 12 }}>
        {edit ? null : (
          <View style={{ flexDirection: 'row', justifyContent: 'center', gap: 8 }} accessibilityLabel={`Step ${step} of ${STEPS}`}>
            {Array.from({ length: STEPS }, (_, i) => (
              <View key={i} style={{ width: 20, height: 4, backgroundColor: i + 1 === step ? C.ink : C.rule }} />
            ))}
          </View>
        )}
        <Button label={edit ? 'Done' : nextLabel} kind={edit ? 'primary' : nextKind} onPress={edit ? () => router.back() : next} />
        {footer}
      </View>
    </SafeAreaView>
  );
}

export const gutter = { paddingHorizontal: GUTTER };
