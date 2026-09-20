"use client";

import { ArrowRight, ShieldCheck } from "lucide-react";
import Link from "next/link";
import { useMemo, useState } from "react";
import { GapCard, StruggleSkillCard } from "@/components/edupath/cards";
import { useLearner } from "@/components/edupath/learner-context";
import { LoopRibbon } from "@/components/edupath/loop-ribbon";
import { NextAction } from "@/components/edupath/next-action";
import { PlanItemRow, BudgetBar, itemTitle } from "@/components/edupath/plan";
import { useChangedItemIds } from "@/components/edupath/revision";
import { SheetHeader } from "@/components/edupath/sheet-header";
import { StateBar } from "@/components/edupath/state-bar";
import { DegradedNotice, EmptyState, ErrorState, LoadingState } from "@/components/edupath/states";
import { WhyDrawer, type WhySubject } from "@/components/edupath/why-drawer";
import { Button } from "@/components/ui/button";
import { loopStages, planMinutes, revisionLetter } from "@/lib/derived";
import { SKILL_STATE_ORDER, gapState, groupSignalsBySkill, humanizeText, type SkillState } from "@/lib/format";
import { useEvidence, useGaps, usePlan, useProgress, useResources, useRevisions } from "@/lib/hooks";
import type { PlanItem } from "@/lib/types";

function Panel({ title, action, children, className }: { title: string; action?: React.ReactNode; children: React.ReactNode; className?: string }) {
  return (
    <section aria-label={title} className={className}>
      <div className="mb-2 flex items-baseline justify-between gap-3">
        <h2 className="text-lg font-bold">{title}</h2>
        {action}
      </div>
      {children}
    </section>
  );
}

