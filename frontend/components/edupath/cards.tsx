"use client";

import { AlertTriangle, BookOpen, ExternalLink, Hammer, PlayCircle, ScanSearch } from "lucide-react";
import { Button } from "@/components/ui/button";
import {
  CONFIDENCE_LABEL,
  DIFFICULTY_LABEL,
  LEVEL_LABEL,
  MODALITY_LABEL,
  SIGNAL_META,
  gapState,
  minutes,
} from "@/lib/format";
import type { LearningObjective, Resource, SkillGap, StruggleSignal } from "@/lib/types";
import { cn } from "@/lib/utils";
import { SkillChip, SkillGlyph, SkillStatus } from "./skill-status";

/** LevelGauge: three ruled steps. Filled to the current level, tick under the level the role needs. */
export function LevelGauge({ current, required, className }: { current: number; required: number; className?: string }) {
  return (
    <div
      className={cn("inline-flex flex-col gap-1", className)}
      role="img"
      aria-label={`You are at ${LEVEL_LABEL[current]?.toLowerCase() ?? `level ${current}`}. The role needs ${LEVEL_LABEL[required]?.toLowerCase() ?? `level ${required}`}.`}
    >
      <div className="flex gap-1" aria-hidden>
        {[1, 2, 3].map((n) => (
          <span key={n} className={cn("h-2 w-7 border border-ink", n <= current ? "bg-ink" : "bg-paper")} />
        ))}
      </div>
      <div className="flex gap-1" aria-hidden>
        {[1, 2, 3].map((n) => (
          <span key={n} className="flex w-7 justify-center">
            {n === required ? (
              <svg width="9" height="7" viewBox="0 0 9 7">
                <path d="M4.5 0L9 7H0z" fill="var(--ink)" />
              </svg>
            ) : null}
          </span>
        ))}
      </div>
    </div>
  );
}

const MODALITY_ICON = { watch: PlayCircle, read: BookOpen, do: Hammer } as const;

/** ResourceCard: a real catalog resource with what a learner needs to decide: how long, what kind, how hard. */
export function ResourceCard({ resource, className, footer }: { resource: Resource; className?: string; footer?: React.ReactNode }) {
  const Icon = MODALITY_ICON[resource.modality as keyof typeof MODALITY_ICON] ?? BookOpen;
  return (
    <article className={cn("plate-quiet flex flex-col gap-3 p-4", className)}>
      <div className="space-y-1">
        <h3 className="text-[1.0625rem] font-bold leading-snug">
          <a
            href={resource.url}
            target="_blank"
            rel="noopener noreferrer"
            className="inline-flex items-start gap-1.5 underline decoration-rule-strong hover:decoration-ink"
          >
            {resource.title}
            <ExternalLink className="mt-1 size-3.5 shrink-0" aria-label="opens in a new tab" />
          </a>
        </h3>
        <p className="text-[0.8125rem] text-ink-2">{resource.provider}</p>
      </div>
      {resource.learning_objective_text && <p className="text-[0.9375rem] text-ink-2">{resource.learning_objective_text}</p>}
      <ul className="flex flex-wrap gap-x-4 gap-y-1 text-[0.8125rem] text-ink-2">
        <li className="inline-flex items-center gap-1.5">
          <Icon className="size-4" aria-hidden />
          {MODALITY_LABEL[resource.modality] ?? resource.modality}
        </li>
        <li>{minutes(resource.duration_min)}</li>
        <li>{DIFFICULTY_LABEL[resource.difficulty] ?? `Level ${resource.difficulty}`}</li>
        <li>{resource.cost === "free" ? "Free" : resource.cost}</li>
        {resource.link_status && resource.link_status !== "ok" && (
          <li className="font-semibold text-revision">Link {resource.link_status}: it may have moved</li>
        )}
      </ul>
      {footer}
    </article>
  );
}

/** GapCard: one skill between you and the role. Names the state, the gap in levels, and what's in the way. */
export function GapCard({
  gap,
  onOpen,
  labelFor,
  className,
}: {
  gap: SkillGap;
  onOpen?: (skillId: string) => void;
  labelFor: (id: string) => string;
  className?: string;
}) {
  const state = gapState(gap);
  return (
    <article className={cn("plate-quiet flex flex-col gap-3 p-4", className)}>
      <header className="flex items-start justify-between gap-3">
        <h3 className={cn("text-base font-bold leading-snug", state === "blocked" && "text-ink-2")}>{gap.label}</h3>
        <SkillStatus state={state} />
      </header>
      <div className="flex items-center gap-4">
        <LevelGauge current={gap.current_level} required={gap.required_level} />
        <p className="text-[0.8125rem] leading-snug text-ink-2">
          Needs <b className="text-ink">{LEVEL_LABEL[gap.required_level] ?? gap.required_level}</b>
          <br />
          You are at <b className="text-ink">{LEVEL_LABEL[gap.current_level] ?? gap.current_level}</b>
        </p>
      </div>
      {gap.blocked_by.length > 0 && (
        <p className="text-[0.8125rem] text-ink-2">
          Blocked by{" "}
          <span className="inline-flex flex-wrap gap-1 align-middle">
            {gap.blocked_by.slice(0, 3).map((id) => (
              <SkillChip key={id} label={labelFor(id)} />
            ))}
            {gap.blocked_by.length > 3 && <span>+{gap.blocked_by.length - 3} more</span>}
          </span>
        </p>
      )}
      {gap.root_of.length > 0 && (
        <p className="text-[0.8125rem] text-ink-2">Unlocks {gap.root_of.length} other {gap.root_of.length === 1 ? "skill" : "skills"}.</p>
      )}
      {onOpen && (
        <Button variant="outline" size="sm" className="self-start" onClick={() => onOpen(gap.skill_id)}>
          Open skill
        </Button>
      )}
    </article>
  );
}

