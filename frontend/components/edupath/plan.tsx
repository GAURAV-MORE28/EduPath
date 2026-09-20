"use client";

import { Check, ExternalLink, HelpCircle, PencilRuler } from "lucide-react";
import Link from "next/link";
import { AnimatePresence, motion } from "motion/react";
import { useState } from "react";
import { Button } from "@/components/ui/button";
import { api } from "@/lib/api-client";
import { revisionLetter, planByDay, planMinutes } from "@/lib/derived";
import { DIFFICULTY_LABEL, ITEM_TYPE_LABEL, MODALITY_LABEL, dayLabel, humanizeText, hours, minutes } from "@/lib/format";
import { useResources } from "@/lib/hooks";
import { invalidate } from "@/lib/query";
import type { PlanItem, Resource, WeeklyPlan as WeeklyPlanT } from "@/lib/types";
import { cn } from "@/lib/utils";
import { useLearner } from "./learner-context";
import { WhyDrawer, type WhySubject } from "./why-drawer";

export function itemTitle(item: PlanItem, resource: Resource | undefined, labelFor: (id: string) => string): string {
  if (item.type === "probe") return `Check: ${labelFor(item.skill_id)}`;
  if (item.type === "practice") return `Practice: ${labelFor(item.skill_id)}`;
  return resource?.title ?? labelFor(item.skill_id);
}

export function practiceHref(item: PlanItem): string {
  const resolution = /resolution-check/i.test(item.reason?.text ?? "");
  const purpose = item.type === "probe" ? (resolution ? "resolution-check" : "probe") : "practice";
  return `/dashboard/practice?skill=${encodeURIComponent(item.skill_id)}&purpose=${purpose}`;
}

/** The revision marker: a small triangle carrying the revision letter, as on a drawing. */
export function RevisionMark({ letter, className }: { letter: string; className?: string }) {
  return (
    <span className={cn("relative inline-grid size-6 place-items-center text-revision", className)} title={`Added in revision ${letter}`}>
      <svg viewBox="0 0 24 24" className="absolute inset-0 size-full" aria-hidden>
        <path d="M12 2.5L22 21H2z" fill="var(--paper)" stroke="currentColor" strokeWidth="1.6" strokeLinejoin="round" />
      </svg>
      <span className="draft relative top-[2px] text-[0.6875rem] font-semibold leading-none">{letter}</span>
      <span className="sr-only">Added in revision {letter}</span>
    </span>
  );
}

function DoneToggle({ item, pending, onToggle }: { item: PlanItem; pending: boolean; onToggle: () => void }) {
  const done = item.status === "done";
  return (
    <button
      type="button"
      role="checkbox"
      aria-checked={done}
      aria-label={done ? `Mark "${item.skill_id}" as not done` : `Mark "${item.skill_id}" as done`}
      disabled={pending}
      onClick={onToggle}
      className="group grid size-11 shrink-0 cursor-pointer place-items-center md:size-8"
    >
      <span className={cn("grid size-6 place-items-center border-[1.5px] border-ink transition-colors duration-150 md:size-5", done ? "bg-ink text-paper" : "bg-paper group-hover:bg-plate")}>
        <AnimatePresence initial={false}>
          {done && (
            <motion.span key="tick" initial={{ scale: 0.4, opacity: 0 }} animate={{ scale: 1, opacity: 1 }} exit={{ scale: 0.4, opacity: 0 }} transition={{ type: "spring", stiffness: 500, damping: 30 }}>
              <Check className="size-4 md:size-3.5" strokeWidth={3} />
            </motion.span>
          )}
        </AnimatePresence>
      </span>
    </button>
  );
}

