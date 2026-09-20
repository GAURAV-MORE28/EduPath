"use client";

import { ArrowRight, Check, History, RotateCcw } from "lucide-react";
import { AnimatePresence, motion, useInView, useReducedMotion } from "motion/react";
import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import { Button } from "@/components/ui/button";
import { api } from "@/lib/api-client";
import { revisionLetter } from "@/lib/derived";
import { OPERATOR_META, SIGNAL_META, dayLabel, humanizeText } from "@/lib/format";
import { useResources } from "@/lib/hooks";
import { invalidate, useQuery } from "@/lib/query";
import type { PlanItem, PlanRevision, PlanRevisionDetail } from "@/lib/types";
import { cn } from "@/lib/utils";
import { CitationBadge } from "./evidence";
import { useLearner } from "./learner-context";
import { RevisionMark, itemTitle } from "./plan";
import { DegradedNotice, ErrorState, LoadingState } from "./states";

/** Scalloped revision-cloud outline for a w x h box: arcs bulging outward, drawn clockwise. */
export function cloudPath(w: number, h: number, scallop = 13): string {
  const nx = Math.max(2, Math.round(w / scallop));
  const ny = Math.max(2, Math.round(h / scallop));
  const sx = w / nx;
  const sy = h / ny;
  const rx = sx / 2;
  const ry = sy / 2;
  let d = "M0 0";
  for (let i = 0; i < nx; i++) d += ` a ${rx} ${rx} 0 0 1 ${sx} 0`;
  for (let i = 0; i < ny; i++) d += ` a ${ry} ${ry} 0 0 1 0 ${sy}`;
  for (let i = 0; i < nx; i++) d += ` a ${rx} ${rx} 0 0 1 ${-sx} 0`;
  for (let i = 0; i < ny; i++) d += ` a ${ry} ${ry} 0 0 1 0 ${-sy}`;
  return d + " z";
}

/**
 * RevisionCloud: wraps content and, once `active`, draws the scalloped cloud
 * around it. This is how a drawing set marks a change, and the one authored
 * motion of the product: the outline is drawn stroke by stroke.
 */
