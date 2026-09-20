import { FileText, GitBranch, PenLine, ShieldCheck, FlaskConical } from "lucide-react";
import { cn } from "@/lib/utils";
import { TIER_META } from "@/lib/format";
import type { Evidence, EvidenceTier } from "@/lib/types";

/** Tier drawn as stacked rules: E0 one rule ... E3 four. The count is the tier, the label states it. */
export function TierBadge({ tier, className, showLabel = true }: { tier: EvidenceTier; className?: string; showLabel?: boolean }) {
  const n = Number(tier.slice(1)) + 1;
  const meta = TIER_META[tier];
  return (
    <span
      className={cn("inline-flex items-center gap-2 text-[0.8125rem] font-semibold", className)}
      title={meta.meaning}
      aria-label={`Evidence tier ${tier}: ${meta.label}`}
    >
      <span className="draft inline-flex h-5 min-w-7 items-center justify-center border border-ink bg-paper px-1 text-[0.8125rem] leading-none">
        {tier}
      </span>
      <span className="hidden flex-col gap-[2px] sm:flex" aria-hidden>
        {[3, 2, 1, 0].map((i) => (
          <span key={i} className={cn("block h-px w-4", i < n ? "bg-ink" : "bg-rule")} />
        ))}
      </span>
      {showLabel && <span className="text-ink-2">{meta.label}</span>}
    </span>
  );
}

/**
 * CitationBadge: a compact pointer to a piece of evidence or a decision.
 * A citation is how any claim in the UI points back at its source.
 */
export function CitationBadge({
  kind,
  label,
  className,
}: {
  kind: "evidence" | "assessment" | "decision" | "graph" | "resource";
  label: string;
  className?: string;
}) {
  const Icon = kind === "assessment" ? FlaskConical : kind === "decision" || kind === "graph" ? ShieldCheck : FileText;
  return (
    <span className={cn("inline-flex max-w-full items-center gap-1 border border-rule-strong bg-paper px-1.5 py-0.5 text-[0.8125rem] text-ink-2", className)}>
      <Icon className="size-3.5 shrink-0" aria-hidden />
      <span className="truncate">{label}</span>
    </span>
  );
}

const SOURCE_LABEL: Record<string, string> = {
  intake: "Your intake form",
  document: "Uploaded document",
  github: "GitHub repository",
  assessment: "EduPath assessment",
};

function SourceIcon({ type }: { type: string }) {
  const cls = "size-4 shrink-0";
  if (type === "github") return <GitBranch className={cls} aria-hidden />;
  if (type === "intake") return <PenLine className={cls} aria-hidden />;
  if (type === "assessment") return <FlaskConical className={cls} aria-hidden />;
  return <FileText className={cls} aria-hidden />;
}

/**
 * EvidenceCard: a skill claim with the words that back it, where they came
 * from, and how strong that evidence is. This is EduPath's central object.
 */
export function EvidenceCard({ evidence, className, showSkill = true }: { evidence: Evidence; className?: string; showSkill?: boolean }) {
  const source = evidence.document_label ?? SOURCE_LABEL[evidence.source_type] ?? evidence.source_type;
  const spanLabel =
    evidence.span_offsets && evidence.source_type !== "intake"
      ? `characters ${evidence.span_offsets.start}–${evidence.span_offsets.end}`
      : null;
  return (
    <article className={cn("plate-quiet p-4", className)}>
      <header className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1">
        {showSkill && <h3 className="text-base font-bold">{evidence.skill_label}</h3>}
        <TierBadge tier={evidence.tier} />
      </header>
      {evidence.source_type === "assessment" ? (
        <p className="mt-3 text-[0.9375rem] leading-relaxed">
          {(() => {
            const m = /(\d+)\/(\d+) correct/.exec(evidence.span_text);
            return m ? `Answered ${m[1]} of ${m[2]} questions correctly in an EduPath assessment.` : "Shown in an EduPath assessment.";
          })()}
        </p>
      ) : evidence.span_text ? (
        <blockquote className="mt-3 border-l border-rule-strong pl-3 text-[0.9375rem] leading-relaxed text-ink">
          &ldquo;{evidence.span_text}&rdquo;
        </blockquote>
      ) : (
        <p className="mt-3 text-[0.9375rem] text-ink-2">No text span. This evidence is a record, not a quotation.</p>
      )}
      <footer className="mt-3 flex flex-wrap items-center gap-x-3 gap-y-1 text-[0.8125rem] text-ink-2">
        <span className="inline-flex items-center gap-1.5">
          <SourceIcon type={evidence.source_type} />
          <span className="break-all">{source}</span>
        </span>
        {spanLabel && <span>{spanLabel}</span>}
        {evidence.verified && (
          <span className="inline-flex items-center gap-1 font-semibold text-verified">
            <ShieldCheck className="size-3.5" aria-hidden /> Span verified
          </span>
        )}
      </footer>
    </article>
  );
}
