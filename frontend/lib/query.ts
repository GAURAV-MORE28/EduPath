"use client";

/**
 * A tiny query cache (no dependency): one shared entry per key, in-flight
 * de-duplication, explicit invalidation after mutations. Enough for this
 * app's fifteen read endpoints; every screen handles idle/loading/ready/error
 * from the same shape (see docs/FRONTEND_DESIGN_SYSTEM.md, "API state").
 */
import { useCallback, useEffect, useSyncExternalStore } from "react";
import { ApiError } from "./api-client";

export type QueryStatus = "loading" | "ready" | "error";

interface Entry<T = unknown> {
  status: QueryStatus;
  data?: T;
  error?: ApiError | Error;
  fetching: boolean;
  stale: boolean;
}

const entries = new Map<string, Entry>();
const inflight = new Map<string, Promise<void>>();
const fetchers = new Map<string, () => Promise<unknown>>();
const listeners = new Set<() => void>();
const mounted = new Map<string, number>();

function emit() {
  listeners.forEach((l) => l());
}

function run(key: string) {
  const fetcher = fetchers.get(key);
  if (!fetcher || inflight.has(key)) return;
  const prev = entries.get(key);
  entries.set(key, { ...(prev ?? { status: "loading" as const }), status: prev?.data !== undefined ? prev.status : "loading", fetching: true, stale: false });
  emit();
  const p = fetcher()
    .then((data) => {
      entries.set(key, { status: "ready", data, fetching: false, stale: false });
    })
    .catch((error: unknown) => {
      const prevEntry = entries.get(key);
      entries.set(key, {
        status: "error",
        data: prevEntry?.data,
        error: error instanceof Error ? error : new Error(String(error)),
        fetching: false,
        stale: false,
      });
    })
    .finally(() => {
      inflight.delete(key);
      emit();
    });
  inflight.set(key, p);
}

/** Mark entries whose key starts with `prefix` stale and refetch the mounted ones. */
export function invalidate(prefix = "") {
  for (const [key, entry] of entries) {
    if (!key.startsWith(prefix)) continue;
    entries.set(key, { ...entry, stale: true });
    if ((mounted.get(key) ?? 0) > 0) run(key);
  }
  emit();
}

/** Drop every cached entry (e.g. after a new profile replaces the old one). */
export function resetQueries() {
  entries.clear();
  emit();
}

const EMPTY: Entry = { status: "loading", fetching: false, stale: false };

export function useQuery<T>(key: string | null, fetcher: () => Promise<T>) {
  const subscribe = useCallback((cb: () => void) => {
    listeners.add(cb);
    return () => {
      listeners.delete(cb);
    };
  }, []);
  const entry = useSyncExternalStore(
    subscribe,
    () => (key ? (entries.get(key) ?? EMPTY) : EMPTY),
    () => EMPTY,
  ) as Entry<T>;

  useEffect(() => {
    if (!key) return;
    fetchers.set(key, fetcher);
    mounted.set(key, (mounted.get(key) ?? 0) + 1);
    const current = entries.get(key);
    if (!current || current.stale || current.status === "error") run(key);
    return () => {
      mounted.set(key, Math.max(0, (mounted.get(key) ?? 1) - 1));
    };
    // fetcher identity is intentionally not a dependency: the key names the data.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key]);

  const reload = useCallback(() => {
    if (key) {
      fetchers.set(key, fetcher);
      run(key);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key]);

  return {
    data: entry.data,
    error: entry.error,
    status: (key ? entry.status : "loading") as QueryStatus,
    isFetching: entry.fetching,
    reload,
  };
}