export default function OverviewPage() {
  const { role, labelFor, profile } = useLearner();
  const gaps = useGaps();
  const plan = usePlan();
  const revisions = useRevisions();
  const evidence = useEvidence();
  const progress = useProgress();
  const [why, setWhy] = useState<WhySubject | null>(null);
  const [whyOpen, setWhyOpen] = useState(false);

  const planItems = plan.data?.items ?? [];
  const { byId: resources } = useResources(planItems.map((i) => i.resource_id));

  const counts = useMemo(() => {
    const c = Object.fromEntries(SKILL_STATE_ORDER.map((s) => [s, 0])) as Record<SkillState, number>;
    (gaps.data?.gaps ?? []).forEach((g) => (c[gapState(g)] += 1));
    return c;
  }, [gaps.data]);

  const rootGaps = useMemo(
    () =>
      (gaps.data?.gaps ?? [])
        .filter((g) => g.status !== "MET" && g.status !== "BLOCKED")
        .sort((a, b) => b.priority - a.priority)
        .slice(0, 3),
    [gaps.data],
  );
  const stages = loopStages({
    evidence: evidence.data,
    gaps: gaps.data,
    plan: plan.data,
    revisions: revisions.data,
    hasStruggle: (progress.data?.struggle_areas.length ?? 0) > 0,
  });

  const changedIds = useChangedItemIds(plan.data, revisions.data);
  const groups = groupSignalsBySkill(progress.data?.struggle_areas ?? []);
  const hasReflection = (revisions.data ?? []).some((r) => r.cause_type === "reflection");
  const nextItems = planItems.filter((i) => i.status === "planned").sort((a, b) => a.day_slot - b.day_slot).slice(0, 3);
  const done = planItems.filter((i) => i.status === "done").length;
  const latestRevision = [...(revisions.data ?? [])].sort((a, b) => b.revision_no - a.revision_no)[0];
  const total = gaps.data?.gaps.length ?? 0;

  function openWhy(item: PlanItem) {
    setWhy({
      title: `Why "${itemTitle(item, item.resource_id ? resources[item.resource_id] : undefined, labelFor)}"`,
      reason: item.reason?.text,
      skillId: item.skill_id,
      evidenceIds: item.reason?.evidence_ids,
      graphPath: item.reason?.graph_path,
      decisionId: item.reason?.decision_id,
    });
    setWhyOpen(true);
  }

  return (
    <div className="space-y-6">
      <SheetHeader
        title="Overview"
        description={profile.career_goal || "Where you stand, where you are going, and what to do this week."}
        next={<NextAction />}
      />

      <section aria-label="The adaptive loop" className="plate-quiet p-4 sm:p-5">
        <LoopRibbon stages={stages} />
      </section>

      <div className="grid gap-6 lg:grid-cols-[minmax(0,1.55fr)_minmax(0,1fr)]">
        <div className="space-y-6">
          <Panel
            title="Do this next"
            action={
              <Link href="/dashboard/plan" className="inline-flex min-h-11 items-center gap-1 text-[0.875rem] font-semibold underline md:min-h-0">
                Full plan <ArrowRight className="size-3.5" aria-hidden />
              </Link>
            }
          >
            {plan.status === "loading" && <LoadingState rows={3} label="Loading this week's plan" />}
            {plan.status === "error" && <ErrorState error={plan.error} onRetry={plan.reload} />}
            {plan.status === "ready" && !plan.data && (
              <EmptyState title="No plan yet" action={<Link href="/dashboard/plan" className="inline-flex min-h-11 items-center bg-ink px-4 text-[0.9375rem] font-semibold text-paper">Build week one</Link>}>
                EduPath needs a plan to tell you what to do. It builds one from your gaps and your hours.
              </EmptyState>
            )}
            {plan.data && (
              <div className="space-y-3">
                <BudgetBar usedMinutes={planMinutes(planItems)} budgetMinutes={Math.round(plan.data.hours_budget * 60)} />
                {plan.data.degraded && <DegradedNotice>The fallback planner scheduled this week from the gap analysis, without model wording.</DegradedNotice>}
                {nextItems.length > 0 ? (
                  <div className="plate reg">
                    {nextItems.map((it) => (
                      <PlanItemRow key={it.item_id} item={it} resource={it.resource_id ? resources[it.resource_id] : undefined} onWhy={openWhy} changedIn={changedIds?.has(it.item_id) ? revisionLetter(plan.data!.revision_no) : undefined} />
                    ))}
                  </div>
                ) : (
                  <p className="plate-quiet p-4 text-[0.9375rem] text-ink-2">Everything planned this week is done. {done} of {planItems.length} items complete.</p>
                )}
                {planItems.length > nextItems.length + done && (
                  <p className="text-[0.8125rem] text-ink-2">{planItems.length - nextItems.length - done} more planned later this week.</p>
                )}
              </div>
            )}
          </Panel>

          <Panel
            title="Where you stand"
            action={
              <Link href="/dashboard/skills" className="inline-flex min-h-11 items-center gap-1 text-[0.875rem] font-semibold underline md:min-h-0">
                Skill map <ArrowRight className="size-3.5" aria-hidden />
              </Link>
            }
          >
            {gaps.status === "loading" && <LoadingState variant="plate" label="Loading your skills" />}
            {gaps.status === "error" && <ErrorState error={gaps.error} onRetry={gaps.reload} />}
            {gaps.data && (
              <div className="plate space-y-4 p-4 sm:p-5">
                <p className="max-w-[60ch] text-[0.9375rem]">
                  {counts.mastered > 0 ? (<><b>{counts.mastered}</b> of {total} skills on the way to <b>{role?.title ?? "your target role"}</b> meet the level the role needs. The rest are in the states below.</>) : (<>None of the {total} skills on the way to <b>{role?.title ?? "your target role"}</b> meet the required level yet. Here is where each one stands.</>)}
                </p>
                <StateBar counts={counts} />
              </div>
            )}
          </Panel>
        </div>

        <div className="space-y-6">
          <Panel
            title="What's missing"
            action={
              <Link href="/dashboard/gaps" className="inline-flex min-h-11 items-center gap-1 text-[0.875rem] font-semibold underline md:min-h-0">
                All gaps <ArrowRight className="size-3.5" aria-hidden />
              </Link>
            }
          >
            {gaps.status === "loading" && <LoadingState variant="grid" rows={2} label="Loading gaps" />}
            {gaps.data && rootGaps.length === 0 && <EmptyState title="No open gaps">Every skill on the way to this role is met, or blocked behind one that is not.</EmptyState>}
            <div className="space-y-3">
              {rootGaps.map((g) => (
                <GapCard key={g.skill_id} gap={g} labelFor={labelFor} className="!p-3.5" onOpen={undefined} />
              ))}
            </div>
            {rootGaps.length > 0 && (
              <p className="mt-2 text-[0.8125rem] text-ink-2">
                These are the gaps you can start on now. {counts.blocked} more are blocked behind them.
              </p>
            )}
          </Panel>

          <Panel title="Anything wrong?">
            {progress.status === "loading" && <LoadingState variant="plate" label="Checking for struggle signals" />}
            {progress.status === "error" && <ErrorState error={progress.error} onRetry={progress.reload} />}
            {progress.data &&
              (groups.length === 0 ? (
                <div className="plate-quiet flex items-start gap-3 p-4">
                  <ShieldCheck className="mt-0.5 size-5 shrink-0 text-verified" aria-hidden />
                  <p className="text-[0.9375rem]">No struggle detected. Assessments you take will be checked for misconceptions and missing prerequisites.</p>
                </div>
              ) : (
                <div className="space-y-2">{groups.slice(0, 2).map((g) => (<StruggleSkillCard key={g.skill_id} skillId={g.skill_id} signals={g.signals} labelFor={labelFor} />))}</div>
              ))}
          </Panel>

          <Panel title="Why this plan">
            {(plan.status === "loading" || revisions.status === "loading") && <LoadingState variant="plate" label="Loading rationale" />}
            {plan.data && (
              <div className="plate-quiet space-y-3 p-4">
                <p className="max-w-[60ch] text-[0.9375rem] leading-relaxed">{humanizeText(latestRevision?.overall_reason || plan.data.overall_reason, labelFor)}</p>
                <p className="text-[0.8125rem] text-ink-2">
                  Based on {evidence.data?.length ?? 0} pieces of evidence and the curated skill graph.
                </p>
                <Button
                  variant="outline"
                  size="sm"
                  onClick={() => {
                    setWhy({ title: "Why this plan", reason: latestRevision?.overall_reason || plan.data!.overall_reason, decisionId: latestRevision?.decision_id });
                    setWhyOpen(true);
                  }}
                >
                  See the evidence
                </Button>
                {hasReflection && (
                  <Link href="/dashboard/plan#moment" className="ml-3 inline-flex min-h-11 items-center gap-1 text-[0.875rem] font-semibold text-revision underline md:min-h-0">
                    Why did my plan change? <ArrowRight className="size-3.5" aria-hidden />
                  </Link>
                )}
              </div>
            )}
            {plan.status === "ready" && !plan.data && <p className="text-[0.9375rem] text-ink-2">The reasoning appears here once a plan exists.</p>}
          </Panel>
        </div>
      </div>

      {progress.data?.narrative && ((progress.data.acquired.length > 0) || (progress.data.completed_work.length > 0)) && (
        <Panel title="Are you improving?">
          <div className="plate-quiet space-y-2 p-4 sm:p-5">
            <p className="max-w-[68ch] text-[0.9375rem] leading-relaxed">{humanizeText(progress.data.narrative, labelFor)}</p>
            <Link href="/dashboard/progress" className="inline-flex items-center gap-1 text-[0.875rem] font-semibold underline">
              Progress report <ArrowRight className="size-3.5" aria-hidden />
            </Link>
          </div>
        </Panel>
      )}

      <WhyDrawer subject={why} open={whyOpen} onOpenChange={setWhyOpen} />
    </div>
  );
}