/** ObjectiveCard: what to do about a gap. Unverified skills get a probe first, never a beginner lesson. */
export function ObjectiveCard({
  objective,
  labelFor,
  onOpen,
  className,
}: {
  objective: LearningObjective;
  labelFor: (id: string) => string;
  onOpen?: (skillId: string) => void;
  className?: string;
}) {
  const probe = objective.objective_type === "probe";
  return (
    <article className={cn("plate-quiet flex flex-col gap-2 p-4", className)}>
      <header className="flex items-start justify-between gap-3">
        <h3 className="text-base font-bold leading-snug">{labelFor(objective.skill_id)}</h3>
        <span className="inline-flex shrink-0 items-center gap-1.5 border border-rule-strong px-2 py-0.5 text-[0.8125rem] font-semibold">
          {probe ? <ScanSearch className="size-3.5" aria-hidden /> : <BookOpen className="size-3.5" aria-hidden />}
          {probe ? "Verify first" : "Lesson"}
        </span>
      </header>
      <p className="text-[0.9375rem] text-ink-2">
        {probe
          ? `You listed this skill, but nothing proves it yet. A short probe comes before any lesson, so you do not relearn what you know.`
          : `Reach ${LEVEL_LABEL[objective.target_level]?.toLowerCase() ?? `level ${objective.target_level}`} in this skill.`}
      </p>
      {objective.prerequisite_objective_ids.length > 0 && (
        <p className="text-[0.8125rem] text-ink-2">
          Comes after {objective.prerequisite_objective_ids.length} other {objective.prerequisite_objective_ids.length === 1 ? "objective" : "objectives"}.
        </p>
      )}
      {onOpen && (
        <Button variant="ghost" size="sm" className="-ml-3 self-start" onClick={() => onOpen(objective.skill_id)}>
          Why this matters
        </Button>
      )}
    </article>
  );
}

/** StruggleSignalCard: a detected struggle, named plainly, with the classifier's confidence. */
export function StruggleSignalCard({
  signal,
  labelFor,
  className,
}: {
  signal: Pick<StruggleSignal, "signal_class" | "skill_id" | "confidence"> & { counts?: Record<string, unknown> };
  labelFor: (id: string) => string;
  className?: string;
}) {
  const meta = SIGNAL_META[signal.signal_class] ?? { label: signal.signal_class.replace(/_/g, " "), meaning: "" };
  return (
    <div className={cn("flex items-start gap-3 border border-revision bg-paper p-3", className)}>
      <AlertTriangle className="mt-0.5 size-5 shrink-0 text-revision" aria-hidden />
      <div className="min-w-0 space-y-0.5">
        <p className="text-[0.9375rem] font-bold">
          {meta.label} <span className="font-normal text-ink-2">in {labelFor(signal.skill_id)}</span>
        </p>
        <p className="text-[0.8125rem] text-ink-2">{meta.meaning}</p>
        <p className="text-[0.8125rem] font-semibold text-ink-2">{CONFIDENCE_LABEL[signal.confidence] ?? signal.confidence}</p>
      </div>
    </div>
  );
}

/** One alert per struggling skill, listing each pattern the classifier found and how sure it is. */
export function StruggleSkillCard({
  skillId,
  signals,
  labelFor,
  className,
}: {
  skillId: string;
  signals: Array<{ signal_class: string | null; confidence: string | null }>;
  labelFor: (id: string) => string;
  className?: string;
}) {
  return (
    <div className={cn("border border-revision bg-paper p-3.5", className)} role="group" aria-label={`Struggle in ${labelFor(skillId)}`}>
      <p className="flex items-center gap-2 text-[0.9375rem] font-bold">
        <AlertTriangle className="size-5 shrink-0 text-revision" aria-hidden /> Struggling with {labelFor(skillId)}
      </p>
      <ul className="mt-2 space-y-1.5 pl-7">
        {signals.map((s) => {
          const meta = SIGNAL_META[s.signal_class ?? "low_score"] ?? { label: s.signal_class ?? "", meaning: "" };
          return (
            <li key={s.signal_class} className="text-[0.8125rem] leading-snug text-ink-2">
              <b className="text-ink">{meta.label}.</b> {meta.meaning} <span className="font-semibold">{CONFIDENCE_LABEL[s.confidence ?? "medium"]}.</span>
            </li>
          );
        })}
      </ul>
    </div>
  );
}

export { SkillGlyph };
