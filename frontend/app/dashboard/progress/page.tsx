"use client";

import { Check, Circle } from "lucide-react";
import Link from "next/link";
import { StruggleSkillCard } from "@/components/edupath/cards";
import { useLearner } from "@/components/edupath/learner-context";
import { SheetHeader } from "@/components/edupath/sheet-header";
import { EmptyState, ErrorState, LoadingState } from "@/components/edupath/states";
import { TierBadge } from "@/components/edupath/evidence";
import { SkillGlyph } from "@/components/edupath/skill-status";
import { ITEM_TYPE_LABEL, groupSignalsBySkill, dayLabel, humanizeText, minutes, pct, skillStateOf } from "@/lib/format";
import { useProgress } from "@/lib/hooks";
import type { ProgressActivityEntry, ProgressSkillEntry } from "@/lib/types";
import { cn } from "@/lib/utils";

function MasteryRow({ s }: { s: ProgressSkillEntry }) {
  const state = skillStateOf(s.status as "MET", s.mastery >= 0.4 ? 1 : 0);
  return (
    <li className="grid items-center gap-x-4 gap-y-1 px-4 py-3 sm:grid-cols-[minmax(0,1.2fr)_minmax(0,1fr)_auto]">
      <span className="flex items-center gap-2.5 font-bold">
        <SkillGlyph state={state} size={18} title="" />
        {s.label}
      </span>
      <div className="flex items-center gap-3" role="img" aria-label={`Mastery estimate ${pct(s.mastery)}, ${s.band}`}>
        <span className="relative h-2 flex-1 border border-ink bg-paper" aria-hidden>
          <span className="absolute inset-y-0 left-0 bg-ink" style={{ width: pct(s.mastery) }} />
          {[0.5, 0.7, 0.85].map((t) => (
            <span key={t} className="absolute -bottom-1 -top-1 w-px bg-rule-strong" style={{ left: `${t * 100}%` }} />
          ))}
        </span>
        <span className="draft w-10 text-right text-[0.9375rem] font-semibold">{pct(s.mastery)}</span>
      </div>
      <span className="flex items-center gap-3 text-[0.8125rem] text-ink-2">
        <span className="capitalize">{s.band}</span>
        {s.tier_max && <TierBadge tier={s.tier_max as "E0"} showLabel={false} />}
      </span>
    </li>
  );
}

function Activity({ items, labelFor, done }: { items: ProgressActivityEntry[]; labelFor: (id: string) => string; done: boolean }) {
  return (
    <ol className="plate reg">
      {items.map((a) => (
        <li key={a.item_id} className="flex items-start gap-3 p-3.5">
          {done ? <Check className="mt-0.5 size-4 shrink-0 text-verified" strokeWidth={3} aria-hidden /> : <Circle className="mt-0.5 size-4 shrink-0 text-ink-3" aria-hidden />}
          <div className="min-w-0">
            <p className="text-[0.9375rem] font-bold">
              {ITEM_TYPE_LABEL[a.type] ?? a.type}: {labelFor(a.skill_id)}
            </p>
            <p className="text-[0.8125rem] text-ink-2">
              {dayLabel(a.day_slot)} · {minutes(a.est_minutes)}
            </p>
          </div>
        </li>
      ))}
    </ol>
  );
}

export default function ProgressPage() {
  const { labelFor, role } = useLearner();
  const { data, status, error, reload } = useProgress();

  return (
    <div className="space-y-8">
      <SheetHeader title="Progress" description={`How far along the way to ${role?.title ?? "your target role"} you are, from evidence and assessments, not from time spent.`} />
      {status === "loading" && <LoadingState variant="grid" rows={4} label="Building your progress report" />}
      {status === "error" && <ErrorState error={error} onRetry={reload} />}

      {data && (
        <>
          {data.narrative && (
            <section aria-labelledby="pg-sum" className="plate p-4 sm:p-5">
              <h2 id="pg-sum" className="text-xl font-bold">In short</h2>
              <p className="mt-1 max-w-[66ch] text-[1rem] leading-relaxed">{humanizeText(data.narrative, labelFor)}</p>
              <p className="mt-2 text-[0.8125rem] text-ink-2">The counts below are computed from your records. The wording above is only a summary of them.</p>
            </section>
          )}

          <section aria-labelledby="pg-acq" className="space-y-2">
            <h2 id="pg-acq" className="text-xl font-bold">Acquired ({data.acquired.length})</h2>
            {data.acquired.length === 0 ? (
              <EmptyState title="Nothing acquired yet">A skill counts as acquired when your evidence meets the level the role needs. Assessments are the fastest way to move a skill there.</EmptyState>
            ) : (
              <ul className="plate reg">{data.acquired.map((s) => <MasteryRow key={s.skill_id} s={s} />)}</ul>
            )}
          </section>

          <section aria-labelledby="pg-inp" className="space-y-2">
            <h2 id="pg-inp" className="text-xl font-bold">In progress ({data.in_progress.length})</h2>
            {data.in_progress.length === 0 ? (
              <EmptyState title="No skills in progress">Skills with some evidence but not yet enough will show here, with a mastery estimate and how sure it is.</EmptyState>
            ) : (
              <ul className="plate reg">{data.in_progress.map((s) => <MasteryRow key={s.skill_id} s={s} />)}</ul>
            )}
            <p className="text-[0.8125rem] text-ink-2">Ticks mark the mastery each level needs: 50%, 70% and 85%. Mastery is an estimate, and one assessment never settles it.</p>
          </section>

          <section aria-labelledby="pg-str" className="space-y-2">
            <h2 id="pg-str" className="text-xl font-bold">Struggle areas</h2>
            {groupSignalsBySkill(data.struggle_areas).length === 0 ? (
              <p className="plate-quiet p-4 text-[0.9375rem] text-ink-2">No struggle detected. Nothing is holding you back that EduPath can see.</p>
            ) : (
              <div className="space-y-2">
                {groupSignalsBySkill(data.struggle_areas).map((g) => (<StruggleSkillCard key={g.skill_id} skillId={g.skill_id} signals={g.signals} labelFor={labelFor} />))}
              </div>
            )}
          </section>

          <div className={cn("grid gap-8", data.completed_work.length + data.next_steps.length > 0 && "lg:grid-cols-2")}>
            <section aria-labelledby="pg-done" className="space-y-2">
              <h2 id="pg-done" className="text-xl font-bold">Done ({data.completed_work.length})</h2>
              {data.completed_work.length === 0 ? <p className="plate-quiet p-4 text-[0.9375rem] text-ink-2">Nothing marked done yet. Tick items off in <Link href="/dashboard/plan" className="font-semibold underline">your plan</Link>.</p> : <Activity items={data.completed_work} labelFor={labelFor} done />}
            </section>
            <section aria-labelledby="pg-next" className="space-y-2">
              <h2 id="pg-next" className="text-xl font-bold">Next ({data.next_steps.length})</h2>
              {data.next_steps.length === 0 ? <p className="plate-quiet p-4 text-[0.9375rem] text-ink-2">No planned items left this week.</p> : <Activity items={data.next_steps} labelFor={labelFor} done={false} />}
            </section>
          </div>

          <p className="text-[0.875rem] text-ink-2">
            {data.remaining_gaps.length} skills still ahead of you for this role. <Link href="/dashboard/gaps" className="font-semibold underline">See the gaps</Link>
          </p>
        </>
      )}
    </div>
  );
}
