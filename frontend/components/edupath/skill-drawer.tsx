"use client";

import { ArrowUpRight, PencilRuler } from "lucide-react";
import Link from "next/link";
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle } from "@/components/ui/sheet";
import { LEVEL_LABEL, SKILL_STATE_META, skillStateOf } from "@/lib/format";
import { useSkillDetail } from "@/lib/hooks";
import { cn } from "@/lib/utils";
import { LevelGauge, ResourceCard } from "./cards";
import { EvidenceCard, TierBadge } from "./evidence";
import { EmptyState, ErrorState, LoadingState } from "./states";
import { SkillChip, SkillStatus } from "./skill-status";

const WEIGHT_LABEL: Record<number, string> = { 3: "core", 2: "important", 1: "nice to have" };

/**
 * SkillDrawer: everything about one skill in one place: why it matters,
 * the level needed, the evidence, prerequisites, resources and the next
 * action. All of it comes from `GET /api/learners/me/skills/{id}`.
 */
export function SkillDrawer({
  skillId,
  onClose,
  onSelectSkill,
}: {
  skillId: string | null;
  onClose: () => void;
  onSelectSkill: (skillId: string) => void;
}) {
  const { data, status, error, reload } = useSkillDetail(skillId);
  const gap = data?.gap ?? null;
  const state = gap ? skillStateOf(gap.status, gap.current_level) : null;
  const blocker = data?.prerequisites.find((p) => p.status && p.status !== "MET");

  return (
    <Sheet open={!!skillId} onOpenChange={(o) => !o && onClose()}>
      <SheetContent className="w-full max-w-none overflow-y-auto border-l border-rule-strong bg-paper sm:max-w-xl">
        <SheetHeader className="border-b border-rule p-5 pr-14">
          <SheetTitle className="text-xl font-bold">{data?.skill.label ?? "Skill"}</SheetTitle>
          <SheetDescription className="text-[0.9375rem]">{data?.skill.description || "Skill details from the curated graph."}</SheetDescription>
          {state && <SkillStatus state={state} className="mt-2" />}
        </SheetHeader>

        <div className="space-y-7 p-5">
          {status === "loading" && <LoadingState variant="plate" label="Loading skill" />}
          {status === "error" && <ErrorState error={error} onRetry={reload} />}

          {data && (
            <>
              <section aria-labelledby="sk-why" className="space-y-2">
                <h3 id="sk-why" className="text-base font-bold">Why it matters</h3>
                <p className="max-w-[60ch] text-[0.9375rem] leading-relaxed text-ink-2">
                  {data.role_requirement
                    ? `Your target role treats this as a ${WEIGHT_LABEL[data.role_requirement.weight] ?? "listed"} skill, needed at ${LEVEL_LABEL[data.role_requirement.required_level]?.toLowerCase()} level.`
                    : "Your target role does not list this skill itself, but other skills it needs depend on it."}
                  {data.dependents.length > 0 && ` It leads directly to ${data.dependents.length} other ${data.dependents.length === 1 ? "skill" : "skills"} in your path.`}
                </p>
              </section>

              {gap && (
                <section aria-labelledby="sk-level" className="space-y-2">
                  <h3 id="sk-level" className="text-base font-bold">Level</h3>
                  <div className="flex flex-wrap items-center gap-5">
                    <LevelGauge current={gap.current_level} required={gap.required_level} />
                    <p className="text-[0.875rem] text-ink-2">
                      Needs <b className="text-ink">{LEVEL_LABEL[gap.required_level]}</b>. You are at <b className="text-ink">{LEVEL_LABEL[gap.current_level]}</b>.
                      {data.mastery && (
                        <>
                          <br />
                          Mastery estimate {Math.round(data.mastery.estimate * 100)}%, {data.mastery.confidence} confidence, {data.mastery.n_obs} assessed {data.mastery.n_obs === 1 ? "answer" : "answers"}.
                        </>
                      )}
                    </p>
                  </div>
                </section>
              )}

              <section aria-labelledby="sk-ev" className="space-y-3">
                <h3 id="sk-ev" className="flex flex-wrap items-center gap-3 text-base font-bold">
                  Evidence {data.mastery && <TierBadge tier={data.mastery.tier_max as "E0"} showLabel={false} />}
                </h3>
                {data.evidence.length === 0 ? (
                  <EmptyState title="No evidence for this skill yet" className="p-4">
                    Nothing in your uploads or assessments shows this skill. A short assessment is the fastest way to add some.
                  </EmptyState>
                ) : (
                  data.evidence.map((e) => <EvidenceCard key={e.evidence_id} evidence={e} showSkill={false} />)
                )}
              </section>

              {data.prerequisites.length > 0 && (
                <section aria-labelledby="sk-pre" className="space-y-2">
                  <h3 id="sk-pre" className="text-base font-bold">Prerequisites</h3>
                  <ul className="flex flex-wrap gap-2">
                    {data.prerequisites.map((p) => (
                      <li key={p.skill_id}>
                        <button type="button" onClick={() => onSelectSkill(p.skill_id)} className="cursor-pointer text-left">
                          <SkillChip label={p.label} state={p.status ? skillStateOf(p.status, 0) : undefined} className="hover:bg-plate" />
                        </button>
                      </li>
                    ))}
                  </ul>
                </section>
              )}

              {data.dependents.length > 0 && (
                <section aria-labelledby="sk-dep" className="space-y-2">
                  <h3 id="sk-dep" className="text-base font-bold">Unlocks</h3>
                  <ul className="flex flex-wrap gap-2">
                    {data.dependents.map((p) => (
                      <li key={p.skill_id}>
                        <button type="button" onClick={() => onSelectSkill(p.skill_id)} className="cursor-pointer text-left">
                          <SkillChip label={p.label} state={p.status ? skillStateOf(p.status, 0) : undefined} className="hover:bg-plate" />
                        </button>
                      </li>
                    ))}
                  </ul>
                </section>
              )}

              {data.misconceptions.length > 0 && (
                <section aria-labelledby="sk-mis" className="space-y-2">
                  <h3 id="sk-mis" className="text-base font-bold">Common misconceptions</h3>
                  <ul className="space-y-2">
                    {data.misconceptions.map((m) => (
                      <li key={m.misconception_id} className={cn("plate-quiet p-3 text-[0.875rem]", m.learner_status && "border-revision")}>
                        <p>{m.description}</p>
                        <p className="mt-1 text-ink-2">
                          Usually rooted in <b className="text-ink">{m.root_skill_label}</b>.
                          {m.learner_status && <span className="ml-1 font-semibold text-revision">Detected in your answers: {m.learner_status}.</span>}
                        </p>
                      </li>
                    ))}
                  </ul>
                </section>
              )}

              <section aria-labelledby="sk-res" className="space-y-3">
                <h3 id="sk-res" className="text-base font-bold">Recommended resources</h3>
                {data.resources.length === 0 ? (
                  <EmptyState title="No resources curated for this skill yet" className="p-4">
                    The catalog has nothing vetted for this skill. EduPath will not invent a link.
                  </EmptyState>
                ) : (
                  data.resources.map((r) => <ResourceCard key={r.resource_id} resource={r} />)
                )}
              </section>

              <section aria-labelledby="sk-next" className="space-y-3 border-t border-rule-strong pt-5">
                <h3 id="sk-next" className="text-base font-bold">Next action</h3>
                {state === "blocked" && blocker ? (
                  <button
                    type="button"
                    onClick={() => onSelectSkill(blocker.skill_id)}
                    className="inline-flex min-h-11 cursor-pointer items-center gap-2 bg-ink px-4 text-[0.9375rem] font-semibold text-paper hover:bg-ink-2"
                  >
                    Start with {blocker.label} <ArrowUpRight className="size-4" aria-hidden />
                  </button>
                ) : state === "mastered" ? (
                  <p className="text-[0.9375rem] text-ink-2">Nothing to do here. This skill meets the level your role needs.</p>
                ) : (
                  <Link
                    href={`/dashboard/practice?skill=${encodeURIComponent(data.skill.skill_id)}&purpose=${state === "unverified" ? "probe" : "practice"}`}
                    className="inline-flex min-h-11 items-center gap-2 bg-ink px-4 text-[0.9375rem] font-semibold text-paper hover:bg-ink-2"
                  >
                    <PencilRuler className="size-4" aria-hidden />
                    {state === "unverified" ? "Verify with a short probe" : "Practise this skill"}
                  </Link>
                )}
                {data.plan_items.length > 0 && (
                  <p className="text-[0.8125rem] text-ink-2">
                    In this week&apos;s plan: {data.plan_items.length} {data.plan_items.length === 1 ? "item" : "items"} ({data.plan_items.filter((i) => i.status === "done").length} done).
                  </p>
                )}
                {state && <p className="max-w-[56ch] text-[0.8125rem] text-ink-3">{SKILL_STATE_META[state].meaning}</p>}
              </section>
            </>
          )}
        </div>
      </SheetContent>
    </Sheet>
  );
}
