"use client";

import { ArrowLeft, ArrowRight, Check } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useId, useMemo, useState } from "react";
import { AgentTrace } from "@/components/edupath/agent-trace";
import { ClaimReview, EvidenceUploader } from "@/components/edupath/evidence-flow";
import { EmptyState, ErrorState, LoadingState } from "@/components/edupath/states";
import { Wordmark } from "@/components/edupath/wordmark";
import { Button } from "@/components/ui/button";
import { DEMO_MODE, api } from "@/lib/api-client";
import { useProfile, useRoles } from "@/lib/hooks";
import { invalidate, resetQueries, useQuery } from "@/lib/query";
import { traced, useTraceRuns } from "@/lib/trace-store";
import type { IntakeRequest } from "@/lib/types";
import { cn } from "@/lib/utils";

type Step = "goal" | "evidence" | "review" | "plan";
const STEPS: Array<[Step, string]> = [
  ["goal", "Your goal"],
  ["evidence", "Your evidence"],
  ["review", "Check it"],
  ["plan", "Your first week"],
];

const MODALITY: Array<[string, IntakeRequest["preferences"]["modality_order"], string]> = [
  ["do", ["do", "read", "watch"], "Doing: projects and exercises first"],
  ["read", ["read", "do", "watch"], "Reading: articles and docs first"],
  ["watch", ["watch", "do", "read"], "Watching: video first"],
];

function Field({ label, hint, children, htmlFor }: { label: string; hint?: string; children: React.ReactNode; htmlFor?: string }) {
  return (
    <div className="space-y-1.5">
      <label htmlFor={htmlFor} className="block text-[0.9375rem] font-bold">
        {label}
      </label>
      {hint && <p className="text-[0.8125rem] text-ink-2">{hint}</p>}
      {children}
    </div>
  );
}

const inputCls = "min-h-11 w-full border border-rule-strong bg-paper px-3 text-[0.9375rem] placeholder:text-ink-3 md:min-h-10";

