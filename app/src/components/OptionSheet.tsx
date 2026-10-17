// A plain picker sheet for filter chips: a scrim and a list, one choice.
import { Modal, Pressable, ScrollView, Text, View } from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';

import { C, F, T } from '@/lib/tokens';

export function OptionSheet<K extends string>({
  title,
  options,
  value,
  onPick,
  onClose,
}: {
  title: string;
  options: { id: K; label: string; hint?: string }[];
  value: K | null;
  onPick: (id: K) => void;
  onClose: () => void;
}) {
  const insets = useSafeAreaInsets();
  return (
    <Modal transparent animationType="fade" visible onRequestClose={onClose}>
      <Pressable accessibilityLabel="Close" onPress={onClose} style={{ flex: 1, backgroundColor: C.scrim }} />
      <View style={{ backgroundColor: C.slip, paddingBottom: insets.bottom + 12, maxHeight: '70%' }}>
        <Text style={[T.label, { padding: 16, paddingBottom: 8 }]}>{title}</Text>
        <ScrollView>
          {options.map((o) => {
            const on = o.id === value;
            return (
              <Pressable
                key={o.id}
                accessibilityRole="radio"
                accessibilityState={{ checked: on }}
                onPress={() => {
                  onPick(o.id);
                  onClose();
                }}
                style={({ pressed }) => ({
                  minHeight: 52,
                  paddingHorizontal: 16,
                  justifyContent: 'center',
                  borderTopWidth: 1,
                  borderColor: C.ruleSoft,
                  backgroundColor: pressed ? C.stampTint : 'transparent',
                })}>
                <Text style={{ fontFamily: on ? F.textSemi : F.text, fontSize: 16, color: on ? C.stamp : C.ink }}>
                  {on ? '✓ ' : ''}
                  {o.label}
                </Text>
                {o.hint ? <Text style={T.small}>{o.hint}</Text> : null}
              </Pressable>
            );
          })}
        </ScrollView>
      </View>
    </Modal>
  );
}
