"use client";

import { useMemo, useState } from "react";
import { ClaimReview, EvidenceUploader } from "@/components/edupath/evidence-flow";
import { EvidenceCard, TierBadge } from "@/components/edupath/evidence";
import { SheetHeader } from "@/components/edupath/sheet-header";
import { EmptyState, ErrorState, LoadingState } from "@/components/edupath/states";
import { api } from "@/lib/api-client";
import { TIER_META } from "@/lib/format";
import { useEvidence } from "@/lib/hooks";
import { invalidate, useQuery } from "@/lib/query";
import type { Evidence, EvidenceTier } from "@/lib/types";
import { cn } from "@/lib/utils";

const TIERS: EvidenceTier[] = ["E3", "E2", "E1", "E0"];

export default function EvidencePage() {
  const { data, status, error, reload } = useEvidence();
  const pending = useQuery("pending", api.pendingClaims);
  const [tier, setTier] = useState<EvidenceTier | "all">("all");

  const counts = useMemo(() => {
    const c: Record<EvidenceTier, number> = { E0: 0, E1: 0, E2: 0, E3: 0 };
    (data ?? []).forEach((e) => (c[e.tier] += 1));
    return c;
  }, [data]);

  const grouped = useMemo(() => {
    const filtered = (data ?? []).filter((e) => tier === "all" || e.tier === tier);
    const map = new Map<string, Evidence[]>();
    filtered.forEach((e) => map.set(e.skill_id, [...(map.get(e.skill_id) ?? []), e]));
    return [...map.values()].sort((a, b) => a[0].skill_label.localeCompare(b[0].skill_label));
  }, [data, tier]);

  return (
    <div className="space-y-8">
      <SheetHeader title="Evidence" description="Every skill EduPath believes about you, with the words behind it and how strong that kind of evidence is." />

      {pending.data && pending.data.length > 0 && (
        <section aria-labelledby="ev-review" className="space-y-3">
          <div className="max-w-[62ch] space-y-1">
            <h2 id="ev-review" className="text-xl font-bold">{pending.data.length} to review</h2>
            <p className="text-[0.9375rem] text-ink-2">Found in your latest upload. Nothing counts as evidence until you confirm it.</p>
          </div>
          <ClaimReview
            claims={pending.data}
            onDone={() => {
              invalidate();
            }}
          />
        </section>
      )}

      <section aria-labelledby="ev-ledger" className="space-y-3">
        <div className="flex flex-wrap items-end justify-between gap-3">
          <h2 id="ev-ledger" className="text-xl font-bold">Ledger</h2>
          <div role="group" aria-label="Filter by tier" className="flex flex-wrap gap-1.5">
            <button
              type="button"
              aria-pressed={tier === "all"}
              onClick={() => setTier("all")}
              className={cn("min-h-11 cursor-pointer border px-3 text-[0.8125rem] font-semibold md:min-h-8", tier === "all" ? "border-ink bg-ink text-paper" : "border-rule-strong bg-paper hover:bg-plate")}
            >
              All <span className="draft">{data?.length ?? 0}</span>
            </button>
            {TIERS.map((t) => (
              <button
                key={t}
                type="button"
                aria-pressed={tier === t}
                disabled={counts[t] === 0}
                onClick={() => setTier(t)}
                title={TIER_META[t].meaning}
                className={cn("min-h-11 cursor-pointer border px-3 text-[0.8125rem] font-semibold md:min-h-8", tier === t ? "border-ink bg-ink text-paper" : "border-rule-strong bg-paper hover:bg-plate", counts[t] === 0 && "cursor-default opacity-40")}
              >
                {t} {TIER_META[t].short} <span className="draft">{counts[t]}</span>
              </button>
            ))}
          </div>
        </div>

        {status === "loading" && <LoadingState variant="grid" rows={4} label="Loading evidence" />}
        {status === "error" && <ErrorState error={error} onRetry={reload} />}
        {data && data.length === 0 && (
          <EmptyState title="No evidence yet">
            Upload a resume, notes or a GitHub repository below. EduPath quotes the exact words it finds, so every skill has a source.
          </EmptyState>
        )}
        {data && data.length > 0 && grouped.length === 0 && <EmptyState title="Nothing at this tier">Try another tier, or show all.</EmptyState>}

        <div className="grid gap-4 lg:grid-cols-2">
          {grouped.map((list) => (
            <article key={list[0].skill_id} className="plate p-4 sm:p-5">
              <header className="mb-3 flex flex-wrap items-center justify-between gap-2">
                <h3 className="text-lg font-bold">{list[0].skill_label}</h3>
                <TierBadge tier={[...list].sort((a, b) => b.tier.localeCompare(a.tier))[0].tier} showLabel={false} />
              </header>
              <div className="space-y-3">
                {list.map((e) => (
                  <EvidenceCard key={e.evidence_id} evidence={e} showSkill={false} />
                ))}
              </div>
            </article>
          ))}
        </div>
      </section>

      <section aria-labelledby="ev-add" className="space-y-3">
        <h2 id="ev-add" className="text-xl font-bold">Add evidence</h2>
        <EvidenceUploader />
      </section>
    </div>
  );
}
