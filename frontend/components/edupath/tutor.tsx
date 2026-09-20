"use client";

import { ShieldCheck } from "lucide-react";
import { humanizeId } from "@/lib/format";
import { cn } from "@/lib/utils";
import { CitationBadge } from "./evidence";

export interface TutorTurn {
  id: string;
  role: "learner" | "tutor";
  text: string;
  citations?: string[];
  conservative?: boolean;
  degraded?: boolean;
  pending?: boolean;
  error?: string;
}

function citationLabel(id: string, labelFor: (s: string) => string): { kind: "evidence" | "assessment" | "decision" | "graph" | "resource"; label: string } {
  if (id.startsWith("skill.")) return { kind: "graph", label: labelFor(id) };
  if (id.startsWith("res.")) return { kind: "resource", label: humanizeId(id) };
  if (id.startsWith("item.")) {
    const m = /^item\.(.+)\.(\d+)$/.exec(id);
    return { kind: "assessment", label: m ? `${labelFor(`skill.${m[1]}`)}, question ${m[2]}` : id };
  }
  if (/^[0-9a-f-]{36}$/i.test(id)) return { kind: "evidence", label: `Record ${id.slice(0, 8)}` };
  return { kind: "evidence", label: humanizeId(id) };
}

/**
 * TutorMessage: one turn. Tutor answers carry the records they cite, so a
 * learner can see what the answer stands on; a conservative answer says it
 * was built directly from those records with no model wording.
 */
export function TutorMessage({ turn, labelFor }: { turn: TutorTurn; labelFor: (s: string) => string }) {
  const mine = turn.role === "learner";
  return (
    <article className={cn("flex", mine ? "justify-end" : "justify-start")} aria-label={mine ? "You" : "Tutor"}>
      <div className={cn("max-w-[min(100%,42rem)] space-y-2 border p-3.5 sm:p-4", mine ? "border-ink bg-ink text-paper" : "border-rule-strong bg-paper")}>
        <p className={cn("text-[0.75rem] font-semibold", mine ? "text-paper/70" : "text-ink-3")}>{mine ? "You" : "Tutor"}</p>
        {turn.pending ? (
          <p className="text-[0.9375rem] text-ink-2" role="status">
            Reading your records
            <span className="inline-flex w-6" aria-hidden>
              <span className="animate-pulse">…</span>
            </span>
          </p>
        ) : turn.error ? (
          <p className="text-[0.9375rem] font-semibold text-revision" role="alert">
            {turn.error}
          </p>
        ) : (
          <p className="whitespace-pre-line text-[0.9375rem] leading-relaxed">{turn.text}</p>
        )}
        {!mine && turn.citations && turn.citations.length > 0 && (
          <div className="space-y-1.5 border-t border-rule pt-2.5">
            <p className="inline-flex items-center gap-1.5 text-[0.8125rem] font-semibold text-ink-2">
              <ShieldCheck className="size-4 text-verified" aria-hidden /> Checked against {turn.citations.length} {turn.citations.length === 1 ? "record" : "records"}
            </p>
            <ul className="flex flex-wrap gap-1.5">
              {turn.citations.map((c) => {
                const { kind, label } = citationLabel(c, labelFor);
                return (
                  <li key={c} className="max-w-full">
                    <CitationBadge kind={kind} label={label} />
                  </li>
                );
              })}
            </ul>
          </div>
        )}
        {!mine && turn.conservative && (
          <p className="text-[0.8125rem] text-ink-2">Built directly from your records, with no model wording.</p>
        )}
      </div>
    </article>
  );
}
