"use client";

import { ArrowRight, Play } from "lucide-react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useState } from "react";
import { AgentTrace } from "@/components/edupath/agent-trace";
import { StruggleSignalCard } from "@/components/edupath/cards";
import { useLearner } from "@/components/edupath/learner-context";
import { AssessmentResult, PracticeCard } from "@/components/edupath/practice";
import { SheetHeader } from "@/components/edupath/sheet-header";
import { EmptyState, ErrorState, LoadingState } from "@/components/edupath/states";
import { SkillGlyph } from "@/components/edupath/skill-status";
import { Button } from "@/components/ui/button";
import { DEMO_MODE, api } from "@/lib/api-client";
import { dedupeSignals, gapState } from "@/lib/format";
import { useGaps, usePlan } from "@/lib/hooks";
import { invalidate } from "@/lib/query";
import { traced, useTraceRuns } from "@/lib/trace-store";
import type { PracticeSet, SubmitPracticeResponse } from "@/lib/types";

const PURPOSE_COPY: Record<string, { title: string; body: string }> = {
  practice: { title: "Practice", body: "A short set at your current level. Your mastery estimate updates with each answer." },
  probe: { title: "Verify first", body: "You listed this skill, but nothing proves it yet. A short probe checks it before any lesson." },
  "resolution-check": { title: "Check the fix", body: "A follow-up to see whether the refresher cleared up the misconception." },
  "prereq-block": { title: "Prerequisite check", body: "A mixed set that checks this skill's prerequisites too." },
};

function Chooser() {
  const router = useRouter();
  const { labelFor } = useLearner();
  const gaps = useGaps();
  const plan = usePlan();
  const planned = (plan.data?.items ?? []).filter((i) => (i.type === "probe" || i.type === "practice") && i.status === "planned");
  const suggestions = (gaps.data?.gaps ?? []).filter((g) => g.status !== "MET" && g.status !== "BLOCKED").sort((a, b) => b.priority - a.priority).slice(0, 8);

  return (
    <div className="space-y-6">
      {planned.length > 0 && (
        <section aria-labelledby="pr-plan" className="space-y-2">
          <h2 id="pr-plan" className="text-xl font-bold">In your plan</h2>
          <ul className="plate reg">
            {planned.map((i) => (
              <li key={i.item_id}>
                <button
                  type="button"
                  onClick={() => router.push(`/dashboard/practice?skill=${encodeURIComponent(i.skill_id)}&purpose=${i.type === "probe" ? (/resolution-check/i.test(i.reason?.text ?? "") ? "resolution-check" : "probe") : "practice"}`)}
                  className="flex min-h-14 w-full cursor-pointer items-center justify-between gap-3 px-4 py-3 text-left hover:bg-plate/60"
                >
                  <span className="font-bold">{i.type === "probe" ? "Check" : "Practice"}: {labelFor(i.skill_id)}</span>
                  <ArrowRight className="size-4" aria-hidden />
                </button>
              </li>
            ))}
          </ul>
        </section>
      )}
      <section aria-labelledby="pr-any" className="space-y-2">
        <h2 id="pr-any" className="text-xl font-bold">Or pick a skill</h2>
        {gaps.status === "loading" && <LoadingState rows={4} label="Loading skills" />}
        {gaps.status === "error" && <ErrorState error={gaps.error} onRetry={gaps.reload} />}
        {gaps.data && suggestions.length === 0 && <EmptyState title="Nothing to practise yet">Every skill is either met or blocked behind a prerequisite.</EmptyState>}
        {suggestions.length > 0 && (
          <ul className="plate reg">
            {suggestions.map((g) => (
              <li key={g.skill_id}>
                <button
                  type="button"
                  onClick={() => router.push(`/dashboard/practice?skill=${encodeURIComponent(g.skill_id)}&purpose=${g.status === "UNVERIFIED" ? "probe" : "practice"}`)}
                  className="flex min-h-14 w-full cursor-pointer items-center gap-3 px-4 py-3 text-left hover:bg-plate/60"
                >
                  <SkillGlyph state={gapState(g)} size={18} title="" />
                  <span className="flex-1 font-bold">{g.label}</span>
                  <span className="text-[0.8125rem] text-ink-2">{g.status === "UNVERIFIED" ? "Verify first" : "Practice"}</span>
                </button>
              </li>
            ))}
          </ul>
        )}
      </section>
    </div>
  );
}

