import type { LoopStage } from "@/components/edupath/loop-ribbon";
import type { Evidence, GapReport, PlanItem, PlanRevision, WeeklyPlan } from "./types";

/** Drawing convention: revision 1 is "A", 2 is "B" ... */
export function revisionLetter(n: number): string {
  if (n < 1) return "-";
  let s = "";
  let x = n;
  while (x > 0) {
    x -= 1;
    s = String.fromCharCode(65 + (x % 26)) + s;
    x = Math.floor(x / 26);
  }
  return s;
}

export function planByDay(items: PlanItem[]): Array<{ day: number; items: PlanItem[] }> {
  const map = new Map<number, PlanItem[]>();
  [...items]
    .sort((a, b) => a.day_slot - b.day_slot)
    .forEach((i) => map.set(i.day_slot, [...(map.get(i.day_slot) ?? []), i]));
  return [...map.entries()].map(([day, list]) => ({ day, items: list }));
}

export function planMinutes(items: PlanItem[], statuses: PlanItem["status"][] = ["planned", "done"]): number {
  return items.filter((i) => statuses.includes(i.status)).reduce((s, i) => s + i.est_minutes, 0);
}

/** The adaptive loop, lit from what is actually true for this learner. */
export function loopStages(input: {
  evidence?: Evidence[];
  gaps?: GapReport;
  plan?: WeeklyPlan | null;
  revisions?: PlanRevision[];
  hasStruggle?: boolean;
}): LoopStage[] {
  const evidence = input.evidence ?? [];
  const revisions = input.revisions ?? [];
  const plan = input.plan ?? null;
  const reflected = revisions.some((r) => r.cause_type === "reflection");
  const assessed = evidence.some((e) => e.tier === "E3");
  const anyDone = (plan?.items ?? []).some((i) => i.status === "done");
  const acquired = (input.gaps?.strengths.length ?? 0) > 0;

  const done: boolean[] = [
    evidence.length > 0,
    evidence.length > 0 && !!input.gaps,
    !!input.gaps && input.gaps.gaps.some((g) => g.status !== "MET"),
    !!plan,
    anyDone,
    assessed,
    reflected || !!input.hasStruggle,
    reflected,
    reflected,
    acquired || (assessed && anyDone),
  ];
  const meta: Array<[string, string, string]> = [
    ["evidence", "Evidence", "Claims tied to source text"],
    ["understand", "Understand", "Each skill graded by tier"],
    ["diagnose", "Diagnose", "Gap to your target role"],
    ["plan", "Plan", "A week that fits your hours"],
    ["learn", "Learn", "Resources and practice"],
    ["assess", "Assess", "Checks that update mastery"],
    ["struggle", "Struggle", "Detected, never guessed"],
    ["reflect", "Reflect", "Root cause traced"],
    ["replan", "Re-plan", "A dated, reversible revision"],
    ["progress", "Progress", "Skills acquired"],
  ];
  const currentIndex = done.findIndex((d) => !d);
  return meta.map(([id, label, hint], i) => ({
    id,
    label,
    hint,
    state: done[i] ? "done" : i === currentIndex ? "current" : "todo",
  }));
}
