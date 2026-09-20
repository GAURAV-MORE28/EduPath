import type { EvidenceTier, GapStatus, SkillGap } from "./types";

/** `skill.chain_rule` -> "Chain rule" (used only when the catalog label is not loaded yet). */
export function humanizeId(id: string): string {
  const tail = id.replace(/^(skill|role|res|misc|item|obj)\./, "").split(".").pop() ?? id;
  const words = tail.replace(/_/g, " ").trim();
  return words.charAt(0).toUpperCase() + words.slice(1);
}

/** Replace raw ids inside backend display text with catalog labels. */
export function humanizeText(text: string, labelFor: (skillId: string) => string): string {
  return text
    .replace(/\s*(?:for|by)?\s*objective\s+obj\.[\w.]+/gi, "")
    .replace(/obj\.[\w.]+/g, "")
    .replace(/\bskill\.[a-z0-9_]+\b/g, (m) => labelFor(m))
    .replace(/\s+--\s+/g, ": ")
    .replace(/\(s\)/g, "s")
    .replace(/:\s+-\s+/g, ": ")
    .replace(/\s{2,}/g, " ")
    .replace(/\s+([.,;:])/g, "$1")
    .trim();
}

/** The six states a skill can be shown in. */
export type SkillState = "mastered" | "developing" | "weak" | "unverified" | "missing" | "blocked";

export const SKILL_STATE_ORDER: SkillState[] = ["mastered", "developing", "weak", "unverified", "missing", "blocked"];

export const SKILL_STATE_META: Record<SkillState, { label: string; meaning: string }> = {
  mastered: { label: "Mastered", meaning: "Evidence meets the level this role needs." },
  developing: { label: "Developing", meaning: "Some evidence, but below the level this role needs." },
  weak: { label: "Weak", meaning: "Evidence exists but sits below foundational level." },
  unverified: { label: "Unverified", meaning: "Claimed, but nothing yet proves it. A short probe comes first." },
  missing: { label: "Missing", meaning: "No evidence of this skill yet." },
  blocked: { label: "Blocked", meaning: "A prerequisite is weak or missing. Start there." },
};

export function skillStateOf(status: GapStatus, currentLevel: number): SkillState {
  switch (status) {
    case "MET":
      return "mastered";
    case "BLOCKED":
      return "blocked";
    case "UNVERIFIED":
      return "unverified";
    case "MISSING":
      return "missing";
    default:
      return currentLevel >= 1 ? "developing" : "weak";
  }
}

export const gapState = (g: Pick<SkillGap, "status" | "current_level">) => skillStateOf(g.status, g.current_level);

export const TIER_META: Record<EvidenceTier, { label: string; short: string; meaning: string }> = {
  E0: { label: "Self-reported", short: "Listed", meaning: "You said so. Never enough on its own to meet a requirement." },
  E1: { label: "Documented", short: "In context", meaning: "Described in your resume or notes with context." },
  E2: { label: "Artifact-verifiable", short: "Verifiable", meaning: "Backed by an artifact such as a repository or certificate." },
  E3: { label: "Assessed", short: "Assessed", meaning: "Shown in an EduPath assessment. The strongest tier." },
};

export const LEVEL_LABEL: Record<number, string> = {
  0: "Not yet",
  1: "Foundational",
  2: "Working",
  3: "Proficient",
};

export const SIGNAL_META: Record<string, { label: string; meaning: string }> = {
  low_score: { label: "Low score", meaning: "Most answers in this set were wrong." },
  repeated_misconception: {
    label: "Repeated misconception",
    meaning: "The same wrong idea showed up in several answers.",
  },
  missing_prerequisite: {
    label: "Prerequisite gap",
    meaning: "A skill this one depends on looks shaky.",
  },
  excessive_difficulty: { label: "Too hard right now", meaning: "The material sits above your current level." },
  cognitive_overload: { label: "Overloaded", meaning: "Several signals suggest too much at once." },
  insufficient_practice: { label: "Needs more practice", meaning: "Too few attempts to judge yet." },
};

export const OPERATOR_META: Record<string, { label: string; verb: string }> = {
  INSERT_REMEDIATION: { label: "Insert remediation", verb: "Added a refresher" },
  ADD_PROBE: { label: "Add probe", verb: "Added a check" },
  DEFER: { label: "Defer", verb: "Moved later" },
  REMOVE_DUPLICATE: { label: "Remove duplicate", verb: "Removed a repeat" },
  REPLACE_RESOURCE: { label: "Replace resource", verb: "Swapped the resource" },
  SPLIT_ACTIVITY: { label: "Split activity", verb: "Split into shorter sessions" },
};

export const ITEM_TYPE_LABEL: Record<string, string> = {
  resource: "Learn",
  practice: "Practice",
  project: "Project",
  probe: "Probe",
  review: "Refresher",
};

export const MODALITY_LABEL: Record<string, string> = { watch: "Watch", read: "Read", do: "Do" };
export const DIFFICULTY_LABEL: Record<number, string> = { 1: "Foundational", 2: "Working", 3: "Proficient" };
const CONF_RANK: Record<string, number> = { low: 0, medium: 1, high: 2 };

/** One signal per (class, skill), keeping the most confident: the classifier can emit the same class at several confidences. */
export function dedupeSignals<T extends { signal_class: string | null; skill_id: string; confidence: string | null }>(signals: T[]): T[] {
  const best = new Map<string, T>();
  signals.forEach((s) => {
    const k = `${s.signal_class ?? "low_score"}|${s.skill_id}`;
    const cur = best.get(k);
    if (!cur || (CONF_RANK[s.confidence ?? "low"] ?? 0) > (CONF_RANK[cur.confidence ?? "low"] ?? 0)) best.set(k, s);
  });
  return [...best.values()];
}

/** Group signals by skill so one struggling skill is one alert, listing each thing noticed. */
export function groupSignalsBySkill<T extends { signal_class: string | null; skill_id: string; confidence: string | null }>(signals: T[]) {
  const bySkill = new Map<string, T[]>();
  dedupeSignals(signals).forEach((s) => bySkill.set(s.skill_id, [...(bySkill.get(s.skill_id) ?? []), s]));
  return [...bySkill.entries()].map(([skill_id, list]) => ({
    skill_id,
    signals: list.sort((a, b) => (CONF_RANK[b.confidence ?? "low"] ?? 0) - (CONF_RANK[a.confidence ?? "low"] ?? 0)),
  }));
}

export const CONFIDENCE_LABEL: Record<string, string> = { low: "Low confidence", medium: "Medium confidence", high: "High confidence" };

export function minutes(n: number): string {
  if (n < 60) return `${n} min`;
  const h = Math.floor(n / 60);
  const m = n % 60;
  return m ? `${h} h ${m} min` : `${h} h`;
}

export function hours(min: number): string {
  const h = min / 60;
  return `${Number.isInteger(h) ? h : h.toFixed(1)} h`;
}

export function pct(x: number): string {
  return `${Math.round(x * 100)}%`;
}

export function dayLabel(slot: number): string {
  return `Day ${slot}`;
}
