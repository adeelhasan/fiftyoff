// Small shared pieces from design/README.md: wordmark, stamp, grade, tags, buttons, chips, section heads, the Keepa
// credit, and the loading / empty / error states.
import { router } from 'expo-router';
import type { ReactNode } from 'react';
import {
  ActivityIndicator,
  Linking,
  Pressable,
  StyleSheet,
  Text,
  View,
  type StyleProp,
  type TextStyle,
  type ViewStyle,
} from 'react-native';

import { C, F, GUTTER, T } from '@/lib/tokens';

export function Wordmark({ size = 32 }: { size?: number }) {
  const framed = size >= 28;
  return (
    <View style={{ flexDirection: 'row', alignItems: 'center' }} accessibilityRole="header" accessibilityLabel="fiftyOff">
      <Text style={{ fontFamily: F.display, fontSize: size, lineHeight: size * 1.05, color: C.ink }}>fifty</Text>
      <Text
        style={[
          { fontFamily: F.display, fontSize: size, lineHeight: size * 1.05, color: C.stamp },
          framed && {
            borderWidth: 3,
            borderColor: C.stamp,
            paddingHorizontal: size * 0.12,
            marginLeft: size * 0.06,
            transform: [{ rotate: '-6deg' }],
          },
        ]}>
        Off
      </Text>
    </View>
  );
}

/** The violet % stamp on a photo. */
export function Stamp({ pct, size = 'card', muted }: { pct: number; size?: 'card' | 'big' | 'small'; muted?: boolean }) {
  const big = size === 'big';
  const n = big ? 44 : size === 'small' ? 20 : 24;
  const color = muted ? C.stampMuted : C.stamp;
  return (
    <View
      style={{
        position: 'absolute',
        top: big ? 14 : 8,
        left: big ? 14 : 8,
        borderWidth: big ? 4 : 3,
        borderColor: color,
        backgroundColor: C.stampBacking,
        paddingHorizontal: big ? 10 : 6,
        paddingVertical: 1,
        alignItems: 'center',
        transform: [{ rotate: '-8deg' }],
      }}>
      <Text style={{ fontFamily: F.display, fontSize: n, lineHeight: n * 0.95, color }}>{pct}%</Text>
      <Text style={{ fontFamily: F.display, fontSize: n * 0.42, lineHeight: n * 0.45, letterSpacing: 2, color }}>OFF</Text>
    </View>
  );
}

/** The condition written in marker. Acceptable takes the warning colours. */
export function Grade({ condition, size = 13, style }: { condition: string; size?: number; style?: StyleProp<ViewStyle> }) {
  const warn = condition === 'Acceptable';
  return (
    <View
      style={[
        {
          backgroundColor: warn ? C.warnTint : C.slip,
          borderWidth: 1.5,
          borderColor: warn ? C.warn : C.ink,
          paddingHorizontal: 6,
        },
        style,
      ]}>
      <Text style={{ fontFamily: F.grade, fontSize: size, color: warn ? C.warnInk : C.ink }}>{condition}</Text>
    </View>
  );
}

export function KraftTag({ children, style }: { children: ReactNode; style?: StyleProp<ViewStyle> }) {
  return (
    <View style={[{ backgroundColor: C.kraft, paddingHorizontal: 6, paddingVertical: 1 }, style]}>
      <Text style={{ fontFamily: F.mono, fontSize: 12, color: C.kraftInk }}>{children}</Text>
    </View>
  );
}

export function GoneStamp({ size = 22 }: { size?: number }) {
  return (
    <View
      style={{
        position: 'absolute',
        borderWidth: 3,
        borderColor: C.gone,
        backgroundColor: 'rgba(255,255,255,0.7)',
        paddingHorizontal: 6,
        transform: [{ rotate: '-12deg' }],
      }}>
      <Text style={{ fontFamily: F.display, fontSize: size, color: C.goneInk }}>GONE</Text>
    </View>
  );
}

type ButtonKind = 'primary' | 'outline' | 'plain' | 'ink';

