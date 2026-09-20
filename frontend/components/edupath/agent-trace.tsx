"use client";

import { AlertOctagon, CheckCircle2, CircleDashed, CircleDot, GitBranch, Radio } from "lucide-react";
import { AnimatePresence, motion, useReducedMotion } from "motion/react";
import type { TraceRun } from "@/lib/trace-store";
import type { TraceKind } from "@/lib/types";
import { cn } from "@/lib/utils";
import { EmptyState } from "./states";

const KIND_META: Record<TraceKind, { label: string; icon: typeof CircleDot; tone: "ink" | "verified" | "revision" | "quiet" }> = {
  input: { label: "Input", icon: CircleDot, tone: "quiet" },
  tool_call: { label: "Tool", icon: CircleDot, tone: "quiet" },
  graph_query: { label: "Graph", icon: GitBranch, tone: "ink" },
  retrieval: { label: "Retrieval", icon: CircleDot, tone: "ink" },
  decision: { label: "Decision", icon: CircleDot, tone: "ink" },
  validation: { label: "Check", icon: CheckCircle2, tone: "verified" },
  reflection: { label: "Reflection", icon: GitBranch, tone: "revision" },
  replan: { label: "Re-plan", icon: GitBranch, tone: "revision" },
  output: { label: "Output", icon: CircleDot, tone: "ink" },
  degraded: { label: "Fallback", icon: CircleDashed, tone: "quiet" },
  error: { label: "Error", icon: AlertOctagon, tone: "revision" },
};

const TONE_CLASS = { ink: "text-ink", verified: "text-verified", revision: "text-revision", quiet: "text-ink-2" } as const;

/**
 * AgentTrace: what the agents and services did during one run, as it
 * happened. Events arrive over SSE from the backend's own services (each
 * agent or deterministic service publishes what it decided). The vertical
 * rule is the run; the top event pulses while the run is still going.
 */
export function AgentTrace({ run, className, compact = false }: { run: TraceRun | undefined; className?: string; compact?: boolean }) {
  const reduce = useReducedMotion();
  if (!run) {
    return (
      <EmptyState title="No runs yet in this session" icon={Radio} className={className}>
        Upload a document, build a plan, or submit practice, and each agent&apos;s steps will appear here as they happen.
      </EmptyState>
    );
  }
  const t0 = run.events[0] ? new Date(run.events[0].ts).getTime() : run.startedAt;

  return (
    <div className={cn("plate", className)}>
      <div className="flex flex-wrap items-center justify-between gap-2 border-b border-rule-strong bg-plate/70 px-4 py-2.5">
        <p className="text-[0.9375rem] font-bold">{run.label}</p>
        <p className="inline-flex items-center gap-2 text-[0.8125rem] font-semibold text-ink-2" role="status" aria-live="polite">
          {run.status === "running" ? (
            <>
              <span className="relative grid size-2.5 place-items-center" aria-hidden>
                <span className="absolute size-2.5 animate-ping border border-revision opacity-60" />
                <span className="size-1.5 bg-revision" />
              </span>
              Running
            </>
          ) : run.status === "error" ? (
            <span className="text-revision">Run failed</span>
          ) : (
            "Run finished"
          )}
        </p>
      </div>
      {run.events.length === 0 ? (
        <p className="p-4 text-[0.875rem] text-ink-2">
          {run.streamFailed
            ? "The live event stream could not be opened, so no steps are shown. The action itself is unaffected."
            : run.status === "running"
              ? "Waiting for the first step."
              : "This run published no trace events."}
        </p>
      ) : (
        <ol className={cn("relative py-2", compact ? "px-3" : "px-4")}>
          <span className="absolute bottom-4 left-[1.625rem] top-4 w-px bg-rule-strong" aria-hidden />
          <AnimatePresence initial={false}>
            {run.events.map((e, i) => {
              const meta = KIND_META[e.kind] ?? KIND_META.output;
              const Icon = meta.icon;
              const last = i === run.events.length - 1 && run.status === "running";
              const dt = Math.max(0, new Date(e.ts).getTime() - t0) / 1000;
              return (
                <motion.li
                  key={e.step_id}
                  initial={reduce ? false : { opacity: 0, x: -8 }}
                  animate={{ opacity: 1, x: 0 }}
                  transition={{ duration: 0.22, ease: [0.16, 1, 0.3, 1] }}
                  className="relative grid grid-cols-[2.25rem_minmax(0,1fr)] gap-x-2 py-2"
                >
                  <span className="relative z-10 mt-0.5 grid size-6 place-items-center self-start bg-paper">
                    <Icon className={cn("size-[18px]", TONE_CLASS[meta.tone], last && "animate-pulse")} aria-hidden />
                  </span>
                  <div className="min-w-0">
                    <p className="flex flex-wrap items-baseline gap-x-2 text-[0.9375rem]">
                      <span className="font-bold">{e.agent_or_service}</span>
                      <span className={cn("text-[0.75rem] font-semibold", TONE_CLASS[meta.tone])}>{meta.label}</span>
                      <span className="draft ml-auto text-[0.8125rem] text-ink-3">+{dt.toFixed(1)}s</span>
                    </p>
                    <p className="max-w-[70ch] text-[0.875rem] leading-snug text-ink-2">{e.summary}</p>
                  </div>
                </motion.li>
              );
            })}
          </AnimatePresence>
        </ol>
      )}
    </div>
  );
}
