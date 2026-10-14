import { usualParts } from "@/lib/format";
import type { Deal } from "@/lib/types";

/** "usually $X · save $Y", each half kept on one line. */
export function Usual({ d }: { d: Deal }) {
  const parts = usualParts(d);
  if (!parts.length) return null;
  return (
    <span className="usual tnum">
      <span className="nw">{parts[0]}</span> · <span className="nw">{parts[1]}</span>
    </span>
  );
}
