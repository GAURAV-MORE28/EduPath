"use client";

import Link from "next/link";
import { useState } from "react";
import { AgentTrace } from "@/components/edupath/agent-trace";
import { useLearner } from "@/components/edupath/learner-context";
import { SheetHeader } from "@/components/edupath/sheet-header";
import { EmptyState } from "@/components/edupath/states";
import { CitationBadge } from "@/components/edupath/evidence";
import { OPERATOR_META } from "@/lib/format";
import { revisionLetter } from "@/lib/derived";
import { useRevisions } from "@/lib/hooks";
import { useTraceRuns } from "@/lib/trace-store";
import { cn } from "@/lib/utils";

export default function TracePage() {
  const runs = useTraceRuns();
  const { labelFor } = useLearner();
  const { data: revisions } = useRevisions();
  const [picked, setPicked] = useState<string>();
  const run = runs.find((r) => r.runId === picked) ?? runs[0];
  const decisions = (revisions ?? []).filter((r) => r.decision_id).sort((a, b) => b.revision_no - a.revision_no);

  return (
    <div className="space-y-8">
      <SheetHeader
        title="Agent trace"
        description="What each agent and service did, step by step, as it ran. Events stream from the backend while a request is in flight. Nothing here is replayed from a script."
      />

      <div className="grid gap-6 lg:grid-cols-[minmax(0,16rem)_minmax(0,1fr)]">
        <nav aria-label="Runs this session" className="space-y-2">
          <h2 className="text-lg font-bold">Runs this session</h2>
          {runs.length === 0 ? (
            <p className="text-[0.875rem] text-ink-2">None yet.</p>
          ) : (
            <ul className="plate reg">
              {runs.map((r) => (
                <li key={r.runId}>
                  <button
                    type="button"
                    onClick={() => setPicked(r.runId)}
                    aria-current={r.runId === run?.runId}
                    className={cn("w-full cursor-pointer px-3 py-2.5 text-left", r.runId === run?.runId ? "bg-plate font-bold" : "hover:bg-plate/60")}
                  >
                    <span className="block text-[0.9375rem]">{r.label}</span>
                    <span className="text-[0.8125rem] font-normal text-ink-2">
                      {r.events.length} {r.events.length === 1 ? "step" : "steps"} · {r.status === "running" ? "running" : r.status === "error" ? "failed" : "finished"}
                    </span>
                  </button>
                </li>
              ))}
            </ul>
          )}
        </nav>

        <div className="space-y-6">
          <AgentTrace run={run} />

          <section aria-labelledby="dec" className="space-y-2">
            <h2 id="dec" className="text-lg font-bold">Stored decisions</h2>
            <p className="max-w-[62ch] text-[0.875rem] text-ink-2">Every plan change EduPath makes keeps a decision record. These persist after a reload, unlike the live trace above.</p>
            {decisions.length === 0 ? (
              <EmptyState title="No decisions recorded yet">A decision record is written when a failed assessment changes your plan.</EmptyState>
            ) : (
              <ul className="plate reg">
                {decisions.map((r) => (
                  <li key={r.revision_id} className="flex flex-wrap items-center justify-between gap-3 p-4">
                    <div className="space-y-1">
                      <p className="text-[0.9375rem] font-bold">
                        Revision {revisionLetter(r.revision_no)}:{" "}
                        {r.operators.map((o) => OPERATOR_META[o.op]?.verb ?? o.op).join(", ")}
                        {r.operators[0]?.params?.skill_id ? ` (${labelFor(String(r.operators[0].params.skill_id))})` : ""}
                      </p>
                      <CitationBadge kind="decision" label={`Decision ${r.decision_id!.slice(0, 8)}`} />
                    </div>
                    <Link href="/dashboard/plan#moment" className="text-[0.875rem] font-semibold underline">
                      See why
                    </Link>
                  </li>
                ))}
              </ul>
            )}
          </section>
        </div>
      </div>
    </div>
  );
}