export function Button({
  label,
  onPress,
  kind = 'primary',
  disabled,
  style,
  icon,
}: {
  label: string;
  onPress: () => void;
  kind?: ButtonKind;
  disabled?: boolean;
  style?: StyleProp<ViewStyle>;
  icon?: ReactNode;
}) {
  const bg = { primary: C.stamp, outline: C.slip, plain: 'transparent', ink: C.ink }[kind];
  const fg = { primary: '#FFFFFF', outline: C.stamp, plain: C.ink, ink: '#FFFFFF' }[kind];
  return (
    <Pressable
      accessibilityRole="button"
      disabled={disabled}
      onPress={onPress}
      style={({ pressed }) => [
        {
          height: kind === 'plain' ? 44 : 52,
          borderRadius: 2,
          backgroundColor: kind === 'primary' && pressed ? C.stampPressed : bg,
          borderWidth: kind === 'outline' ? 1.5 : 0,
          borderColor: C.stamp,
          alignItems: 'center',
          justifyContent: 'center',
          flexDirection: 'row',
          gap: 8,
          opacity: disabled ? 0.5 : 1,
          paddingHorizontal: 18,
        },
        style,
      ]}>
      {icon}
      <Text style={{ fontFamily: F.textSemi, fontSize: 17, color: fg }}>{label}</Text>
    </Pressable>
  );
}

export function Chip({
  label,
  on,
  onPress,
  style,
}: {
  label: string;
  on?: boolean;
  onPress: () => void;
  style?: StyleProp<ViewStyle>;
}) {
  return (
    <Pressable
      accessibilityRole="button"
      accessibilityState={{ selected: !!on }}
      onPress={onPress}
      style={[
        {
          minHeight: 40,
          minWidth: 44,
          paddingHorizontal: 12,
          borderRadius: 2,
          justifyContent: 'center',
          alignItems: 'center',
          backgroundColor: on ? C.ink : C.slip,
          borderWidth: 1.5,
          borderColor: on ? C.ink : C.rule,
        },
        style,
      ]}>
      <Text style={{ fontFamily: on ? F.textSemi : F.text, fontSize: 14, color: on ? '#FFFFFF' : C.ink, ...T.tnum }}>
        {label}
      </Text>
    </Pressable>
  );
}

/** A violet-outlined pick chip (onboarding interests, sizes). */
export function PickChip({ label, on, onPress }: { label: string; on: boolean; onPress: () => void }) {
  return (
    <Pressable
      accessibilityRole="checkbox"
      accessibilityState={{ checked: on }}
      onPress={onPress}
      style={{
        minHeight: 40,
        minWidth: 44,
        paddingHorizontal: 12,
        borderRadius: 2,
        justifyContent: 'center',
        alignItems: 'center',
        backgroundColor: on ? C.stampTint : C.slip,
        borderWidth: on ? 2 : 1.5,
        borderColor: on ? C.stamp : C.rule,
      }}>
      <Text style={{ fontFamily: on ? F.textSemi : F.text, fontSize: 15, color: C.ink, ...T.tnum }}>
        {on ? '✓ ' : ''}
        {label}
      </Text>
    </Pressable>
  );
}

/** A row of equal segments with an ink border (condition, shop for). */
export function Segments<K extends string>({
  options,
  isOn,
  onPick,
}: {
  options: { id: K; label: string }[];
  isOn: (id: K) => boolean;
  onPick: (id: K) => void;
}) {
  return (
    <View style={{ flexDirection: 'row', borderWidth: 1.5, borderColor: C.ink, borderRadius: 2, overflow: 'hidden' }}>
      {options.map((o, i) => {
        const on = isOn(o.id);
        return (
          <Pressable
            key={o.id}
            accessibilityRole="button"
            accessibilityState={{ selected: on }}
            onPress={() => onPick(o.id)}
            style={{
              flex: 1,
              minHeight: 44,
              alignItems: 'center',
              justifyContent: 'center',
              backgroundColor: on ? C.ink : C.slip,
              borderLeftWidth: i ? 1.5 : 0,
              borderLeftColor: C.ink,
            }}>
            <Text style={{ fontFamily: on ? F.textSemi : F.text, fontSize: 15, color: on ? '#FFFFFF' : C.ink }}>
              {o.label}
            </Text>
          </Pressable>
        );
      })}
    </View>
  );
}