/** One row of the plan register. Shows what to do, how long, how hard, and why. */
export function PlanItemRow({
  item,
  resource,
  onWhy,
  changedIn,
  className,
  readOnly = false,
  afterTitles,
}: {
  item: PlanItem;
  resource?: Resource;
  onWhy?: (item: PlanItem) => void;
  /** revision letter if this item was added or changed by a revision */
  changedIn?: string;
  className?: string;
  readOnly?: boolean;
  afterTitles?: string[];
}) {
  const { labelFor } = useLearner();
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const done = item.status === "done";
  const practice = item.type === "probe" || item.type === "practice";

  async function toggle() {
    setPending(true);
    setError(null);
    try {
      await api.setItemStatus(item.item_id, done ? "planned" : "done");
      invalidate("plan");
      invalidate("progress");
      invalidate("revisions");
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not update this item.");
    } finally {
      setPending(false);
    }
  }

  return (
    <div id={`item-${item.item_id}`} className={cn("flex items-start gap-2 p-3 sm:gap-3 sm:p-4", done && "bg-plate/50", className)}>
      {!readOnly && <DoneToggle item={item} pending={pending} onToggle={toggle} />}
      <div className="min-w-0 flex-1 space-y-1.5">
        <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
          <span className="border border-rule-strong px-1.5 py-px text-[0.75rem] font-semibold text-ink-2">{ITEM_TYPE_LABEL[item.type] ?? item.type}</span>
          <h4 className={cn("text-[1rem] font-bold leading-snug", done && "text-ink-2 line-through decoration-rule-strong")}>{itemTitle(item, resource, labelFor)}</h4>
          {changedIn && <RevisionMark letter={changedIn} />}
        </div>
        <p className="text-[0.8125rem] text-ink-2">
          {labelFor(item.skill_id)} · {minutes(item.est_minutes)} · {DIFFICULTY_LABEL[item.difficulty] ?? `Level ${item.difficulty}`}
          {resource ? ` · ${MODALITY_LABEL[resource.modality] ?? resource.modality} · ${resource.provider}` : ""}
        </p>
        {item.reason?.text && <p className="max-w-[68ch] text-[0.875rem] text-ink-2">{humanizeText(item.reason.text, labelFor)}</p>}
        {afterTitles && afterTitles.length > 0 && <p className="text-[0.8125rem] text-ink-3">After: {afterTitles.join(", ")}</p>}
        {!readOnly && (
          <div className="flex flex-wrap items-center gap-2 pt-1">
            {practice ? (
              <Link href={practiceHref(item)} className="inline-flex min-h-11 items-center gap-1.5 border border-ink bg-ink px-3 text-[0.8125rem] font-semibold text-paper hover:bg-ink-2 md:min-h-8">
                <PencilRuler className="size-4" aria-hidden /> Begin {item.type === "probe" ? "check" : "practice"}
              </Link>
            ) : (
              resource && (
                <a href={resource.url} target="_blank" rel="noopener noreferrer" className="inline-flex min-h-11 items-center gap-1.5 border border-ink bg-ink px-3 text-[0.8125rem] font-semibold text-paper hover:bg-ink-2 md:min-h-8">
                  <ExternalLink className="size-4" aria-hidden /> Open resource
                </a>
              )
            )}
            {onWhy && (
              <Button variant="outline" size="sm" onClick={() => onWhy(item)}>
                <HelpCircle /> Why this
              </Button>
            )}
          </div>
        )}
        {error && <p role="alert" className="text-[0.8125rem] font-semibold text-revision">{error}</p>}
      </div>
      <span className="draft hidden shrink-0 pt-0.5 text-[0.9375rem] font-semibold text-ink-2 sm:block">{minutes(item.est_minutes)}</span>
    </div>
  );
}

/** Budget: minutes planned against the weekly hours, drawn as a ruled bar with the ceiling marked. */
export function BudgetBar({ usedMinutes, budgetMinutes, className }: { usedMinutes: number; budgetMinutes: number; className?: string }) {
  const ratio = budgetMinutes > 0 ? Math.min(1, usedMinutes / budgetMinutes) : 0;
  return (
    <div className={cn("space-y-1.5", className)}>
      <div className="flex items-baseline justify-between text-[0.8125rem]">
        <span className="font-semibold">
          {hours(usedMinutes)} planned <span className="font-normal text-ink-2">of {hours(budgetMinutes)}</span>
        </span>
        <span className="text-ink-2">{Math.max(0, Math.round((budgetMinutes - usedMinutes) / 6) / 10)} h free</span>
      </div>
      <div className="relative h-2.5 border border-ink bg-paper" role="img" aria-label={`${hours(usedMinutes)} planned of ${hours(budgetMinutes)}`}>
        <motion.div className="h-full bg-ink" initial={false} animate={{ width: `${ratio * 100}%` }} transition={{ duration: 0.5, ease: [0.16, 1, 0.3, 1] }} />
      </div>
    </div>
  );
}

/** WeeklyPlan: the week as a ruled register grouped by day, with budget, completion and the why drawer. */
export function WeeklyPlan({ plan, changedIds, revisionLabel }: { plan: WeeklyPlanT; changedIds?: Set<string>; revisionLabel?: string }) {
  const { labelFor } = useLearner();
  const [why, setWhy] = useState<WhySubject | null>(null);
  const [open, setOpen] = useState(false);
  const { byId } = useResources(plan.items.map((i) => i.resource_id));
  const days = planByDay(plan.items);
  const titleOf = (it: PlanItem) => itemTitle(it, it.resource_id ? byId[it.resource_id] : undefined, labelFor);
  const letter = revisionLabel ?? revisionLetter(plan.revision_no);

  function openWhy(item: PlanItem) {
    setWhy({
      title: `Why "${titleOf(item)}"`,
      reason: item.reason?.text,
      skillId: item.skill_id,
      evidenceIds: item.reason?.evidence_ids,
      graphPath: item.reason?.graph_path,
      decisionId: item.reason?.decision_id,
    });
    setOpen(true);
  }

  return (
    <div className="space-y-4">
      <BudgetBar usedMinutes={planMinutes(plan.items)} budgetMinutes={Math.round(plan.hours_budget * 60)} />
      <div className="plate divide-y divide-rule-strong">
        {days.map(({ day, items }) => (
          <section key={day} aria-label={dayLabel(day)}>
            <h3 className="draft border-b border-rule bg-plate/70 px-4 py-1.5 text-[0.9375rem] font-semibold">{dayLabel(day)}</h3>
            <div className="reg">
              {items.map((it) => (
                <PlanItemRow
                  key={it.item_id}
                  item={it}
                  resource={it.resource_id ? byId[it.resource_id] : undefined}
                  onWhy={openWhy}
                  changedIn={changedIds?.has(it.item_id) ? letter : undefined}
                  afterTitles={it.depends_on.map((id) => plan.items.find((p) => p.item_id === id)).filter((p): p is PlanItem => !!p).map(titleOf)}
                />
              ))}
            </div>
          </section>
        ))}
      </div>
      <WhyDrawer subject={why} open={open} onOpenChange={setOpen} />
    </div>
  );
}
