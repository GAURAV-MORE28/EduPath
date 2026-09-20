"use client";

import { Check, FileUp, GitBranch, Trash2, Upload } from "lucide-react";
import { useCallback, useId, useMemo, useRef, useState } from "react";
import { Button } from "@/components/ui/button";
import { DEMO_MODE, api } from "@/lib/api-client";
import { useSkillIndex } from "@/lib/hooks";
import { invalidate } from "@/lib/query";
import { traced, useTraceRuns } from "@/lib/trace-store";
import type { ClaimDecision, DocumentUploadResponse, PendingClaim } from "@/lib/types";
import { cn } from "@/lib/utils";
import { AgentTrace } from "./agent-trace";
import { TierBadge } from "./evidence";
import { DegradedNotice, ErrorState } from "./states";

const ACCEPT = ".pdf,.docx,.txt,.md,.png,.jpg,.jpeg";

interface UploadedDoc {
  name: string;
  result: DocumentUploadResponse;
}

/**
 * EvidenceUploader: adds a resume/notes file or a GitHub repository. Each
 * upload runs the real profiling pipeline; its trace streams live beneath.
 */
export function EvidenceUploader({ onUploaded, className }: { onUploaded?: (d: UploadedDoc) => void; className?: string }) {
  const inputId = useId();
  const fileRef = useRef<HTMLInputElement>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const [docs, setDocs] = useState<UploadedDoc[]>([]);
  const [repo, setRepo] = useState("");
  const [runId, setRunId] = useState<string | undefined>();
  const [dragging, setDragging] = useState(false);
  const runs = useTraceRuns();
  const run = runs.find((r) => r.runId === runId);

  const submit = useCallback(
    async (label: string, form: FormData) => {
      setBusy(true);
      setError(null);
      try {
        const result = await traced(`Reading ${label}`, (id) => {
          setRunId(id);
          return api.uploadDocument(form, id);
        });
        const doc = { name: label, result };
        setDocs((d) => [...d, doc]);
        invalidate("pending");
        onUploaded?.(doc);
      } catch (e) {
        setError(e);
      } finally {
        setBusy(false);
      }
    },
    [onUploaded],
  );

  const uploadFile = (file: File) => {
    const form = new FormData();
    form.append("file", file);
    return submit(file.name, form);
  };

  async function uploadDemoResume() {
    const res = await fetch("/demo/asha-resume.md");
    const blob = await res.blob();
    return uploadFile(new File([blob], "asha-resume.md", { type: "text/markdown" }));
  }

  return (
    <div className={cn("space-y-4", className)}>
      <div
        onDragOver={(e) => {
          e.preventDefault();
          setDragging(true);
        }}
        onDragLeave={() => setDragging(false)}
        onDrop={(e) => {
          e.preventDefault();
          setDragging(false);
          const f = e.dataTransfer.files?.[0];
          if (f) void uploadFile(f);
        }}
        className={cn("border border-dashed p-5 transition-colors duration-150 sm:p-6", dragging ? "border-ink bg-plate" : "border-rule-strong bg-paper")}
      >
        <div className="flex flex-wrap items-center gap-4">
          <FileUp className="size-7 text-ink-2" aria-hidden />
          <div className="min-w-[14rem] flex-1 space-y-1">
            <label htmlFor={inputId} className="text-[1rem] font-bold">
              Add a resume, notes or certificate
            </label>
            <p className="text-[0.875rem] text-ink-2">PDF, DOCX, text or Markdown, up to a few MB. EduPath quotes your own words back to you, so text files work best.</p>
          </div>
          <input
            id={inputId}
            ref={fileRef}
            type="file"
            accept={ACCEPT}
            className="sr-only"
            onChange={(e) => {
              const f = e.target.files?.[0];
              if (f) void uploadFile(f);
              e.target.value = "";
            }}
          />
          <Button onClick={() => fileRef.current?.click()} disabled={busy} aria-busy={busy}>
            <Upload /> {busy ? "Reading" : "Choose file"}
          </Button>
        </div>
      </div>

      <form
        className="flex flex-wrap items-end gap-3"
        onSubmit={(e) => {
          e.preventDefault();
          if (!repo.trim()) return;
          const form = new FormData();
          form.append("github_url", repo.trim());
          void submit(repo.trim(), form).then(() => setRepo(""));
        }}
      >
        <div className="min-w-[16rem] flex-1 space-y-1">
          <label htmlFor={`${inputId}-gh`} className="flex items-center gap-1.5 text-[0.9375rem] font-bold">
            <GitBranch className="size-4" aria-hidden /> Or a public GitHub repository
          </label>
          <input
            id={`${inputId}-gh`}
            type="url"
            inputMode="url"
            placeholder="https://github.com/you/project"
            value={repo}
            onChange={(e) => setRepo(e.target.value)}
            className="min-h-11 w-full border border-rule-strong bg-paper px-3 text-[0.9375rem] placeholder:text-ink-3 md:min-h-10"
          />
        </div>
        <Button variant="outline" type="submit" disabled={busy || !repo.trim()}>
          Read repository
        </Button>
      </form>

      {DEMO_MODE && (
        <div className="flex flex-wrap items-center gap-3 border border-dashed border-ink-3 bg-paper px-4 py-3">
          <p className="min-w-[14rem] flex-1 text-[0.875rem] text-ink-2">
            <b className="text-ink">Demo mode.</b> Upload the demo learner&apos;s resume through the same pipeline. Nothing is pre-filled: the system reads it like any other file.
          </p>
          <Button variant="secondary" onClick={() => void uploadDemoResume()} disabled={busy}>
            Use the demo resume
          </Button>
        </div>
      )}

      {error != null && <ErrorState error={error} title="That file could not be read" onRetry={() => setError(null)} />}

      {docs.length > 0 && (
        <ul className="plate-quiet reg" aria-label="Documents read this session">
          {docs.map((d, i) => (
            <li key={i} className="flex flex-wrap items-center justify-between gap-2 p-3 text-[0.875rem]">
              <span className="break-all font-semibold">{d.name}</span>
              <span className="text-ink-2">
                {d.result.claims_summary.pending} skill {d.result.claims_summary.pending === 1 ? "claim" : "claims"} found
                {d.result.claims_summary.dropped_injection > 0 && `, ${d.result.claims_summary.dropped_injection} ignored as instructions`}
              </span>
            </li>
          ))}
        </ul>
      )}
      {docs.some((d) => d.result.claims_summary.degraded) && (
        <DegradedNotice>The catalog-matching extractor read your document. It finds skills the curated graph already names, and quotes the exact words.</DegradedNotice>
      )}
      {run && <AgentTrace run={run} compact />}
    </div>
  );
}

