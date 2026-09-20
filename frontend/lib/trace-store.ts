"use client";

/**
 * Live agent trace. `traced()` wraps a backend call: it generates a run id,
 * subscribes to `GET /api/runs/{run_id}/events` (SSE) *before* the call so no
 * event is missed, passes the id to the call as `X-Run-Id`, and keeps the
 * stream open briefly after the call resolves so late events land. Every
 * event shown in the UI comes off that stream, published by the backend's
 * own services; nothing here is scripted.
 */
import { useSyncExternalStore } from "react";
import { api } from "./api-client";
import type { TraceEvent, TraceKind } from "./types";

export interface TraceRun {
  runId: string;
  label: string;
  startedAt: number;
  status: "running" | "done" | "error";
  events: TraceEvent[];
  /** The stream never opened (backend unreachable or blocked): say so, don't fake events. */
  streamFailed: boolean;
}

const KINDS: TraceKind[] = [
  "input",
  "tool_call",
  "graph_query",
  "retrieval",
  "decision",
  "validation",
  "reflection",
  "replan",
  "output",
  "degraded",
  "error",
];

const MAX_RUNS = 12;
let runs: TraceRun[] = [];
const listeners = new Set<() => void>();

function emit() {
  runs = [...runs];
  listeners.forEach((l) => l());
}

function update(runId: string, fn: (run: TraceRun) => void) {
  const run = runs.find((r) => r.runId === runId);
  if (run) {
    fn(run);
    emit();
  }
}

function newRunId() {
  return typeof crypto !== "undefined" && "randomUUID" in crypto
    ? crypto.randomUUID()
    : `run-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 10)}`;
}

const LINGER_MS = 700;

export async function traced<T>(label: string, work: (runId: string) => Promise<T>): Promise<T> {
  const runId = newRunId();
  const run: TraceRun = { runId, label, startedAt: Date.now(), status: "running", events: [], streamFailed: false };
  runs = [run, ...runs].slice(0, MAX_RUNS);
  emit();

  let source: EventSource | null = null;
  if (typeof EventSource !== "undefined") {
    source = new EventSource(api.runEventsUrl(runId), { withCredentials: true });
    const onEvent = (message: MessageEvent<string>) => {
      try {
        const event = JSON.parse(message.data) as TraceEvent;
        if (!event.step_id) return; // keep-alive ping
        update(runId, (r) => {
          if (!r.events.some((e) => e.step_id === event.step_id)) r.events = [...r.events, event];
        });
      } catch {
        // ignore malformed frames
      }
    };
    KINDS.forEach((kind) => source!.addEventListener(kind, onEvent as EventListener));
    source.onerror = () => update(runId, (r) => (r.streamFailed = r.events.length === 0));
  }

  try {
    const result = await work(runId);
    update(runId, (r) => (r.status = "done"));
    return result;
  } catch (error) {
    update(runId, (r) => (r.status = "error"));
    throw error;
  } finally {
    setTimeout(() => source?.close(), LINGER_MS);
  }
}

export function useTraceRuns(): TraceRun[] {
  return useSyncExternalStore(
    (cb) => {
      listeners.add(cb);
      return () => {
        listeners.delete(cb);
      };
    },
    () => runs,
    () => [] as TraceRun[],
  );
}
