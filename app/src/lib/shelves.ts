import { api } from './api';
import type { Shelf } from './types';
import { useApi } from './useApi';

/** Shelf id -> shelf, from /api/v1/shelves (cached). Cards carry only the id. */
export function useShelves(): Map<string, Shelf> {
  const { data } = useApi('shelves', api.shelves);
  return new Map((data?.shelves ?? []).map((s) => [s.id, s]));
}

export function shelfName(id: string, shelves: Map<string, Shelf>): string {
  return shelves.get(id)?.name ?? id.replace(/-/g, ' ').replace(/^./, (c) => c.toUpperCase());
}
