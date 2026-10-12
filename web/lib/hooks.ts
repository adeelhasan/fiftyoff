"use client";
import { useCallback, useEffect, useState, useSyncExternalStore } from "react";
import { api } from "./api";
import type { Shelf } from "./types";

export interface Loaded<T> {
  data: T | null;
  error: unknown;
  loading: boolean;
  retry: () => void;
}

/** Fetch on mount and whenever `key` changes. Keeps the last good data while reloading or after an error. */
export function useApi<T>(load: () => Promise<T>, key: string): Loaded<T> {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [loading, setLoading] = useState(true);
  const [attempt, setAttempt] = useState(0);
  useEffect(() => {
    let live = true;
    setLoading(true);
    setError(null);
    load()
      .then((d) => live && setData(d))
      .catch((e) => live && setError(e))
      .finally(() => live && setLoading(false));
    return () => {
      live = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key, attempt]);
  const retry = useCallback(() => setAttempt((n) => n + 1), []);
  return { data, error, loading, retry };
}

let shelvesPromise: Promise<Map<string, Shelf>> | null = null;

/** Shelf id -> Shelf, fetched once per page load; cards carry only the shelf id. */
export function useShelves(): Map<string, Shelf> | null {
  const [m, setM] = useState<Map<string, Shelf> | null>(null);
  useEffect(() => {
    shelvesPromise ??= api
      .shelves()
      .then((r) => new Map(r.shelves.map((s) => [s.id, s])))
      .catch(() => {
        shelvesPromise = null;
        return new Map();
      });
    let live = true;
    shelvesPromise.then((x) => live && setM(x));
    return () => {
      live = false;
    };
  }, []);
  return m;
}

/** Re-render every minute so "40 min ago" stays true. */
export function useNow(): number {
  return useSyncExternalStore(
    (cb) => {
      const t = setInterval(cb, 60_000);
      return () => clearInterval(t);
    },
    () => Math.floor(Date.now() / 60_000) * 60_000,
    () => 0,
  );
}

/** One id from the URL: the path segment after `prefix` (/shelf/gaming-gear/), else `?id=`. */
export function useIdFromUrl(prefix: string): string | null | undefined {
  const [id, setId] = useState<string | null | undefined>(undefined); // undefined until mounted
  useEffect(() => {
    const seg = location.pathname.split("/").filter(Boolean);
    const fromPath = seg[0] === prefix && seg[1] && seg[1] !== "_" ? decodeURIComponent(seg[1]) : null;
    setId(fromPath ?? new URLSearchParams(location.search).get("id"));
  }, [prefix]);
  return id;
}
