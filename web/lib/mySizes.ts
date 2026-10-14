// D59: the visitor's clothing and shoe sizes, kept on this device only (never sent anywhere but the /sized query).
import type { MySizes } from "./types";

const KEY = "fiftyoff.sizes.v1";
export const NO_SIZES: MySizes = { letter: [], num: [], waist: [], length: [], shoe: [] };

export function loadSizes(): MySizes | null {
  try {
    const v = JSON.parse(localStorage.getItem(KEY) ?? "null");
    return v && typeof v === "object" ? { ...NO_SIZES, ...v } : null;
  } catch {
    return null;
  }
}

export function saveSizes(m: MySizes): void {
  try {
    localStorage.setItem(KEY, JSON.stringify(m));
  } catch {
    /* private mode: the choice lasts for this visit */
  }
}

export function anySizes(m: MySizes | null): boolean {
  return !!m && Object.values(m).some((x) => x.length > 0);
}

/** The picker's group id + value -> where it lives in MySizes ("shoe-men", "10.5" -> shoe "men-10.5"). */
export function slot(group: string, v: string): [keyof MySizes, string] {
  return group.startsWith("shoe-") ? ["shoe", `${group.slice(5)}-${v}`] : [group as keyof MySizes, v];
}

export function describe(m: MySizes): string {
  const who: Record<string, string> = { men: "Men's", women: "Women's", kids: "Kids" };
  return [
    ...m.letter,
    ...m.num.map((v) => `Size ${v}`),
    ...m.waist.map((v) => `Waist ${v}`),
    ...m.length.map((v) => `Inseam ${v}`),
    ...m.shoe.map((s) => {
      const [w, v] = s.split("-");
      return `${who[w] ?? w} shoe ${v}`;
    }),
  ].join(" · ");
}
