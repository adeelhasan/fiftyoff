import type { ReactNode } from "react";

/** The legal layout (Account design): an "On this page" nav, a 56px title, a "Last updated" line, the short
 * version, then sections. Placeholder text until the real copy comes (web.md). */
export function Legal({
  title,
  updated,
  short,
  sections,
}: {
  title: string;
  updated: string;
  short: ReactNode;
  sections: { id: string; title: string; body: ReactNode }[];
}) {
  return (
    <div className="legal">
      <nav aria-label="On this page">
        <span className="mono" style={{ marginBottom: 6 }}>
          ON THIS PAGE
        </span>
        {sections.map((s) => (
          <a key={s.id} href={`#${s.id}`}>
            {s.title}
          </a>
        ))}
      </nav>
      <article>
        <h1 className="page-title">{title}</h1>
        <span className="mono mono-13 ink2">LAST UPDATED {updated}</span>
        <div className="short">
          <span className="mono">THE SHORT VERSION</span>
          {short}
        </div>
        {sections.map((s) => (
          <div key={s.id} id={s.id} style={{ display: "flex", flexDirection: "column", gap: 10 }}>
            <h2>{s.title}</h2>
            {s.body}
          </div>
        ))}
      </article>
    </div>
  );
}
