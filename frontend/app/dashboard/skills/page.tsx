"use client";

import dynamic from "next/dynamic";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useMemo, useState } from "react";
import { useLearner } from "@/components/edupath/learner-context";
import { SheetHeader } from "@/components/edupath/sheet-header";
import { SkillDrawer } from "@/components/edupath/skill-drawer";
import { EmptyState, ErrorState, LoadingState } from "@/components/edupath/states";
import { SKILL_STATE_META, SKILL_STATE_ORDER, gapState, type SkillState } from "@/lib/format";
import { useGaps } from "@/lib/hooks";
import { cn } from "@/lib/utils";
import { SkillGlyph } from "@/components/edupath/skill-status";

// The graph is the heaviest client component on the app: load it on demand.
const SkillGraph = dynamic(() => import("@/components/edupath/skill-graph").then((m) => m.SkillGraph), {
  ssr: false,
  loading: () => <LoadingState variant="plate" label="Drawing the skill map" />,
});

function SkillMap() {
  const params = useSearchParams();
  const router = useRouter();
  const { role } = useLearner();
  const { data, status, error, reload } = useGaps();
  const [hidden, setHidden] = useState<Set<SkillState>>(new Set());
  const selected = params.get("skill");

  const select = (id: string | null) => {
    const next = new URLSearchParams(params.toString());
    if (id) next.set("skill", id);
    else next.delete("skill");
    router.replace(`/dashboard/skills${next.toString() ? `?${next}` : ""}`, { scroll: false });
  };

  const counts = useMemo(() => {
    const c = Object.fromEntries(SKILL_STATE_ORDER.map((s) => [s, 0])) as Record<SkillState, number>;
    (data?.gaps ?? []).forEach((g) => (c[gapState(g)] += 1));
    return c;
  }, [data]);

  return (
    <div className="space-y-6">
      <SheetHeader
        title="Skill map"
        description={`Every skill on the way to ${role?.title ?? "your target role"}, with what you can prove about it. Prerequisites run left to right.`}
      />

      {status === "loading" && <LoadingState variant="plate" label="Loading skills" />}
      {status === "error" && <ErrorState error={error} onRetry={reload} />}
      {data && data.gaps.length === 0 && (
        <EmptyState title="No skills to map">This role has no curated skills in the graph yet.</EmptyState>
      )}
      {data && data.gaps.length > 0 && (
        <>
          <div className="flex flex-wrap items-center gap-2" role="group" aria-label="Filter skills by state">
            <span className="mr-1 text-[0.875rem] font-semibold text-ink-2">Show</span>
            {SKILL_STATE_ORDER.map((s) => {
              const off = hidden.has(s);
              return (
                <button
                  key={s}
                  type="button"
                  aria-pressed={!off}
                  disabled={counts[s] === 0}
                  onClick={() =>
                    setHidden((h) => {
                      const n = new Set(h);
                      if (n.has(s)) n.delete(s);
                      else n.add(s);
                      return n;
                    })
                  }
                  title={SKILL_STATE_META[s].meaning}
                  className={cn(
                    "inline-flex min-h-11 cursor-pointer items-center gap-1.5 border px-2.5 text-[0.8125rem] font-semibold transition-colors duration-150 md:min-h-8",
                    off ? "border-rule bg-sheet text-ink-3 line-through" : "border-rule-strong bg-paper hover:bg-plate",
                    counts[s] === 0 && "cursor-default opacity-40",
                  )}
                >
                  <SkillGlyph state={s} size={14} title="" />
                  {SKILL_STATE_META[s].label} <span className="draft">{counts[s]}</span>
                </button>
              );
            })}
          </div>

          <SkillGraph gaps={data.gaps} edges={data.prerequisite_edges} selectedId={selected} onSelect={select} hiddenStates={hidden.size ? hidden : undefined} />
          <p className="max-w-[70ch] text-[0.8125rem] text-ink-2">
            Select a skill to see why it matters, the evidence for it, its prerequisites and what to do next. Graph version {data.graph_version}; curated by people, not generated at runtime.
          </p>
        </>
      )}

      <SkillDrawer skillId={selected} onClose={() => select(null)} onSelectSkill={(id) => select(id)} />
    </div>
  );
}

export default function SkillsPage() {
  return (
    <Suspense fallback={<LoadingState variant="plate" label="Loading skill map" />}>
      <SkillMap />
    </Suspense>
  );
}