function Session({ skillId, purpose }: { skillId: string; purpose: string }) {
  const { labelFor } = useLearner();
  const runs = useTraceRuns();
  const [runId, setRunId] = useState<string>();
  const run = runs.find((r) => r.runId === runId);
  const [set, setSet] = useState<PracticeSet | null>(null);
  const [answers, setAnswers] = useState<Record<string, number>>({});
  const [busy, setBusy] = useState<"idle" | "starting" | "grading">("idle");
  const [error, setError] = useState<unknown>(null);
  const [outcome, setOutcome] = useState<SubmitPracticeResponse | null>(null);
  const copy = PURPOSE_COPY[purpose] ?? PURPOSE_COPY.practice;

  async function start() {
    setBusy("starting");
    setError(null);
    try {
      const s = await traced(`Preparing ${copy.title.toLowerCase()}`, (id) => {
        setRunId(id);
        return api.createPractice(skillId, purpose, id);
      });
      setSet(s);
      setAnswers({});
      setOutcome(null);
    } catch (e) {
      setError(e);
    } finally {
      setBusy("idle");
    }
  }

  async function submit() {
    if (!set) return;
    setBusy("grading");
    setError(null);
    try {
      const res = await traced(`Grading ${labelFor(skillId)}`, (id) => {
        setRunId(id);
        return api.submitPractice(set.set_id, { answers: set.items.map((i) => ({ item_id: i.item_id, chosen_option: answers[i.item_id] })) }, id);
      });
      setOutcome(res);
      invalidate();
    } catch (e) {
      setError(e);
    } finally {
      setBusy("idle");
    }
  }

  async function fillStruggle() {
    if (!set) return;
    const res = await fetch("/demo/struggle-answers.json");
    const { answers: map } = (await res.json()) as { answers: Record<string, number> };
    setAnswers(Object.fromEntries(set.items.map((i) => [i.item_id, map[i.item_id] ?? 0])));
  }

  const complete = set ? set.items.every((i) => answers[i.item_id] !== undefined) : false;
  const outcomeByItem = Object.fromEntries((outcome?.result.items ?? []).map((i) => [i.item_id, i]));

  return (
    <div className="space-y-6">
      <div className="plate p-4 sm:p-5">
        <h2 className="text-xl font-bold">
          {copy.title}: {labelFor(skillId)}
        </h2>
        <p className="mt-1 max-w-[62ch] text-[0.9375rem] text-ink-2">{copy.body}</p>
        {!set && (
          <div className="mt-4 flex flex-wrap gap-3">
            <Button size="lg" onClick={start} disabled={busy !== "idle"} aria-busy={busy === "starting"}>
              <Play /> {busy === "starting" ? "Preparing" : "Start"}
            </Button>
            <Link href="/dashboard/practice" className="inline-flex min-h-12 items-center px-3 text-[0.9375rem] font-semibold underline">
              Choose another skill
            </Link>
          </div>
        )}
      </div>

      {error != null && <ErrorState error={error} onRetry={() => setError(null)} title={busy === "grading" ? "Your answers could not be graded" : "Practice could not start"} />}
      {set && set.items.length === 0 && (
        <EmptyState title="No questions for this skill yet">The item bank has nothing vetted for this skill. EduPath will not make up questions it cannot check.</EmptyState>
      )}

      {set && set.items.length > 0 && (
        <div className="space-y-4">
          {set.items.map((item, i) => (
            <PracticeCard
              key={item.item_id}
              item={item}
              index={i}
              total={set.items.length}
              value={answers[item.item_id] ?? null}
              onChange={(o) => setAnswers((a) => ({ ...a, [item.item_id]: o }))}
              disabled={!!outcome || busy === "grading"}
              outcome={outcomeByItem[item.item_id]}
            />
          ))}
          {!outcome && (
            <div className="flex flex-wrap items-center gap-3">
              <Button size="lg" onClick={submit} disabled={!complete || busy === "grading"} aria-busy={busy === "grading"}>
                {busy === "grading" ? "Grading" : "Submit answers"}
              </Button>
              {!complete && <p className="text-[0.8125rem] text-ink-2">{set.items.filter((i) => answers[i.item_id] === undefined).length} left to answer.</p>}
              {DEMO_MODE && (
                <Button variant="secondary" onClick={() => void fillStruggle()} disabled={busy === "grading"}>
                  Demo: answer with a common misconception
                </Button>
              )}
            </div>
          )}
        </div>
      )}

      {outcome && (
        <div className="space-y-4">
          <AssessmentResult result={outcome.result} labelFor={labelFor} />
          {outcome.signals.length > 0 && (
            <section aria-labelledby="sig" className="space-y-2">
              <h2 id="sig" className="text-xl font-bold">What EduPath noticed</h2>
              {dedupeSignals(outcome.signals).map((s) => (
                <StruggleSignalCard key={s.signal_id} signal={s} labelFor={labelFor} />
              ))}
            </section>
          )}
          {outcome.reflection ? (
            <section aria-labelledby="refl" className="border border-revision bg-paper p-4 sm:p-5">
              <h2 id="refl" className="text-xl font-bold">Your plan changed</h2>
              <p className="mt-1 max-w-[64ch] text-[1rem] leading-relaxed">
                {outcome.reflection.root_cause_skill_id
                  ? `The trouble traces back to ${labelFor(outcome.reflection.root_cause_skill_id)}. EduPath added a refresher and a follow-up check before you return to ${labelFor(skillId)}.`
                  : outcome.reflection.explanation}
              </p>
              {outcome.reflection.needs_attention && <p className="mt-2 text-[0.875rem] font-semibold text-revision">The automatic fix could not satisfy the plan rules, so your plan was left unchanged.</p>}
              <div className="mt-4 flex flex-wrap gap-3">
                <Link href="/dashboard/plan#moment" className="inline-flex min-h-11 items-center gap-2 bg-ink px-4 text-[0.9375rem] font-semibold text-paper hover:bg-ink-2">
                  See what changed and why <ArrowRight className="size-4" aria-hidden />
                </Link>
                <Button variant="outline" onClick={() => { setSet(null); setOutcome(null); setAnswers({}); }}>
                  Practice again
                </Button>
              </div>
            </section>
          ) : (
            <div className="flex flex-wrap gap-3">
              <Link href="/dashboard/plan" className="inline-flex min-h-11 items-center gap-2 bg-ink px-4 text-[0.9375rem] font-semibold text-paper hover:bg-ink-2">
                Back to your plan <ArrowRight className="size-4" aria-hidden />
              </Link>
              <Button variant="outline" onClick={() => { setSet(null); setOutcome(null); setAnswers({}); }}>
                Practice again
              </Button>
            </div>
          )}
        </div>
      )}

      {run && (busy !== "idle" || outcome) && <AgentTrace run={run} compact />}
    </div>
  );
}

function PracticeInner() {
  const params = useSearchParams();
  const skill = params.get("skill");
  const purpose = params.get("purpose") ?? "practice";
  return (
    <div className="space-y-6">
      <SheetHeader title="Practice" description="Short sets that check what you can do. Answers update your mastery estimate and can change your plan." />
      {skill ? <Session key={`${skill}:${purpose}`} skillId={skill} purpose={purpose} /> : <Chooser />}
    </div>
  );
}

export default function PracticePage() {
  return (
    <Suspense fallback={<LoadingState variant="plate" label="Loading practice" />}>
      <PracticeInner />
    </Suspense>
  );
}
