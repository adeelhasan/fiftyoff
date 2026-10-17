// EXPO_PUBLIC_* values are bundled into the app: public addresses and publishable keys only, never a secret.
export const API_BASE = (process.env.EXPO_PUBLIC_API_BASE ?? 'https://beta.fiftyoff.app/api/v1').replace(/\/$/, '');

/** The site that serves /d/ (the Amazon redirect), /deal/ pages and the legal pages. */
export const SITE = (process.env.EXPO_PUBLIC_SITE ?? 'https://beta.fiftyoff.app').replace(/\/$/, '');

/** Every surface the app logs is ios-prefixed, so click and open rows tell the app from the web. */
export const SURFACE = 'ios';
