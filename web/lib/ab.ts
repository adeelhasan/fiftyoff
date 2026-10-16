// trust-first measure (D56): one A/B arm per device and test, kept in localStorage. Nothing leaves the device but the
// letters, on /d/ links, deal opens and page-view counts.
// - tagline: "a" is the new tagline, "b" the old one.
export type Arm = "a" | "b";

function pick(key: string): Arm | "" {
  try {
    let v = localStorage.getItem(key);
    if (v !== "a" && v !== "b") {
      v = Math.random() < 0.5 ? "a" : "b";
      localStorage.setItem(key, v);
    }
    return v as Arm;
  } catch {
    return "";
  }
}

/** The tagline arm. */
export function arm(): Arm | "" {
  return pick("fo:ab:tagline");
}

/** What the logs get: the tagline arm. (D64's featured-layout test ended 10-15 with the plain row; its rows carry two
 * letters, tagline then featured.) */
export function variant(): string {
  return arm();
}