export function RevisionCloud({ active, children, className }: { active: boolean; children: React.ReactNode; className?: string }) {
  const ref = useRef<HTMLDivElement>(null);
  const [size, setSize] = useState({ w: 0, h: 0 });
  const reduce = useReducedMotion();

  useLayoutEffect(() => {
    const el = ref.current;
    if (!el) return;
    const measure = () => setSize({ w: el.offsetWidth, h: el.offsetHeight });
    measure();
    const ro = new ResizeObserver(measure);
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  const pad = 6;
  return (
    <div ref={ref} className={cn("relative", className)}>
      {children}
      {size.w > 0 && (
        <svg
          aria-hidden
          className="pointer-events-none absolute overflow-visible"
          style={{ left: -pad, top: -pad }}
          width={size.w + pad * 2}
          height={size.h + pad * 2}
          viewBox={`0 0 ${size.w + pad * 2} ${size.h + pad * 2}`}
        >
          <motion.path
            d={cloudPath(size.w + pad * 2, size.h + pad * 2)}
            fill="none"
            stroke="var(--revision)"
            strokeWidth={1.5}
            strokeLinejoin="round"
            initial={false}
            animate={{ pathLength: active ? 1 : 0, opacity: active ? 1 : 0 }}
            transition={reduce ? { duration: 0 } : { pathLength: { duration: 0.9, ease: [0.16, 1, 0.3, 1] }, opacity: { duration: 0.1 } }}
          />
        </svg>
      )}
    </div>
  );
}

const keyOf = (i: PlanItem) => `${i.type}|${i.skill_id}|${i.resource_id ?? ""}`;

/** Compare two revisions' items by what they are (ids are fresh per revision). */
export function diffItems(before: PlanItem[], after: PlanItem[]) {
  const beforeKeys = new Map(before.map((i) => [keyOf(i), i]));
  const afterKeys = new Map(after.map((i) => [keyOf(i), i]));
  return {
    inserted: after.filter((i) => !beforeKeys.has(keyOf(i))),
    removed: before.filter((i) => !afterKeys.has(keyOf(i))),
    moved: after
      .filter((i) => beforeKeys.has(keyOf(i)) && beforeKeys.get(keyOf(i))!.day_slot !== i.day_slot)
      .map((i) => ({ item: i, from: beforeKeys.get(keyOf(i))!.day_slot })),
    carried: after.filter((i) => beforeKeys.has(keyOf(i))),
  };
}

function MiniItem({ item, title, sub, struck }: { item: PlanItem; title: string; sub?: string; struck?: boolean }) {
  return (
    <div className="flex items-start justify-between gap-3 p-3">
      <div className="min-w-0">
        <p className={cn("text-[0.9375rem] font-bold leading-snug", struck && "struck text-ink-2")}>{title}</p>
        <p className="text-[0.8125rem] text-ink-2">
          {dayLabel(item.day_slot)} · {item.est_minutes} min{sub ? ` · ${sub}` : ""}
        </p>
      </div>
    </div>
  );
}

interface Step {
  title: string;
  detail: string;
}

/**
 * AdaptiveMoment: the product's centrepiece. For one reflection revision it
 * shows the causal chain (assessment, misconception, prerequisite,
 * reflection, revision, new activity) and the plan before and after, with
 * the inserted work clouded. Everything is read from the stored revision,
 * its decision record and the catalog.
 */
export function AdaptiveMoment({ planId, revision, autoPlay = true }: { planId: string; revision: PlanRevision; autoPlay?: boolean }) {
  const { labelFor } = useLearner();
  const reduce = useReducedMotion();
  const rootRef = useRef<HTMLElement>(null);
  const inView = useInView(rootRef, { once: true, margin: "-15% 0px" });

  const after = useQuery(`rev:${revision.revision_id}`, () => api.revisionDetail(planId, revision.revision_id));
  const before = useQuery(revision.parent_revision_id ? `rev:${revision.parent_revision_id}` : null, () => api.revisionDetail(planId, revision.parent_revision_id!));
  const decision = useQuery(revision.decision_id ? `decision:${revision.decision_id}` : null, () => api.decision(revision.decision_id!));
  const struggling = (decision.data?.inputs?.struggling_skill_id as string | undefined) ?? null;
  const skill = useQuery(struggling ? `skill:${struggling}` : null, () => api.skillDetail(struggling!));
  const allItems = useMemo(() => [...(before.data?.items ?? []), ...(after.data?.items ?? [])], [before.data, after.data]);
  const { byId: resources } = useResources(allItems.map((i) => i.resource_id));

  const titleOf = useCallback((i: PlanItem) => itemTitle(i, i.resource_id ? resources[i.resource_id] : undefined, labelFor), [resources, labelFor]);

  const diff = useMemo(() => (before.data && after.data ? diffItems(before.data.items, after.data.items) : null), [before.data, after.data]);
  const letterBefore = revisionLetter(revision.revision_no - 1);
  const letterAfter = revisionLetter(revision.revision_no);

  // Playback: 0..6 lights the causal steps; then the plan opens up and the clouds draw.
  const [lit, setLit] = useState(0);
  const [phase, setPhase] = useState<"before" | "after" | "clouded">("before");
  const [runKey, setRunKey] = useState(0);
  const ready = !!diff && !!decision.data;
  // Reduced motion: show the finished state, no playback.
  const litSteps = reduce ? 6 : lit;
  const shownPhase = reduce ? "clouded" : phase;

  const play = useCallback(() => {
    setLit(0);
    setPhase("before");
    setRunKey((k) => k + 1);
  }, []);

  useEffect(() => {
    if (!ready || (!inView && autoPlay) || reduce) return;
    const timers: number[] = [];
    for (let i = 1; i <= 6; i++) timers.push(window.setTimeout(() => setLit(i), 380 * i));
    timers.push(window.setTimeout(() => setPhase("after"), 380 * 6 + 250));
    timers.push(window.setTimeout(() => setPhase("clouded"), 380 * 6 + 1100));
    return () => timers.forEach(window.clearTimeout);
  }, [ready, inView, autoPlay, reduce, runKey]);

  const [confirming, setConfirming] = useState(false);
  const [reverting, setReverting] = useState(false);
  const [revertError, setRevertError] = useState<string | null>(null);
  async function revert() {
    setReverting(true);
    setRevertError(null);
    try {
      await api.revertRevision(planId, revision.revision_id);
      invalidate();
    } catch (e) {
      setRevertError(e instanceof Error ? e.message : "Could not revert.");
      setReverting(false);
    }
  }

  if (after.status === "error" || before.status === "error") {
    return <ErrorState error={after.error ?? before.error} onRetry={() => { after.reload(); before.reload(); }} />;
  }
  if (!ready || !diff || !after.data || !before.data) return <LoadingState label="Loading the revision" variant="plate" />;

  const rootOp = revision.operators.find((o) => o.op === "INSERT_REMEDIATION");
  const rootSkillId = (rootOp?.params?.skill_id as string | undefined) ?? null;
  const misconception =
    skill.data?.misconceptions.find((m) => m.root_skill_id === rootSkillId && m.learner_status) ??
    skill.data?.misconceptions.find((m) => m.learner_status);
  const signalClass = decision.data?.inputs?.signal_class as string | undefined;
  const assessmentIds = (decision.data?.evidence_ids ?? []).filter((id) => id.startsWith("item."));
  const path = decision.data?.graph_paths?.[0];

  const steps: Step[] = [
    {
      title: struggling ? `Assessment on ${labelFor(struggling)}` : "Assessment",
      detail: assessmentIds.length ? `${assessmentIds.length} questions pointed to the same wrong idea.` : "The answers fell below the bar for this skill.",
    },
    {
      title: "Misconception detected",
      detail: misconception ? misconception.description : signalClass ? (SIGNAL_META[signalClass]?.meaning ?? "A pattern in your answers.") : "A pattern in your answers.",
    },
    {
      title: rootSkillId ? `Root cause: ${labelFor(rootSkillId)}` : "Prerequisite identified",
      detail: path && path.length > 1 ? path.map(labelFor).join(" → ") : "A skill this one depends on needs a refresher.",
    },
    {
      title: revision.degraded ? "Reflection (rule-based)" : "Reflection agent",
      detail: revision.degraded ? "No language model was available, so fixed rules chose the fix." : "The reflection agent proposed the fix; rules checked it.",
    },
    {
      title: `Revision ${letterAfter}`,
      detail: revision.operators.map((o) => OPERATOR_META[o.op]?.verb ?? o.op).join(", ") || "Plan updated",
    },
    {
      title: "New activity",
      detail: diff.inserted.length ? diff.inserted.map(titleOf).join("; ") : "No new items were needed.",
    },
  ];

  const visibleAfter = shownPhase === "before" ? diff.carried : after.data.items;
  const sortedAfter = [...visibleAfter].sort((a, b) => a.day_slot - b.day_slot);
  const insertedKeys = new Set(diff.inserted.map(keyOf));
  const movedByKey = new Map(diff.moved.map((m) => [keyOf(m.item), m.from]));

  return (
    <section ref={rootRef} aria-labelledby="moment-title" className="space-y-5">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div className="space-y-1">
          <h2 id="moment-title" className="text-2xl font-bold">Why did my plan change?</h2>
          <p className="max-w-[62ch] text-[0.9375rem] text-ink-2">
            Revision {letterAfter} was drawn after your assessment, from the evidence below. Revision {letterBefore} is kept, and you can go back to it.
          </p>
        </div>
        <Button variant="outline" size="sm" onClick={play}>
          <RotateCcw /> Replay
        </Button>
      </div>

      {/* Causal chain */}
      <ol className="grid gap-px border border-rule-strong bg-rule-strong sm:grid-cols-2 xl:grid-cols-6" aria-label="How the change was decided">
        {steps.map((s, i) => {
          const on = litSteps > i;
          return (
            <li key={s.title} className="relative bg-paper p-3.5 sm:min-h-[8.5rem]" aria-current={litSteps === i + 1 ? "step" : undefined}>
              <motion.div
                className="absolute inset-x-0 top-0 h-[3px] origin-left bg-revision"
                initial={false}
                animate={{ scaleX: on ? 1 : 0 }}
                transition={reduce ? { duration: 0 } : { duration: 0.35, ease: [0.16, 1, 0.3, 1] }}
                aria-hidden
              />
              <div className="mb-2 flex items-center gap-2">
                <span className={cn("draft grid size-6 place-items-center border text-[0.8125rem] font-semibold transition-colors duration-200", on ? "border-revision bg-revision text-paper" : "border-rule-strong text-ink-3")}>
                  {on && i === 5 ? <Check className="size-3.5" strokeWidth={3} /> : i + 1}
                </span>
                {i < steps.length - 1 && <ArrowRight className="size-3.5 text-ink-3 xl:ml-auto" aria-hidden />}
              </div>
              <h3 className={cn("text-[0.9375rem] font-bold leading-snug", !on && "text-ink-3")}>{s.title}</h3>
              <p className={cn("mt-1 text-[0.8125rem] leading-snug", on ? "text-ink-2" : "text-ink-3")}>{humanizeText(s.detail, labelFor)}</p>
            </li>
          );
        })}
      </ol>

      {/* Before / after */}
      <div className="grid items-start gap-4 lg:grid-cols-2">
        <div className="plate">
          <h3 className="flex items-center justify-between border-b border-rule-strong bg-plate/70 px-4 py-2 text-base font-bold">
            <span>Before</span>
            <span className="draft text-ink-2">Revision {letterBefore}</span>
          </h3>
          <ul className="reg">
            {[...before.data.items].sort((a, b) => a.day_slot - b.day_slot).map((i) => (
              <li key={i.item_id}>
                <MiniItem item={i} title={titleOf(i)} sub={labelFor(i.skill_id)} struck={diff.removed.some((r) => r.item_id === i.item_id)} />
              </li>
            ))}
            {before.data.items.length === 0 && <li className="p-4 text-[0.875rem] text-ink-2">This revision had no items.</li>}
          </ul>
        </div>

        <div className="plate border-revision">
          <h3 className="flex items-center justify-between border-b border-revision bg-revision-wash/50 px-4 py-2 text-base font-bold">
            <span>After</span>
            <span className="draft inline-flex items-center gap-2 text-revision">
              Revision {letterAfter} <RevisionMark letter={letterAfter} />
            </span>
          </h3>
          <ul className="reg overflow-hidden">
            <AnimatePresence initial={false} mode="popLayout">
              {sortedAfter.map((i) => {
                const inserted = insertedKeys.has(keyOf(i));
                const from = movedByKey.get(keyOf(i));
                return (
                  <motion.li
                    key={keyOf(i)}
                    layout={!reduce}
                    initial={reduce ? false : { opacity: 0, height: 0 }}
                    animate={{ opacity: 1, height: "auto" }}
                    exit={{ opacity: 0, height: 0 }}
                    transition={{ type: "spring", stiffness: 380, damping: 38, mass: 0.9 }}
                    className={cn(inserted && "bg-revision-wash/40")}
                  >
                    <div className={inserted ? "px-4 py-3.5" : undefined}>
                    <RevisionCloud active={inserted && shownPhase === "clouded"}>
                      <div className="flex items-start gap-2 pr-3">
                        <div className="min-w-0 flex-1">
                          <MiniItem item={i} title={titleOf(i)} sub={labelFor(i.skill_id)} />
                          {from !== undefined && (
                            <p className="px-3 pb-3 text-[0.8125rem] font-semibold text-ink-2">Moved from {dayLabel(from)}</p>
                          )}
                        </div>
                        {inserted && shownPhase !== "before" && <RevisionMark letter={letterAfter} className="mt-3" />}
                      </div>
                    </RevisionCloud>
                    </div>
                  </motion.li>
                );
              })}
            </AnimatePresence>
          </ul>
        </div>
      </div>

      {/* The reasons and evidence */}
      <div className="plate-quiet space-y-4 p-4 sm:p-5">
        <p className="max-w-[66ch] text-[1rem] leading-relaxed">{humanizeText(revision.overall_reason, labelFor)}</p>
        {(assessmentIds.length > 0 || path) && (
          <div className="space-y-2">
            <p className="text-[0.875rem] font-bold">Evidence behind this change</p>
            <ul className="flex flex-wrap gap-2">
              {assessmentIds.map((id) => {
                const m = /^item\.(.+)\.(\d+)$/.exec(id);
                return (
                  <li key={id}>
                    <CitationBadge kind="assessment" label={m ? `${labelFor(`skill.${m[1]}`)}, question ${m[2]}` : id} />
                  </li>
                );
              })}
              {path && path.length > 1 && (
                <li>
                  <CitationBadge kind="graph" label={`Graph path: ${path.map(labelFor).join(" → ")}`} />
                </li>
              )}
              {decision.data && (
                <li>
                  <CitationBadge kind="decision" label={`Decision record, graph ${decision.data.graph_version}`} />
                </li>
              )}
            </ul>
          </div>
        )}
        {revision.degraded && <DegradedNotice>Reflection ran on its rules, not a model. The evidence and the graph path above are the same either way.</DegradedNotice>}
        {revision.is_current && (
          <div className="flex flex-wrap items-center gap-3 border-t border-rule pt-4">
            {!confirming ? (
              <Button variant="revision" onClick={() => setConfirming(true)}>
                <RotateCcw /> Revert to revision {letterBefore}
              </Button>
            ) : (
              <>
                <p className="text-[0.875rem] font-semibold">Restore revision {letterBefore}? Revision {letterAfter} stays in the history.</p>
                <Button variant="revision" onClick={revert} disabled={reverting} aria-busy={reverting}>
                  {reverting ? "Reverting" : `Yes, restore ${letterBefore}`}
                </Button>
                <Button variant="ghost" onClick={() => setConfirming(false)} disabled={reverting}>
                  Keep {letterAfter}
                </Button>
              </>
            )}
            {revertError && <p role="alert" className="text-[0.8125rem] font-semibold text-revision">{revertError}</p>}
          </div>
        )}
      </div>
    </section>
  );
}

/** Ids of current-plan items that the latest reflection revision added (compared by what they are, see diffItems). */
export function useChangedItemIds(plan: { plan_id: string; items: PlanItem[] } | null | undefined, revisions: PlanRevision[] | undefined) {
  const current = revisions?.find((r) => r.is_current);
  const parentId = current?.cause_type === "reflection" ? current.parent_revision_id : null;
  const parent = useQuery(parentId && plan ? `rev:${parentId}` : null, () => api.revisionDetail(plan!.plan_id, parentId!));
  return useMemo(
    () => (plan && parent.data ? new Set(diffItems(parent.data.items, plan.items).inserted.map((i) => i.item_id)) : undefined),
    [plan, parent.data],
  );
}

/** RevisionHistory: every revision of the plan, newest first, like a revision table on a sheet. */
export function RevisionHistory({ revisions }: { revisions: PlanRevision[] }) {
  const { labelFor } = useLearner();
  const list = [...revisions].sort((a, b) => b.revision_no - a.revision_no);
  return (
    <section aria-labelledby="rev-history" className="space-y-3">
      <h2 id="rev-history" className="flex items-center gap-2 text-xl font-bold">
        <History className="size-5" aria-hidden /> Revision history
      </h2>
      <div className="plate overflow-x-auto scroll-fine">
        <table className="w-full min-w-[32rem] text-left text-[0.875rem]">
          <caption className="sr-only">Revisions of your plan, newest first</caption>
          <thead className="border-b border-rule-strong bg-plate/70">
            <tr>
              <th scope="col" className="w-16 px-4 py-2 font-semibold">Rev</th>
              <th scope="col" className="px-4 py-2 font-semibold">Cause</th>
              <th scope="col" className="px-4 py-2 font-semibold">Changes</th>
              <th scope="col" className="px-4 py-2 font-semibold">Date</th>
            </tr>
          </thead>
          <tbody className="reg">
            {list.map((r) => (
              <tr key={r.revision_id}>
                <td className="draft px-4 py-3 text-[1.125rem] font-semibold">
                  {revisionLetter(r.revision_no)}
                  {r.is_current && <span className="ml-2 border border-ink px-1 py-px text-[0.6875rem] font-semibold">current</span>}
                </td>
                <td className="px-4 py-3">
                  {r.cause_type === "initial" ? "First plan" : r.cause_type === "reflection" ? "Reflection after an assessment" : r.cause_type === "user_override" ? (r.diff.reverted_revision_id ? "You reverted a revision" : "Your change") : r.cause_type}
                  {r.reverted_by && <span className="ml-2 text-ink-2">(reverted)</span>}
                  {r.degraded && <span className="ml-2 text-ink-2">rule-based</span>}
                </td>
                <td className="px-4 py-3 text-ink-2">
                  {r.operators.length ? r.operators.map((o) => OPERATOR_META[o.op]?.verb ?? o.op).join(", ") : "None"}
                  {r.operators.length > 0 && r.operators[0].params?.skill_id ? `: ${labelFor(String(r.operators[0].params.skill_id))}` : ""}
                </td>
                <td className="whitespace-nowrap px-4 py-3 text-ink-2">{r.created_at ? new Date(r.created_at).toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" }) : ""}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}

export type { PlanRevisionDetail };