export default function StartPage() {
  const router = useRouter();
  const [step, setStep] = useState<Step>("goal");
  const { data: roles, status: rolesStatus, error: rolesError, reload: reloadRoles } = useRoles();
  const { data: profile } = useProfile();
  const uid = useId();

  const [roleId, setRoleId] = useState("");
  const [hours, setHours] = useState(5);
  const [modality, setModality] = useState("do");
  const [session, setSession] = useState(45);
  const [goal, setGoal] = useState("");
  const [summary, setSummary] = useState("");
  const [skills, setSkills] = useState("");
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState<unknown>(null);
  const [prefilled, setPrefilled] = useState(false);

  // Returning learners see their saved answers (derived once, during render).
  if (profile && !prefilled) {
    setPrefilled(true);
    setRoleId(profile.target_role_id);
    setHours(profile.weekly_hours);
    setGoal(profile.career_goal);
    setSummary(profile.experience_summary);
    const first = profile.preferences?.modality_order?.[0];
    if (first) setModality(first);
    if (profile.preferences?.session_length_min) setSession(profile.preferences.session_length_min);
  }

  async function loadDemo() {
    const res = await fetch("/demo/asha.json");
    const d = await res.json();
    setRoleId(d.target_role_id);
    setHours(d.weekly_hours);
    setGoal(d.career_goal);
    setSummary(d.experience_summary);
    setSkills(d.current_skills.join(", "));
    setModality(d.preferences.modality_order[0]);
    setSession(d.preferences.session_length_min ?? 45);
  }

  async function saveGoal(e: React.FormEvent) {
    e.preventDefault();
    setSaving(true);
    setSaveError(null);
    const body: IntakeRequest = {
      current_skills: skills.split(",").map((s) => s.trim()).filter(Boolean),
      experience_summary: summary,
      target_role_id: roleId,
      career_goal: goal,
      weekly_hours: hours,
      preferences: { modality_order: MODALITY.find((m) => m[0] === modality)![1], language: "en", session_length_min: session },
    };
    try {
      await api.createProfile(body);
      resetQueries();
      setStep("evidence");
    } catch (err) {
      setSaveError(err);
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="min-h-dvh">
      <header className="border-b border-rule-strong bg-plate">
        <div className="mx-auto flex max-w-[64rem] items-center justify-between px-4 py-3 sm:px-6">
          <Link href="/" aria-label="EduPath home">
            <Wordmark />
          </Link>
          {profile && (
            <Link href="/dashboard" className="text-[0.875rem] font-semibold underline">
              Skip to your dashboard
            </Link>
          )}
        </div>
      </header>

      <main id="main" className="mx-auto max-w-[64rem] px-4 py-8 sm:px-6 sm:py-10">
        <ol className="mb-8 grid grid-cols-4 gap-px border border-rule-strong bg-rule-strong" aria-label="Setup steps">
          {STEPS.map(([id, label], i) => {
            const idx = STEPS.findIndex(([s]) => s === step);
            const done = i < idx;
            const current = i === idx;
            return (
              <li key={id} aria-current={current ? "step" : undefined} className={cn("flex min-h-14 items-center gap-2.5 px-3 py-2", current ? "bg-paper" : "bg-plate")}>
                <span className={cn("draft grid size-6 shrink-0 place-items-center border text-[0.8125rem] font-semibold", done ? "border-ink bg-ink text-paper" : current ? "border-ink" : "border-rule-strong text-ink-3")}>
                  {done ? <Check className="size-3.5" strokeWidth={3} /> : i + 1}
                </span>
                <span className={cn("hidden text-[0.875rem] sm:block", current ? "font-bold" : done ? "font-semibold" : "text-ink-3")}>{label}</span>
                <span className="sr-only sm:hidden">{label}</span>
              </li>
            );
          })}
        </ol>

        {step === "goal" && (
          <form onSubmit={saveGoal} className="space-y-8">
            <div className="max-w-[58ch] space-y-2">
              <h1 className="text-[2rem] font-bold sm:text-[2.5rem]">Where do you want to get to?</h1>
              <p className="text-[1rem] text-ink-2">Pick a target role and tell us how much time you have. EduPath plans around both.</p>
            </div>

            {DEMO_MODE && (
              <div className="flex flex-wrap items-center gap-3 border border-dashed border-ink-3 bg-paper px-4 py-3">
                <p className="min-w-[14rem] flex-1 text-[0.875rem] text-ink-2">
                  <b className="text-ink">Demo mode.</b> Fill this form with the demo learner, Asha, a third-year AI/ML student.
                </p>
                <Button type="button" variant="secondary" onClick={() => void loadDemo()}>
                  Fill in for Asha
                </Button>
              </div>
            )}

            <fieldset className="space-y-3">
              <legend className="text-[1.0625rem] font-bold">Target role</legend>
              {rolesStatus === "loading" && <LoadingState variant="register" rows={3} label="Loading roles" />}
              {rolesStatus === "error" && <ErrorState error={rolesError} onRetry={reloadRoles} />}
              {roles && roles.length === 0 && (
                <EmptyState title="No roles are curated yet">EduPath only plans for roles whose skills and prerequisites have been curated. Seed the catalog, then reload.</EmptyState>
              )}
              {roles && roles.length > 0 && (
                <div className="plate divide-y divide-rule-strong">
                  {roles.map((r) => (
                    <label key={r.role_id} className={cn("flex min-h-14 cursor-pointer items-start gap-3 p-4 transition-colors duration-150", roleId === r.role_id ? "bg-plate" : "hover:bg-plate/50")}>
                      <input type="radio" name={`${uid}-role`} value={r.role_id} checked={roleId === r.role_id} onChange={() => setRoleId(r.role_id)} required className="peer sr-only" />
                      <span aria-hidden className={cn("mt-1 grid size-5 shrink-0 place-items-center rounded-full border-[1.5px] border-ink peer-focus-visible:outline peer-focus-visible:outline-2 peer-focus-visible:outline-offset-2 peer-focus-visible:outline-ink")}>
                        {roleId === r.role_id && <span className="size-2.5 rounded-full bg-ink" />}
                      </span>
                      <span className="min-w-0 space-y-0.5">
                        <span className="block text-[1.0625rem] font-bold">{r.title}</span>
                        <span className="block max-w-[64ch] text-[0.875rem] text-ink-2">{r.description}</span>
                        <span className="block text-[0.8125rem] text-ink-3">{r.required_skill_count} required skills</span>
                      </span>
                    </label>
                  ))}
                </div>
              )}
            </fieldset>

            <div className="grid gap-6 sm:grid-cols-2">
              <Field label="Hours a week" htmlFor={`${uid}-h`} hint="What you can honestly give. The plan never goes over it.">
                <input id={`${uid}-h`} type="number" min={1} max={40} step={0.5} value={hours} onChange={(e) => setHours(Number(e.target.value))} required className={inputCls} />
              </Field>
              <Field label="Longest single session" htmlFor={`${uid}-s`}>
                <select id={`${uid}-s`} value={session} onChange={(e) => setSession(Number(e.target.value))} className={inputCls}>
                  {[20, 30, 45, 60, 90].map((m) => (
                    <option key={m} value={m}>
                      {m} minutes
                    </option>
                  ))}
                </select>
              </Field>
            </div>

            <fieldset className="space-y-2">
              <legend className="text-[0.9375rem] font-bold">How do you like to learn?</legend>
              <div className="grid gap-2 sm:grid-cols-3">
                {MODALITY.map(([id, , label]) => (
                  <label key={id} className={cn("flex min-h-11 cursor-pointer items-center gap-2 border px-3 py-2 text-[0.875rem]", modality === id ? "border-ink bg-plate font-bold" : "border-rule-strong bg-paper hover:bg-plate/60")}>
                    <input type="radio" name={`${uid}-m`} value={id} checked={modality === id} onChange={() => setModality(id)} className="peer sr-only" />
                    <span aria-hidden className="grid size-4 shrink-0 place-items-center rounded-full border-[1.5px] border-ink peer-focus-visible:outline peer-focus-visible:outline-2 peer-focus-visible:outline-offset-2 peer-focus-visible:outline-ink">
                      {modality === id && <span className="size-2 rounded-full bg-ink" />}
                    </span>
                    {label}
                  </label>
                ))}
              </div>
            </fieldset>

            <Field label="Your goal, in a sentence" htmlFor={`${uid}-g`} hint="Optional.">
              <textarea id={`${uid}-g`} rows={2} value={goal} onChange={(e) => setGoal(e.target.value)} className={cn(inputCls, "py-2")} />
            </Field>
            <Field label="Skills you already have" htmlFor={`${uid}-k`} hint="Separate with commas. These count as self-reported only, and are never enough on their own to meet a requirement.">
              <input id={`${uid}-k`} value={skills} onChange={(e) => setSkills(e.target.value)} placeholder="Python, SQL, Git" className={inputCls} />
            </Field>

            {saveError != null && <ErrorState error={saveError} onRetry={() => setSaveError(null)} />}
            <Button size="lg" type="submit" disabled={!roleId || saving} aria-busy={saving}>
              {saving ? "Saving" : "Continue to evidence"} <ArrowRight />
            </Button>
          </form>
        )}

        {step === "evidence" && <EvidenceStep onBack={() => setStep("goal")} onNext={() => setStep("review")} />}
        {step === "review" && <ReviewStep onBack={() => setStep("evidence")} onNext={() => setStep("plan")} />}
        {step === "plan" && <PlanStep onBack={() => setStep("review")} onDone={() => router.push("/dashboard")} />}
      </main>
    </div>
  );
}

function EvidenceStep({ onBack, onNext }: { onBack: () => void; onNext: () => void }) {
  const [uploaded, setUploaded] = useState(0);
  return (
    <div className="space-y-6">
      <div className="max-w-[60ch] space-y-2">
        <h1 className="text-[2rem] font-bold sm:text-[2.5rem]">Show us what you&apos;ve done.</h1>
        <p className="text-[1rem] text-ink-2">
          Add a resume, notes or a repository. EduPath finds the skills in it and keeps the exact words as your evidence. You can also skip this and add evidence later.
        </p>
      </div>
      <EvidenceUploader onUploaded={() => setUploaded((n) => n + 1)} />
      <div className="flex flex-wrap items-center gap-3">
        <Button variant="ghost" onClick={onBack}>
          <ArrowLeft /> Back
        </Button>
        <Button size="lg" onClick={onNext}>
          {uploaded > 0 ? "Review what was found" : "Skip for now"} <ArrowRight />
        </Button>
      </div>
    </div>
  );
}

function ReviewStep({ onBack, onNext }: { onBack: () => void; onNext: () => void }) {
  const { data, status, error, reload } = useQuery("pending", api.pendingClaims);
  const [done, setDone] = useState<{ confirmed: number; removed: number } | null>(null);

  useEffect(() => {
    if (status === "ready" && data && data.length === 0 && !done) onNext();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [status, data]);

  if (status === "loading") return <LoadingState label="Loading claims" rows={4} />;
  if (status === "error") return <ErrorState error={error} onRetry={reload} />;

  return (
    <div className="space-y-6">
      <div className="max-w-[60ch] space-y-2">
        <h1 className="text-[2rem] font-bold sm:text-[2.5rem]">Is this what you meant?</h1>
        <p className="text-[1rem] text-ink-2">
          Each claim below is a skill EduPath found, with the exact words it came from and how strong that evidence is. Keep what is true, leave out what isn&apos;t.
        </p>
      </div>
      {data && data.length > 0 && !done && (
        <ClaimReview
          claims={data}
          onDone={(s) => {
            setDone(s);
            invalidate("pending");
            onNext();
          }}
        />
      )}
      <Button variant="ghost" onClick={onBack}>
        <ArrowLeft /> Back
      </Button>
    </div>
  );
}

function PlanStep({ onBack, onDone }: { onBack: () => void; onDone: () => void }) {
  const [state, setState] = useState<"idle" | "running" | "done" | "error">("idle");
  const [error, setError] = useState<unknown>(null);
  const [runId, setRunId] = useState<string>();
  const runs = useTraceRuns();
  const run = useMemo(() => runs.find((r) => r.runId === runId), [runs, runId]);

  async function build() {
    setState("running");
    setError(null);
    try {
      await traced("Building your first week", (id) => {
        setRunId(id);
        return api.createPlan({ week_index: 0 }, id);
      });
      invalidate();
      setState("done");
    } catch (e) {
      setError(e);
      setState("error");
    }
  }

  return (
    <div className="space-y-6">
      <div className="max-w-[60ch] space-y-2">
        <h1 className="text-[2rem] font-bold sm:text-[2.5rem]">Build your first week.</h1>
        <p className="text-[1rem] text-ink-2">
          EduPath compares your evidence with the role, finds what is missing, and schedules it inside your hours. Watch each step as it runs.
        </p>
      </div>
      {state === "idle" && (
        <div className="flex flex-wrap gap-3">
          <Button variant="ghost" onClick={onBack}>
            <ArrowLeft /> Back
          </Button>
          <Button size="lg" onClick={build}>
            Build my plan <ArrowRight />
          </Button>
        </div>
      )}
      {state === "error" && <ErrorState error={error} onRetry={build} title="The plan could not be built" />}
      {run && <AgentTrace run={run} />}
      {state === "done" && (
        <Button size="lg" onClick={onDone}>
          Open my dashboard <ArrowRight />
        </Button>
      )}
    </div>
  );
}
