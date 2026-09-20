"use client";

import { AlertTriangle } from "lucide-react";
import { useRouter } from "next/navigation";
import { useMemo } from "react";
import { GapCard, ObjectiveCard } from "@/components/edupath/cards";
import { useLearner } from "@/components/edupath/learner-context";
import { SheetHeader } from "@/components/edupath/sheet-header";
import { StateBar } from "@/components/edupath/state-bar";
import { EmptyState, ErrorState, LoadingState } from "@/components/edupath/states";
import { SKILL_STATE_ORDER, gapState, type SkillState } from "@/lib/format";
import { useGaps } from "@/lib/hooks";

export default function GapsPage() {
  const router = useRouter();
  const { role, labelFor } = useLearner();
  const { data, status, error, reload } = useGaps();

  const counts = useMemo(() => {
    const c = Object.fromEntries(SKILL_STATE_ORDER.map((s) => [s, 0])) as Record<SkillState, number>;
    (data?.gaps ?? []).forEach((g) => (c[gapState(g)] += 1));
    return c;
  }, [data]);

  const open = (id: string) => router.push(`/dashboard/skills?skill=${encodeURIComponent(id)}`);
  const actionable = (data?.gaps ?? []).filter((g) => g.status !== "MET" && g.status !== "BLOCKED").sort((a, b) => b.priority - a.priority);
  const blocked = (data?.gaps ?? []).filter((g) => g.status === "BLOCKED").sort((a, b) => b.priority - a.priority);
  const objectives = [...(data?.objectives ?? [])].sort((a, b) => b.priority - a.priority);

  return (
    <div className="space-y-8">
      <SheetHeader
        title="Gaps and objectives"
        description={`The distance between what you can prove and what ${role?.title ?? "the role"} needs, and the order to close it.`}
      />

      {status === "loading" && <LoadingState variant="grid" rows={6} label="Loading gaps" />}
      {status === "error" && <ErrorState error={error} onRetry={reload} />}

      {data && (
        <>
          <section aria-labelledby="g-summary" className="space-y-3">
            <h2 id="g-summary" className="text-xl font-bold">Summary</h2>
            <div className="plate p-4 sm:p-5">
              <StateBar counts={counts} />
            </div>
          </section>

          <section aria-labelledby="g-now" className="space-y-3">
            <div className="max-w-[62ch] space-y-1">
              <h2 id="g-now" className="text-xl font-bold">Start on these now</h2>
              <p className="text-[0.9375rem] text-ink-2">Nothing blocks these. Closing them unlocks the blocked skills below.</p>
            </div>
            {actionable.length === 0 ? (
              <EmptyState title="Nothing open right now">Every unmet skill is blocked behind another, or every skill is met.</EmptyState>
            ) : (
              <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
                {actionable.map((g) => (
                  <GapCard key={g.skill_id} gap={g} labelFor={labelFor} onOpen={open} />
                ))}
              </div>
            )}
          </section>

          <section aria-labelledby="g-obj" className="space-y-3">
            <div className="max-w-[62ch] space-y-1">
              <h2 id="g-obj" className="text-xl font-bold">Learning objectives</h2>
              <p className="text-[0.9375rem] text-ink-2">
                What the plan works toward. A skill you listed but have not shown gets a short probe first, so you never relearn what you already know.
              </p>
            </div>
            {objectives.length === 0 ? (
              <EmptyState title="No objectives yet">Objectives appear once there is a gap to close.</EmptyState>
            ) : (
              <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
                {objectives.map((o) => (
                  <ObjectiveCard key={o.objective_id} objective={o} labelFor={labelFor} onOpen={open} />
                ))}
              </div>
            )}
          </section>

          {data.audit_flags.length > 0 && (
            <section aria-labelledby="g-audit" className="space-y-3">
              <div className="max-w-[62ch] space-y-1">
                <h2 id="g-audit" className="text-xl font-bold">Worth double-checking</h2>
                <p className="text-[0.9375rem] text-ink-2">Places where a claim and its evidence do not quite line up.</p>
              </div>
              <ul className="plate reg">
                {data.audit_flags.map((f, i) => (
                  <li key={i} className="flex items-start gap-3 p-4">
                    <AlertTriangle className="mt-0.5 size-5 shrink-0 text-revision" aria-hidden />
                    <div className="space-y-0.5">
                      <p className="text-[0.9375rem] font-bold">{labelFor(f.skill_id)}</p>
                      <p className="max-w-[64ch] text-[0.875rem] text-ink-2">{f.message}</p>
                    </div>
                  </li>
                ))}
              </ul>
            </section>
          )}

          {blocked.length > 0 && (
            <section aria-labelledby="g-blocked" className="space-y-3">
              <div className="max-w-[62ch] space-y-1">
                <h2 id="g-blocked" className="text-xl font-bold">Blocked for now ({blocked.length})</h2>
                <p className="text-[0.9375rem] text-ink-2">A prerequisite is weak or missing. Each one names what is in the way.</p>
              </div>
              <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
                {blocked.slice(0, 12).map((g) => (
                  <GapCard key={g.skill_id} gap={g} labelFor={labelFor} onOpen={open} />
                ))}
              </div>
              {blocked.length > 12 && <p className="text-[0.8125rem] text-ink-2">{blocked.length - 12} more are on the skill map.</p>}
            </section>
          )}
        </>
      )}
    </div>
  );
}
