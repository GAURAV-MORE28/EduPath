"use client";

import { ArrowRight, MessageSquareText } from "lucide-react";
import Link from "next/link";
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle } from "@/components/ui/sheet";
import { api } from "@/lib/api-client";
import { humanizeText } from "@/lib/format";
import { useEvidence } from "@/lib/hooks";
import { useQuery } from "@/lib/query";
import { CitationBadge, EvidenceCard } from "./evidence";
import { useLearner } from "./learner-context";
import { LoadingState } from "./states";

export interface WhySubject {
  title: string;
  /** Display text written by the planner or reflection (already a sentence). */
  reason?: string;
  skillId?: string;
  evidenceIds?: string[];
  graphPath?: string[] | null;
  decisionId?: string | null;
}

/** "assessment item 3 of backpropagation" from an id like item.backpropagation.3 */
function itemCitation(id: string, labelFor: (s: string) => string) {
  const m = /^item\.(.+)\.(\d+)$/.exec(id);
  return m ? `${labelFor(`skill.${m[1]}`)}, question ${m[2]}` : id;
}

/**
 * WhyDrawer: the answer to "why did the system do that?" Every claim points
 * at its evidence: uploaded text, assessment questions, the graph path, and
 * the stored decision record with the rules that fired.
 */
export function WhyDrawer({
  subject,
  open,
  onOpenChange,
}: {
  subject: WhySubject | null;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  const { labelFor } = useLearner();
  const { data: allEvidence } = useEvidence(open);
  const decision = useQuery(open && subject?.decisionId ? `decision:${subject.decisionId}` : null, () => api.decision(subject!.decisionId!));

  const ids = subject?.evidenceIds ?? decision.data?.evidence_ids ?? [];
  const evidenceCards = (allEvidence ?? []).filter((e) => ids.includes(e.evidence_id));
  const assessmentIds = ids.filter((id) => id.startsWith("item."));
  const graphPath = subject?.graphPath ?? decision.data?.graph_paths?.[0] ?? null;

  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent className="w-full max-w-none overflow-y-auto border-l border-rule-strong bg-paper sm:max-w-lg">
        <SheetHeader className="border-b border-rule p-5 pr-14">
          <SheetTitle className="text-xl font-bold">{subject?.title ?? "Why"}</SheetTitle>
          <SheetDescription className="text-[0.9375rem]">What the system decided, and what it based that on.</SheetDescription>
        </SheetHeader>
        <div className="space-y-6 p-5">
          {subject?.reason && (
            <section aria-labelledby="why-decision" className="space-y-2">
              <h3 id="why-decision" className="text-base font-bold">What it decided</h3>
              <p className="max-w-[60ch] text-[0.9375rem] leading-relaxed">{humanizeText(subject.reason, labelFor)}</p>
            </section>
          )}

          {graphPath && graphPath.length > 1 && (
            <section aria-labelledby="why-path" className="space-y-2">
              <h3 id="why-path" className="text-base font-bold">Prerequisite path in the skill graph</h3>
              <ol className="flex flex-wrap items-center gap-x-2 gap-y-2 text-[0.9375rem]">
                {graphPath.map((id, i) => (
                  <li key={id} className="inline-flex items-center gap-2">
                    <span className="border border-rule-strong bg-plate px-2 py-1 font-semibold">{labelFor(id)}</span>
                    {i < graphPath.length - 1 && <ArrowRight className="size-4 text-ink-3" aria-label="is a prerequisite of" />}
                  </li>
                ))}
              </ol>
            </section>
          )}

          {(evidenceCards.length > 0 || assessmentIds.length > 0) && (
            <section aria-labelledby="why-evidence" className="space-y-3">
              <h3 id="why-evidence" className="text-base font-bold">Evidence it used</h3>
              {evidenceCards.map((e) => (
                <EvidenceCard key={e.evidence_id} evidence={e} />
              ))}
              {assessmentIds.length > 0 && (
                <ul className="flex flex-wrap gap-2">
                  {assessmentIds.map((id) => (
                    <li key={id}>
                      <CitationBadge kind="assessment" label={itemCitation(id, labelFor)} />
                    </li>
                  ))}
                </ul>
              )}
            </section>
          )}

          {subject?.decisionId && (
            <section aria-labelledby="why-record" className="space-y-2">
              <h3 id="why-record" className="text-base font-bold">Decision record</h3>
              {decision.status === "loading" && <LoadingState variant="plate" label="Loading decision record" />}
              {decision.data && (
                <dl className="plate-quiet divide-y divide-rule text-[0.875rem]">
                  <div className="flex justify-between gap-4 p-3">
                    <dt className="text-ink-2">Type</dt>
                    <dd className="font-semibold">{decision.data.type}</dd>
                  </div>
                  <div className="flex justify-between gap-4 p-3">
                    <dt className="text-ink-2">Graph version</dt>
                    <dd className="draft font-semibold">{decision.data.graph_version}</dd>
                  </div>
                  <div className="p-3">
                    <dt className="text-ink-2">Rules checked</dt>
                    <dd className="mt-1 font-semibold">
                      {decision.data.rules_fired.length ? decision.data.rules_fired.join(", ") : "All hard rules held; none had to be relaxed."}
                    </dd>
                  </div>
                </dl>
              )}
            </section>
          )}

          {!subject?.reason && evidenceCards.length === 0 && assessmentIds.length === 0 && !graphPath && (
            <p className="text-[0.9375rem] text-ink-2">
              No further evidence is attached to this decision. It follows from the gap analysis for your target role.
            </p>
          )}

          <Link
            href={`/dashboard/tutor${subject?.skillId ? `?skill=${encodeURIComponent(subject.skillId)}` : ""}${subject?.decisionId ? `${subject?.skillId ? "&" : "?"}decision=${encodeURIComponent(subject.decisionId)}` : ""}`}
            className="inline-flex min-h-11 items-center gap-2 border border-rule-strong bg-paper px-4 text-[0.9375rem] font-semibold hover:bg-plate"
          >
            <MessageSquareText className="size-4" aria-hidden /> Ask the tutor about this
          </Link>
        </div>
      </SheetContent>
    </Sheet>
  );
}
