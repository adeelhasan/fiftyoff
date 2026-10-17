import { useCallback, useEffect, useRef, useState } from 'react';

export interface Loaded<T> {
  data: T | null;
  error: Error | null;
  loading: boolean;
  reload: () => void;
}

// A short in-memory cache so going back to a screen shows its last data at once while it refreshes.
const cache = new Map<string, unknown>();

/** Load `fn()` for `key`; a new key loads again. `key` null = don't load yet. State is only set when a request
 * settles; "loading" is derived from which key the last result belongs to. */
export function useApi<T>(key: string | null, fn: () => Promise<T>): Loaded<T> {
  const [res, setRes] = useState<{ key: string; n: number; data: T | null; error: Error | null } | null>(null);
  const [n, setN] = useState(0);
  const fnRef = useRef(fn);
  useEffect(() => {
    fnRef.current = fn;
  });

  useEffect(() => {
    if (!key) return;
    let live = true;
    fnRef
      .current()
      .then((data) => {
        cache.set(key, data);
        if (live) setRes({ key, n, data, error: null });
      })
      .catch((error: Error) => live && setRes({ key, n, data: null, error }));
    return () => {
      live = false;
    };
  }, [key, n]);

  const reload = useCallback(() => setN((x) => x + 1), []);
  const current = res && res.key === key ? res : null;
  const data = (current?.data ?? (key ? (cache.get(key) as T | undefined) : undefined)) ?? null;
  return { data, error: current?.error ?? null, loading: !!key && (!current || current.n !== n), reload };
}

export interface Paged<T> {
  items: T[];
  total: number | null;
  error: boolean;
  busy: boolean;
  more: () => void;
  retry: () => void;
}

/** A list that loads page by page for `key` (filters); a new key starts again from the first page. */
export function usePaged<T>(key: string | null, page: (offset: number) => Promise<{ items: T[]; total: number }>): Paged<T> {
  const [st, setSt] = useState<{ key: string; items: T[]; total: number | null; error: boolean; want: number; got: number }>({
    key: '',
    items: [],
    total: null,
    error: false,
    want: 0,
    got: -1,
  });
  const [n, setN] = useState(0);
  const pageRef = useRef(page);
  useEffect(() => {
    pageRef.current = page;
  });
  const fresh = st.key === key;
  const want = fresh ? st.want : 0;

  useEffect(() => {
    if (!key) return;
    let live = true;
    pageRef
      .current(want)
      .then((r) => {
        if (!live) return;
        setSt((p) => {
          const base = p.key === key ? p.items.slice(0, want) : [];
          return { key, items: [...base, ...r.items], total: r.total, error: false, want, got: want };
        });
      })
      .catch(() => live && setSt((p) => ({ ...(p.key === key ? p : { items: [], total: null }), key, error: true, want, got: want })));
    return () => {
      live = false;
    };
  }, [key, want, n]);

  const items = fresh ? st.items : [];
  const total = fresh ? st.total : null;
  const busy = !!key && (!fresh || st.got !== want) && !(fresh && st.error);
  return {
    items,
    total,
    error: fresh && st.error,
    busy,
    more: () => {
      if (fresh && !busy && total !== null && items.length < total) setSt((p) => ({ ...p, want: items.length }));
    },
    retry: () => setN((x) => x + 1),
  };
}
