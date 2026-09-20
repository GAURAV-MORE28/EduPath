import { cn } from "@/lib/utils";
import { SKILL_STATE_META, type SkillState } from "@/lib/format";

/**
 * SkillGlyph: a skill's state drawn as line form, never hue alone.
 *   mastered   double ring, filled, tick
 *   developing single ring, lower half filled
 *   weak       single ring, solid, short bar inside
 *   unverified dotted ring
 *   missing    long-dash ring, empty
 *   blocked    square, struck through
 * Verified/mastered take viridian; everything else takes ink. Blocked and
 * struggle take no extra hue: the strike is the signal.
 */
export function SkillGlyph({
  state,
  size = 20,
  className,
  title,
}: {
  state: SkillState;
  size?: number;
  className?: string;
  title?: string;
}) {
  const stroke = state === "mastered" ? "var(--verified)" : "var(--ink)";
  const common = { fill: "none", stroke, strokeWidth: 1.5 } as const;
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 20 20"
      {...(title === ""
        ? { "aria-hidden": true }
        : { role: "img", "aria-label": title ?? SKILL_STATE_META[state].label })}
      className={cn("shrink-0", className)}
    >
      {state === "mastered" && (
        <>
          <circle cx="10" cy="10" r="8.5" {...common} />
          <circle cx="10" cy="10" r="6" fill="var(--verified)" stroke="none" />
          <path d="M7 10.2l2.2 2.2L13.2 8" fill="none" stroke="var(--paper)" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" />
        </>
      )}
      {state === "developing" && (
        <>
          <circle cx="10" cy="10" r="8" {...common} />
          <path d="M2 10a8 8 0 0 0 16 0z" fill="var(--ink)" />
        </>
      )}
      {state === "weak" && (
        <>
          <circle cx="10" cy="10" r="8" {...common} />
          <path d="M6.5 10h7" stroke="var(--ink)" strokeWidth="1.8" strokeLinecap="round" />
        </>
      )}
      {state === "unverified" && <circle cx="10" cy="10" r="8" {...common} strokeDasharray="0.1 3.2" strokeLinecap="round" strokeWidth={2.2} />}
      {state === "missing" && <circle cx="10" cy="10" r="8" {...common} strokeDasharray="5 3" />}
      {state === "blocked" && (
        <>
          <rect x="2.5" y="2.5" width="15" height="15" {...common} />
          <path d="M3 17L17 3" stroke="var(--ink)" strokeWidth="1.5" />
        </>
      )}
    </svg>
  );
}

/** SkillStatus: glyph plus its word. The word is always present for assistive tech and sighted users alike. */
export function SkillStatus({
  state,
  className,
  compact = false,
}: {
  state: SkillState;
  className?: string;
  compact?: boolean;
}) {
  return (
    <span className={cn("inline-flex items-center gap-1.5 text-[0.8125rem] font-semibold text-ink", className)}>
      <SkillGlyph state={state} size={16} title="" />
      <span className={cn(compact && "sr-only")}>{SKILL_STATE_META[state].label}</span>
    </span>
  );
}

/** SkillChip: a skill name with its state, used inline in registers and lists. */
export function SkillChip({
  label,
  state,
  className,
  struck,
}: {
  label: string;
  state?: SkillState;
  className?: string;
  struck?: boolean;
}) {
  return (
    <span className={cn("inline-flex items-center gap-1.5 border border-rule-strong bg-paper px-2 py-1 text-[0.8125rem] font-medium", className)}>
      {state && <SkillGlyph state={state} size={14} title={SKILL_STATE_META[state].label} />}
      <span className={cn(struck && "struck")}>{label}</span>
    </span>
  );
}

/** The legend: the six line forms with their meanings. */
export function StateLegend({ className, states }: { className?: string; states?: SkillState[] }) {
  const list = states ?? (Object.keys(SKILL_STATE_META) as SkillState[]);
  return (
    <ul className={cn("flex flex-wrap gap-x-4 gap-y-2", className)} aria-label="Skill state legend">
      {list.map((s) => (
        <li key={s} className="inline-flex items-center gap-1.5 text-[0.8125rem] text-ink-2">
          <SkillGlyph state={s} size={16} title="" />
          {SKILL_STATE_META[s].label}
        </li>
      ))}
    </ul>
  );
}
