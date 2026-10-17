// Mirrors design/tokens/tokens.css ("Returns Desk"). Light theme only in v1; the dark values are in the CSS.
import type { TextStyle } from 'react-native';

export const C = {
  ground: '#E6E6E2',
  slip: '#FFFFFF',
  slipMuted: '#F1F1EE',
  ink: '#222326',
  ink2: '#45464A',
  rule: '#B5B5AE',
  ruleSoft: '#ECECE8',
  stamp: '#4B3BA6',
  stampPressed: '#3A2C96',
  stampDeep: '#2B1F8C',
  stampTint: '#ECE9FA',
  stampMuted: '#6F64A8',
  stampBacking: 'rgba(255,255,255,0.85)',
  kraft: '#D9BC92',
  kraftInk: '#2A1E10',
  good: '#2E7D32',
  goodTint: '#E5F2E5',
  goodInk: '#1F5A22',
  warn: '#9A6700',
  warnTint: '#FFF6E0',
  warnInk: '#6E4A00',
  gone: '#7A7A75',
  goneTint: '#ECECE8',
  goneInk: '#5E5E59',
  scrim: 'rgba(34,35,38,0.45)',
} as const;

export const F = {
  display: 'BigShoulders_900Black',
  text: 'IBMPlexSans_400Regular',
  textSemi: 'IBMPlexSans_600SemiBold',
  textBold: 'IBMPlexSans_700Bold',
  mono: 'IBMPlexMono_600SemiBold',
  grade: 'PermanentMarker_400Regular',
} as const;

const tnum: TextStyle = { fontVariant: ['tabular-nums'] };

/** Type roles from design/README.md, sized for phones. No readable text under 14 except caps mono labels (12). */
export const T = {
  // Big Shoulders has tall caps: a line height below ~1.12x the size clips the tops on iOS.
  title: { fontFamily: F.display, fontSize: 44, lineHeight: 50, color: C.ink, textTransform: 'uppercase' },
  h2: { fontFamily: F.display, fontSize: 30, lineHeight: 34, color: C.ink, textTransform: 'uppercase' },
  h3: { fontFamily: F.display, fontSize: 26, lineHeight: 30, color: C.ink, textTransform: 'uppercase' },
  body: { fontFamily: F.text, fontSize: 16, lineHeight: 23, color: C.ink },
  bodyStrong: { fontFamily: F.textSemi, fontSize: 16, lineHeight: 23, color: C.ink },
  small: { fontFamily: F.text, fontSize: 14, lineHeight: 20, color: C.ink2 },
  smallStrong: { fontFamily: F.textSemi, fontSize: 14, lineHeight: 20, color: C.ink },
  label: { fontFamily: F.mono, fontSize: 12, letterSpacing: 0.8, color: C.ink2, textTransform: 'uppercase' },
  link: { fontFamily: F.textSemi, fontSize: 15, color: C.stamp },
  price: { fontFamily: F.textBold, fontSize: 17, color: C.ink, ...tnum },
  tnum,
} satisfies Record<string, TextStyle>;

export const GUTTER = 16;
