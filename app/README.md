# fiftyOff iOS app (Expo / React Native)

Plan and status: `../docs/handoffs/mobile-app.md`. Screens: `../design/ios-v0.7/`. Server work it waits for:
`../docs/handoffs/web-api-for-mobile.md`.

```bash
npm install
npx expo start            # scan the QR code with the iPhone camera; opens in Expo Go
npx tsc --noEmit && npx eslint src && npx expo-doctor
```

Web preview (for quick checks only; the beta API sends no CORS headers, so a local proxy adds them):

```bash
node scripts/dev-proxy.mjs &
EXPO_PUBLIC_API_BASE=http://localhost:8787/api/v1 npx expo start --web
```

- `src/app/`: routes (Expo Router). Tabs: Today, All deals, Alerts, Settings. Pushed: deal, shelf, search, sizes.
  Modals: onboarding (4 steps), alert sheet, sign-in.
- `src/lib/`: `api.ts` (the one /api/v1 client), `types.ts` (mirrors `web/lib/types.ts`), `prefs.tsx` (picks kept on
  the phone), `session.tsx` (the sign-in / Head start seam: Clerk and RevenueCat plug in there, M3), `tokens.ts`.
- Config: `EXPO_PUBLIC_API_BASE` (default `https://beta.fiftyoff.app/api/v1`), `EXPO_PUBLIC_SITE`.
