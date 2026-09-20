"use client";

import { Check } from "lucide-react";
import { cn } from "@/lib/utils";

export interface LoopStage {
  id: string;
  label: string;
  /** done = happened for this learner; current = the stage the learner is in; todo = not yet */
  state: "done" | "current" | "todo";
  hint: string;
}

/**
 * LoopRibbon: EduPath's adaptive loop as one continuous line. Stage states
 * come from the learner's real data (evidence exists, a plan exists, a
 * reflection revision exists...), never from a script. It is a sequence, so
 * the order is the information.
 */
export function LoopRibbon({ stages, className, compact = false }: { stages: LoopStage[]; className?: string; compact?: boolean }) {
  return (
    <ol className={cn("grid grid-cols-5 gap-y-4 md:flex md:items-start md:gap-0 md:overflow-x-auto md:pb-1 scroll-fine", className)} aria-label="The adaptive loop">
      {stages.map((s, i) => (
        <li key={s.id} className={cn("relative flex flex-col gap-1.5 md:min-w-[5.5rem] md:flex-1", i === stages.length - 1 && "md:min-w-[4.5rem] md:flex-none")} aria-current={s.state === "current" ? "step" : undefined}>
          <div className="flex items-center">
            <span
              className={cn(
                "grid size-5 shrink-0 place-items-center border text-[0.6875rem]",
                s.state === "done" && "border-ink bg-ink text-paper",
                s.state === "current" && "border-revision bg-paper text-revision",
                s.state === "todo" && "border-rule-strong bg-paper text-transparent",
              )}
              aria-hidden
            >
              {s.state === "done" ? <Check className="size-3" strokeWidth={3} /> : s.state === "current" ? <span className="size-1.5 bg-revision" /> : "."}
            </span>
            {i < stages.length - 1 && (
              <span className={cn("hidden h-px flex-1 md:block", s.state === "done" ? "bg-ink" : "bg-rule-strong")} style={s.state === "todo" ? { backgroundImage: "repeating-linear-gradient(90deg,var(--rule-strong) 0 4px,transparent 4px 8px)", backgroundColor: "transparent" } : undefined} aria-hidden />
            )}
          </div>
          <span className={cn("pr-1 text-[0.75rem] leading-tight [overflow-wrap:anywhere] hyphens-auto md:pr-2 md:text-[0.8125rem]", s.state === "current" ? "font-bold text-ink" : s.state === "done" ? "font-semibold text-ink" : "text-ink-3")}>
            {s.label}
            <span className="sr-only">
              {" "}
              ({s.state === "done" ? "done" : s.state === "current" ? "current stage" : "not yet"})
            </span>
          </span>
          {!compact && <span className="hidden pr-3 text-[0.75rem] leading-snug text-ink-3 xl:block">{s.hint}</span>}
        </li>
      ))}
    </ol>
  );
}
