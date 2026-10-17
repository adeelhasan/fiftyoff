// What the person chose, kept on this phone only (AsyncStorage): onboarding done, shelves first on Today, condition,
// who they shop for and their sizes (D59, D74, D75), and the weekly email address they gave.
import AsyncStorage from '@react-native-async-storage/async-storage';
import { createContext, use, useEffect, useState, type ReactNode } from 'react';

import type { CondPref } from './format';
import type { MySizes } from './types';

export const NO_SIZES: MySizes = { letter: [], num: [], waist: [], length: [], shoe: [] };

export interface Prefs {
  onboarded: boolean;
  shelves: string[]; // shelf ids, first on Today
  cond: CondPref;
  shopFor: { women: boolean; men: boolean };
  sizes: MySizes;
  weekly: { email: string; state: 'sent' | 'saved' } | null;
}

const DEFAULTS: Prefs = {
  onboarded: false,
  shelves: [],
  cond: 'good',
  shopFor: { women: false, men: false },
  sizes: NO_SIZES,
  weekly: null,
};

const KEY = 'fiftyoff.prefs.v1';

interface Ctx {
  prefs: Prefs;
  ready: boolean;
  set: (patch: Partial<Prefs>) => void;
  reset: () => void;
}

const PrefsContext = createContext<Ctx | null>(null);

export function PrefsProvider({ children }: { children: ReactNode }) {
  const [prefs, setPrefs] = useState<Prefs>(DEFAULTS);
  const [ready, setReady] = useState(false);

  useEffect(() => {
    AsyncStorage.getItem(KEY)
      .then((v) => {
        if (v) setPrefs({ ...DEFAULTS, ...JSON.parse(v) });
      })
      .catch(() => {})
      .finally(() => setReady(true));
  }, []);

  const save = (next: Prefs) => {
    setPrefs(next);
    AsyncStorage.setItem(KEY, JSON.stringify(next)).catch(() => {});
  };

  return (
    <PrefsContext
      value={{
        prefs,
        ready,
        set: (patch) => save({ ...prefs, ...patch }),
        reset: () => save(DEFAULTS),
      }}>
      {children}
    </PrefsContext>
  );
}

export function usePrefs(): Ctx {
  const c = use(PrefsContext);
  if (!c) throw new Error('usePrefs outside PrefsProvider');
  return c;
}

export const anySizes = (m: MySizes) => Object.values(m).some((x) => x.length > 0);

/** "Women's M · 8 · Women's shoe 8.5" */
export function describeSizes(m: MySizes): string {
  const who: Record<string, string> = { men: "Men's", women: "Women's", kids: 'Kids' };
  return [
    ...m.letter,
    ...m.num.map((v) => `Size ${v}`),
    ...m.waist.map((v) => `Waist ${v}`),
    ...m.length.map((v) => `Inseam ${v}`),
    ...m.shoe.map((s) => {
      const [w, v] = s.split('-');
      return `${who[w] ?? w} shoe ${v}`;
    }),
  ].join(' · ');
}