/**
 * ClaimReview: the human checkpoint. Every skill claim extracted from a
 * document is shown with the exact words it came from and its evidence tier;
 * the learner confirms, removes or remaps it before it counts as evidence.
 */
export function ClaimReview({
  claims,
  onDone,
  className,
}: {
  claims: PendingClaim[];
  onDone: (summary: { confirmed: number; removed: number }) => void;
  className?: string;
}) {
  const { byId } = useSkillIndex();
  const skills = useMemo(() => Object.values(byId).sort((a, b) => a.label.localeCompare(b.label)), [byId]);
  const listId = useId();
  const [choice, setChoice] = useState<Record<string, "confirm" | "remove">>(() =>
    Object.fromEntries(claims.map((c) => [c.claim_id, c.normalized_skill_id ? "confirm" : "remove"])),
  );
  const [override, setOverride] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);

  const overrideId = (text: string) => skills.find((s) => s.label.toLowerCase() === text.trim().toLowerCase())?.skill_id;

  async function save() {
    setBusy(true);
    setError(null);
    const decisions: ClaimDecision[] = claims.map((c) => {
      const o = override[c.claim_id];
      const oid = o ? overrideId(o) : undefined;
      if (choice[c.claim_id] === "remove") return { claim_id: c.claim_id, action: "remove" };
      if (oid && oid !== c.normalized_skill_id) return { claim_id: c.claim_id, action: "edit", skill_id_override: oid };
      return { claim_id: c.claim_id, action: "confirm" };
    });
    try {
      const summary = await traced("Confirming your evidence", (id) => api.confirmClaims(decisions, id));
      invalidate();
      onDone({ confirmed: summary.confirmed, removed: summary.removed });
    } catch (e) {
      setError(e);
      setBusy(false);
    }
  }

  const confirmCount = claims.filter((c) => choice[c.claim_id] === "confirm").length;

  return (
    <div className={cn("space-y-4", className)}>
      <datalist id={listId}>
        {skills.map((s) => (
          <option key={s.skill_id} value={s.label} />
        ))}
      </datalist>
      <ul className="plate divide-y divide-rule-strong">
        {claims.map((c) => {
          const mapped = c.normalized_skill_id ? byId[c.normalized_skill_id]?.label : undefined;
          const removed = choice[c.claim_id] === "remove";
          return (
            <li key={c.claim_id} className={cn("space-y-3 p-4", removed && "bg-plate/60")}>
              <div className="flex flex-wrap items-start justify-between gap-3">
                <div className="min-w-0 space-y-1">
                  <p className={cn("text-[1.0625rem] font-bold leading-snug", removed && "struck text-ink-2")}>
                    {c.skill_label}
                    {mapped && mapped.toLowerCase() !== c.skill_label.toLowerCase() && <span className="font-normal text-ink-2"> maps to {mapped}</span>}
                  </p>
                  <p className="text-[0.8125rem] text-ink-2">
                    {c.normalized_skill_id
                      ? `Matched to the skill graph by ${c.normalization_method.replace(/_/g, " ")} (${Math.round(c.normalization_confidence * 100)}% sure).`
                      : "Not matched to a curated skill. Leave it out, or choose the skill it means."}
                  </p>
                </div>
                <TierBadge tier={c.tier} />
              </div>
              <blockquote className="max-w-[68ch] border-l border-rule-strong pl-3 text-[0.9375rem] leading-relaxed">&ldquo;{c.verbatim_span}&rdquo;</blockquote>
              <p className="text-[0.8125rem] text-ink-2">
                From your document, characters {c.span_offsets.start}&ndash;{c.span_offsets.end}
                {c.claimed_level_cue ? `. You wrote "${c.claimed_level_cue}".` : "."}
              </p>
              <div className="flex flex-wrap items-center gap-2">
                <div role="group" aria-label={`Decision for ${c.skill_label}`} className="inline-flex">
                  <button
                    type="button"
                    aria-pressed={!removed}
                    onClick={() => setChoice((s) => ({ ...s, [c.claim_id]: "confirm" }))}
                    className={cn("inline-flex min-h-11 cursor-pointer items-center gap-1.5 border px-3 text-[0.875rem] font-semibold md:min-h-9", !removed ? "border-ink bg-ink text-paper" : "border-rule-strong bg-paper hover:bg-plate")}
                  >
                    <Check className="size-4" aria-hidden /> Keep
                  </button>
                  <button
                    type="button"
                    aria-pressed={removed}
                    onClick={() => setChoice((s) => ({ ...s, [c.claim_id]: "remove" }))}
                    className={cn("-ml-px inline-flex min-h-11 cursor-pointer items-center gap-1.5 border px-3 text-[0.875rem] font-semibold md:min-h-9", removed ? "border-ink bg-ink text-paper" : "border-rule-strong bg-paper hover:bg-plate")}
                  >
                    <Trash2 className="size-4" aria-hidden /> Leave out
                  </button>
                </div>
                {!removed && (
                  <label className="flex min-w-[14rem] flex-1 items-center gap-2 text-[0.8125rem] text-ink-2">
                    <span className="shrink-0">Means</span>
                    <input
                      list={listId}
                      placeholder={mapped ?? "Choose a skill"}
                      value={override[c.claim_id] ?? ""}
                      onChange={(e) => setOverride((s) => ({ ...s, [c.claim_id]: e.target.value }))}
                      className="min-h-11 w-full border border-rule-strong bg-paper px-2 text-[0.875rem] text-ink placeholder:text-ink-3 md:min-h-9"
                    />
                  </label>
                )}
              </div>
            </li>
          );
        })}
      </ul>
      {error != null && <ErrorState error={error} onRetry={() => setError(null)} />}
      <div className="flex flex-wrap items-center gap-3">
        <Button size="lg" onClick={save} disabled={busy} aria-busy={busy}>
          {busy ? "Saving" : `Confirm ${confirmCount} ${confirmCount === 1 ? "claim" : "claims"}`}
        </Button>
        <p className="text-[0.8125rem] text-ink-2">Only what you confirm becomes evidence. Nothing here counts until you do.</p>
      </div>
    </div>
  );
}
