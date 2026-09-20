"use client";

import { Send } from "lucide-react";
import { useSearchParams } from "next/navigation";
import { Suspense, useEffect, useRef, useState } from "react";
import { useLearner } from "@/components/edupath/learner-context";
import { SheetHeader } from "@/components/edupath/sheet-header";
import { LoadingState } from "@/components/edupath/states";
import { TutorMessage, type TutorTurn } from "@/components/edupath/tutor";
import { DegradedNotice } from "@/components/edupath/states";
import { Button } from "@/components/ui/button";
import { api } from "@/lib/api-client";
import { traced } from "@/lib/trace-store";

function TutorInner() {
  const params = useSearchParams();
  const { labelFor } = useLearner();
  const skillHint = params.get("skill") ?? undefined;
  const decisionHint = params.get("decision") ?? undefined;
  const [turns, setTurns] = useState<TutorTurn[]>([]);
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const endRef = useRef<HTMLDivElement>(null);
  const anyDegraded = turns.some((t) => t.conservative || t.degraded);

  const suggestions = [
    decisionHint ? "Why did my plan change?" : "Why is my plan this way?",
    "What should I work on next?",
    "How am I doing overall?",
    ...(skillHint ? [`Why does ${labelFor(skillHint)} matter for my role?`] : []),
  ];

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [turns]);

  async function ask(message: string) {
    const q = message.trim();
    if (!q || busy) return;
    const id = crypto.randomUUID();
    setTurns((t) => [...t, { id: `${id}-q`, role: "learner", text: q }, { id: `${id}-a`, role: "tutor", text: "", pending: true }]);
    setText("");
    setBusy(true);
    try {
      const res = await traced(`Tutor: ${q.length > 40 ? `${q.slice(0, 40)}…` : q}`, (runId) =>
        api.chat(q, { skill_id_hint: skillHint, decision_id_hint: decisionHint }, runId),
      );
      setTurns((t) => t.map((x) => (x.id === `${id}-a` ? { ...x, pending: false, text: res.answer, citations: res.citations, conservative: res.conservative, degraded: res.degraded } : x)));
    } catch (e) {
      setTurns((t) => t.map((x) => (x.id === `${id}-a` ? { ...x, pending: false, error: e instanceof Error ? e.message : "The tutor could not answer." } : x)));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="space-y-6">
      <SheetHeader title="Tutor" description="Ask about your plan, your skills or your progress. Answers come only from your own records, and cite them. The tutor cannot change your plan." />

      <div className="plate flex min-h-[26rem] flex-col">
        <div className="flex-1 space-y-4 p-4 sm:p-5" aria-live="polite" aria-label="Conversation">
          {turns.length === 0 ? (
            <div className="space-y-3">
              <p className="max-w-[54ch] text-[0.9375rem] text-ink-2">Try one of these, or ask your own question.</p>
              <ul className="flex flex-wrap gap-2">
                {suggestions.map((s) => (
                  <li key={s}>
                    <button type="button" onClick={() => void ask(s)} className="min-h-11 cursor-pointer border border-rule-strong bg-paper px-3 text-left text-[0.9375rem] font-semibold hover:bg-plate md:min-h-9">
                      {s}
                    </button>
                  </li>
                ))}
              </ul>
            </div>
          ) : (
            turns.map((t) => <TutorMessage key={t.id} turn={t} labelFor={labelFor} />)
          )}
          <div ref={endRef} />
        </div>
        <form
          onSubmit={(e) => {
            e.preventDefault();
            void ask(text);
          }}
          className="flex items-end gap-2 border-t border-rule-strong bg-plate/60 p-3"
        >
          <label htmlFor="tutor-q" className="sr-only">
            Ask the tutor
          </label>
          <textarea
            id="tutor-q"
            rows={1}
            value={text}
            onChange={(e) => setText(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault();
                void ask(text);
              }
            }}
            placeholder="Ask about your plan or a skill"
            className="max-h-32 min-h-11 flex-1 resize-none border border-rule-strong bg-paper px-3 py-2.5 text-[0.9375rem] placeholder:text-ink-3 md:min-h-10"
          />
          <Button type="submit" disabled={busy || !text.trim()} aria-busy={busy}>
            <Send /> Ask
          </Button>
        </form>
      </div>
      {anyDegraded && <DegradedNotice>Answers were assembled directly from your records, with the model wording step skipped. Every citation is still checked.</DegradedNotice>}
    </div>
  );
}

export default function TutorPage() {
  return (
    <Suspense fallback={<LoadingState variant="plate" label="Loading tutor" />}>
      <TutorInner />
    </Suspense>
  );
}
