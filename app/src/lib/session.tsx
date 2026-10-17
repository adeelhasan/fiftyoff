// The sign-in and Head start seam (mobile-app.md M3). Screens read only this; Clerk (email code) and RevenueCat plug in
// here later, so nothing else imports them. Until then the session is signed out, and a development build can preview
// the other states from Settings.
import { createContext, use, useState, type ReactNode } from 'react';

export type Tier = 'signed-out' | 'free' | 'plus';

export interface Keyword {
  id: string;
  word: string;
  sentThisWeek: number;
  last: string | null;
}

export interface Session {
  tier: Tier;
  email: string | null;
  keywords: Keyword[];
  /** True while sign-in and purchases are stubs: screens say so instead of pretending. */
  stub: boolean;
}

interface Ctx {
  session: Session;
  /** Development only: preview a state without accounts. */
  preview: (tier: Tier) => void;
  signOut: () => void;
}

const SIGNED_OUT: Session = { tier: 'signed-out', email: null, keywords: [], stub: true };

const PREVIEW: Record<Tier, Session> = {
  'signed-out': SIGNED_OUT,
  free: { tier: 'free', email: 'you@example.com', keywords: [], stub: true },
  plus: {
    tier: 'plus',
    email: 'you@example.com',
    stub: true,
    keywords: [
      { id: '1', word: 'espresso', sentThisWeek: 2, last: 'Philips Baristina, 52% off, 2 d ago' },
      { id: '2', word: 'robot vacuum', sentThisWeek: 1, last: 'ECOVACS Deebot T30S, 73% off, 5 h ago' },
    ],
  },
};

const SessionContext = createContext<Ctx | null>(null);

export function SessionProvider({ children }: { children: ReactNode }) {
  const [session, setSession] = useState<Session>(SIGNED_OUT);
  return (
    <SessionContext value={{ session, preview: (t) => setSession(PREVIEW[t]), signOut: () => setSession(SIGNED_OUT) }}>
      {children}
    </SessionContext>
  );
}

export function useSession(): Ctx {
  const c = use(SessionContext);
  if (!c) throw new Error('useSession outside SessionProvider');
  return c;
}

export const KEYWORD_LIMIT = 10;
