"use client";

import { motion } from "motion/react";
import { SKILL_STATE_META, SKILL_STATE_ORDER, type SkillState } from "@/lib/format";
import { cn } from "@/lib/utils";
import { SkillGlyph } from "./skill-status";

/** Line-form fills so each state reads without colour. */
const FILL: Record<SkillState, React.CSSProperties> = {
  mastered: { background: "var(--verified)" },
  developing: { background: "repeating-linear-gradient(135deg,var(--ink) 0 2px,var(--paper) 2px 6px)" },
  weak: { background: "linear-gradient(var(--ink-3),var(--ink-3))", backgroundSize: "100% 40%", backgroundRepeat: "no-repeat", backgroundPosition: "0 50%", backgroundColor: "var(--paper)" },
  unverified: { background: "radial-gradient(circle,var(--ink) 1px,transparent 1.5px) 0 0/6px 6px, var(--paper)" },
  missing: { background: "var(--paper)" },
  blocked: { background: "repeating-linear-gradient(45deg,var(--rule-strong) 0 1px,var(--plate) 1px 5px)" },
};

/**
 * StateBar: how many skills sit in each state, as one ruled bar plus a
 * legend register with counts. Segment widths animate when a count changes.
 */
export function StateBar({ counts, className }: { counts: Record<SkillState, number>; className?: string }) {
  const total = SKILL_STATE_ORDER.reduce((s, k) => s + counts[k], 0) || 1;
  return (
    <div className={cn("space-y-3", className)}>
      <div className="flex h-6 border border-ink" role="img" aria-label={SKILL_STATE_ORDER.map((k) => `${counts[k]} ${SKILL_STATE_META[k].label.toLowerCase()}`).join(", ")}>
        {SKILL_STATE_ORDER.filter((k) => counts[k] > 0).map((k) => (
          <motion.div
            key={k}
            className={cn("h-full border-r border-ink last:border-r-0", k === "missing" && "border-dashed")}
            style={FILL[k]}
            initial={false}
            animate={{ width: `${(counts[k] / total) * 100}%` }}
            transition={{ duration: 0.5, ease: [0.16, 1, 0.3, 1] }}
          />
        ))}
      </div>
      <ul className="grid grid-cols-2 gap-x-4 gap-y-1.5 sm:grid-cols-3">
        {SKILL_STATE_ORDER.map((k) => (
          <li key={k} className={cn("flex items-center gap-2 text-[0.875rem]", counts[k] === 0 && "text-ink-3")}>
            <SkillGlyph state={k} size={16} title="" />
            <span className="flex-1">{SKILL_STATE_META[k].label}</span>
            <span className="draft text-[1rem] font-semibold">{counts[k]}</span>
          </li>
        ))}
      </ul>
    </div>
  );
}
