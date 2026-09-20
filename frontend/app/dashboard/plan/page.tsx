"use client";

import { CalendarPlus, RefreshCw } from "lucide-react";
import { useMemo, useState } from "react";
import { AgentTrace } from "@/components/edupath/agent-trace";
import { useLearner } from "@/components/edupath/learner-context";
import { NextAction } from "@/components/edupath/next-action";
import { WeeklyPlan } from "@/components/edupath/plan";
import { AdaptiveMoment, RevisionHistory, useChangedItemIds } from "@/components/edupath/revision";
import { SheetHeader } from "@/components/edupath/sheet-header";
import { DegradedNotice, EmptyState, ErrorState, LoadingState } from "@/components/edupath/states";
import { Button } from "@/components/ui/button";
import { api } from "@/lib/api-client";
import { revisionLetter } from "@/lib/derived";
import { useGaps, usePlan, useRevisions } from "@/lib/hooks";
import { invalidate } from "@/lib/query";
import { traced, useTraceRuns } from "@/lib/trace-store";

export default function PlanPage() {
  const { role } = useLearner();
  const plan = usePlan();
  const revisions = useRevisions();
  const gaps = useGaps();
  const [building, setBuilding] = useState(false);
  const [buildError, setBuildError] = useState<unknown>(null);
  const [runId, setRunId] = useState<string>();
  const runs = useTraceRuns();
  const run = runs.find((r) => r.runId === runId);

  const sorted = useMemo(() => [...(revisions.data ?? [])].sort((a, b) => b.revision_no - a.revision_no), [revisions.data]);
  const current = sorted.find((r) => r.is_current);
  const latestReflection = sorted.find((r) => r.cause_type === "reflection" && r.parent_revision_id);
  const changedIds = useChangedItemIds(plan.data, revisions.data);

  async function build(nextWeek: boolean) {
    setBuilding(true);
    setBuildError(null);
    const week = nextWeek && plan.data ? plan.data.week_index + 1 : (plan.data?.week_index ?? 0);
    try {
      await traced(`Building week ${week + 1}`, (id) => {
        setRunId(id);
        return api.createPlan({ week_index: week }, id);
      });
      invalidate();
    } catch (e) {
      setBuildError(e);
    } finally {
      setBuilding(false);
    }
  }

  const hasPlan = !!plan.data;
  return (
    <div className="space-y-8">
      <SheetHeader
        title="Weekly plan"
        description={`A week toward ${role?.title ?? "your target role"}, sized to your hours. Every item says why it is here.`}
        next={hasPlan ? <NextAction /> : undefined}
        action={
          hasPlan ? (
            <Button variant="outline" onClick={() => build(true)} disabled={building} aria-busy={building}>
              <CalendarPlus /> {building ? "Planning" : "Plan next week"}
            </Button>
          ) : undefined
        }
      />

      {plan.status === "loading" && <LoadingState rows={4} label="Loading your plan" />}
      {plan.status === "error" && <ErrorState error={plan.error} onRetry={plan.reload} />}

      {plan.status === "ready" && !plan.data && (
        <EmptyState
          title="No plan yet"
          action={
            <Button size="lg" onClick={() => build(false)} disabled={building} aria-busy={building}>
              {building ? "Building" : "Build week one"}
            </Button>
          }
        >
          EduPath compares your evidence with the role, finds the gaps you can start on, and schedules them inside your {`hours`}. You will see each step as it runs.
        </EmptyState>
      )}

      {buildError != null && <ErrorState error={buildError} onRetry={() => build(false)} title="The plan could not be built" />}
      {run && (building || !hasPlan) && <AgentTrace run={run} />}

      {plan.data && (
        <section aria-label="This week" className="space-y-3">
          <div className="flex flex-wrap items-baseline justify-between gap-2">
            <h2 className="text-xl font-bold">Week {plan.data.week_index + 1}</h2>
            <p className="flex items-center gap-3 text-[0.9375rem] font-semibold text-ink-2">
              {latestReflection && (
                <a href="#moment" className="font-semibold text-revision underline">
                  Why did my plan change?
                </a>
              )}
              <span className="draft">Revision {revisionLetter(plan.data.revision_no)}</span>
            </p>
          </div>
          {plan.data.degraded && (
            <DegradedNotice>The fallback planner scheduled this week: objectives ordered by priority and prerequisite layer, fitted to your hours.</DegradedNotice>
          )}
          {plan.data.items.length === 0 ? (
            <EmptyState title="Nothing fits this week" icon={RefreshCw}>
              No eligible resource fits your hours and session length for the gaps you can start on. Try more hours, or check the catalog covers your target role.
            </EmptyState>
          ) : (
            <WeeklyPlan plan={plan.data} changedIds={changedIds} revisionLabel={current ? revisionLetter(current.revision_no) : undefined} />
          )}
        </section>
      )}

      {plan.data && latestReflection && (
        <div id="moment" className="scroll-mt-20 border-t border-rule-strong pt-8">
          <AdaptiveMoment planId={plan.data.plan_id} revision={latestReflection} />
        </div>
      )}

      {plan.data && revisions.data && revisions.data.length > 0 && <RevisionHistory revisions={revisions.data} />}
      {gaps.status === "error" && null}
    </div>
  );
}
