// trust-first measure (D56): one A/B arm per device, kept in localStorage. "a" is the new tagline, "b" the old one.
// Nothing leaves the device but the letter, on /d/ links and page-view counts.
export type Arm = "a" | "b";
const KEY = "fo:ab:tagline";

export function arm(): Arm | "" {
  try {
    let v = localStorage.getItem(KEY);
    if (v !== "a" && v !== "b") {
      v = Math.random() < 0.5 ? "a" : "b";
      localStorage.setItem(KEY, v);
    }
    return v as Arm;
  } catch {
    return "";
  }
}