export function SectionHead({
  title,
  sub,
  action,
  onAction,
}: {
  title: string;
  sub?: string;
  action?: string;
  onAction?: () => void;
}) {
  return (
    <View style={{ paddingHorizontal: GUTTER, flexDirection: 'row', alignItems: 'flex-end', justifyContent: 'space-between' }}>
      <View style={{ flexShrink: 1, gap: 4 }}>
        <Text style={T.h2}>{title}</Text>
        {sub ? <Text style={T.label}>{sub}</Text> : null}
      </View>
      {action && onAction ? <TextLink label={action} onPress={onAction} /> : null}
    </View>
  );
}

export function TextLink({ label, onPress, style }: { label: string; onPress: () => void; style?: StyleProp<TextStyle> }) {
  return (
    <Pressable accessibilityRole="link" onPress={onPress} hitSlop={8} style={{ paddingVertical: 8 }}>
      <Text style={[T.link, style]}>{label}</Text>
    </Pressable>
  );
}

/** "Prices from Data by Keepa · No affiliate links": wherever deal data shows (D19). */
export function KeepaLine({ style }: { style?: StyleProp<ViewStyle> }) {
  return (
    <View style={[{ paddingHorizontal: GUTTER, paddingVertical: 16, flexDirection: 'row', flexWrap: 'wrap' }, style]}>
      <Text style={T.small}>Prices from </Text>
      <Text style={[T.small, { fontFamily: F.textSemi, color: C.stamp }]} onPress={() => Linking.openURL('https://keepa.com')}>
        Data by Keepa
      </Text>
      <Text style={T.small}> · No affiliate links</Text>
    </View>
  );
}

export function Loading() {
  return (
    <View style={{ padding: 40, alignItems: 'center' }}>
      <ActivityIndicator color={C.stamp} />
    </View>
  );
}

export function ErrorState({ onRetry }: { onRetry: () => void }) {
  return (
    <View style={{ padding: GUTTER, gap: 10 }}>
      <View style={{ alignSelf: 'flex-start', backgroundColor: C.warnTint, borderWidth: 1.5, borderColor: C.warn, paddingHorizontal: 8 }}>
        <Text style={[T.label, { color: C.warnInk }]}>COULDN'T LOAD</Text>
      </View>
      <Text style={T.bodyStrong}>We couldn't reach the shelves</Text>
      <Text style={T.small}>Check your connection and try again.</Text>
      <Button label="Try again" kind="ink" onPress={onRetry} style={{ alignSelf: 'flex-start' }} />
    </View>
  );
}

export function Empty({ title, line, action, onAction }: { title: string; line?: string; action?: string; onAction?: () => void }) {
  return (
    <View style={{ padding: GUTTER, gap: 10 }}>
      <View
        style={{
          alignSelf: 'flex-start',
          borderWidth: 4,
          borderColor: C.stamp,
          paddingHorizontal: 10,
          transform: [{ rotate: '-6deg' }],
          marginVertical: 8,
        }}>
        <Text style={{ fontFamily: F.display, fontSize: 28, color: C.stamp }}>CHECKED</Text>
      </View>
      <Text style={T.bodyStrong}>{title}</Text>
      {line ? <Text style={T.small}>{line}</Text> : null}
      {action && onAction ? <Button label={action} kind="ink" onPress={onAction} style={{ alignSelf: 'flex-start' }} /> : null}
    </View>
  );
}

export function BackLink({ label }: { label: string }) {
  return <TextLink label={`‹ ${label}`} onPress={() => (router.canGoBack() ? router.back() : router.replace('/'))} style={{ fontSize: 17 }} />;
}

export const s = StyleSheet.create({
  screen: { flex: 1, backgroundColor: C.ground },
  hair: { height: 1, backgroundColor: C.ruleSoft },
  tear: { borderTopWidth: 1, borderStyle: 'dashed', borderColor: C.rule },
  panel: { backgroundColor: C.slip },
});
