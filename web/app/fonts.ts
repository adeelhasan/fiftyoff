// "Big Shoulders Display" is now Google's "Big Shoulders" family (display optical size).
// Self-hosted at build time by next/font, so pages make no third-party font calls and fallbacks are size-matched.
import { Big_Shoulders, IBM_Plex_Mono, IBM_Plex_Sans, Permanent_Marker } from "next/font/google";

// Big Shoulders has no size-matched fallback in next/font, so it blocks briefly rather than swapping (no shift).
export const display = Big_Shoulders({ weight: ["900"], subsets: ["latin"], variable: "--font-display", display: "block" });
export const text = IBM_Plex_Sans({ weight: ["400", "600", "700"], subsets: ["latin"], variable: "--font-text", display: "swap" });
export const mono = IBM_Plex_Mono({ weight: ["600"], subsets: ["latin"], variable: "--font-mono", display: "swap" });
export const grade = Permanent_Marker({ weight: ["400"], subsets: ["latin"], variable: "--font-grade", display: "swap", preload: false });
