"use client";

import { Check, X } from "lucide-react";
import { cn } from "@/lib/utils";
import type { AssessmentItemResult, AssessmentResult as AssessmentResultT, PracticeItem } from "@/lib/types";

const LETTERS = ["A", "B", "C", "D", "E", "F"];

/**
 * PracticeCard: one question. A native radio group, so it works with the
 * keyboard and screen readers (arrow keys move, space selects). After
 * grading only correct/incorrect is shown: the backend never returns the
 * answer key.
 */
export function PracticeCard({
  item,
  index,
  total,
  value,
  onChange,
  disabled,
  outcome,
}: {
  item: PracticeItem;
  index: number;
  total: number;
  value: number | null;
  onChange: (option: number) => void;
  disabled?: boolean;
  outcome?: AssessmentItemResult;
}) {
  return (
    <fieldset className="plate-quiet p-4 sm:p-5" disabled={disabled}>
      <legend className="sr-only">
        Question {index + 1} of {total}
      </legend>
      <div className="mb-3 flex items-baseline justify-between gap-3">
        <p className="draft text-[0.9375rem] font-semibold text-ink-2">
          Question {index + 1} of {total}
        </p>
        <span className="border border-rule-strong px-1.5 py-px text-[0.75rem] font-semibold capitalize text-ink-2">{item.difficulty}</span>
      </div>
      <p className="mb-4 max-w-[64ch] text-[1.0625rem] font-semibold leading-snug">{item.stem}</p>
      <div className="space-y-2">
        {item.options.map((opt, i) => {
          const chosen = value === i;
          const graded = outcome && outcome.chosen_option === i;
          return (
            <label
              key={i}
              className={cn(
                "flex min-h-11 cursor-pointer items-start gap-3 border px-3 py-2.5 text-[0.9375rem] leading-snug transition-colors duration-150",
                chosen ? "border-ink bg-plate" : "border-rule-strong bg-paper hover:bg-plate/60",
                graded && (outcome!.correct ? "border-verified bg-verified-wash" : "border-revision bg-revision-wash/60"),
                disabled && "cursor-default",
              )}
            >
              <input
                type="radio"
                name={`q-${item.item_id}`}
                checked={chosen}
                onChange={() => onChange(i)}
                className="peer sr-only"
              />
              <span
                aria-hidden
                className={cn(
                  "draft mt-px grid size-6 shrink-0 place-items-center border text-[0.8125rem] font-semibold peer-focus-visible:outline peer-focus-visible:outline-2 peer-focus-visible:outline-offset-2 peer-focus-visible:outline-ink",
                  chosen ? "border-ink bg-ink text-paper" : "border-rule-strong",
                )}
              >
                {LETTERS[i]}
              </span>
              <span className="flex-1">{opt}</span>
              {graded && (
                <span className={cn("inline-flex shrink-0 items-center gap-1 text-[0.8125rem] font-bold", outcome!.correct ? "text-verified" : "text-revision")}>
                  {outcome!.correct ? <Check className="size-4" aria-hidden /> : <X className="size-4" aria-hidden />}
                  {outcome!.correct ? "Correct" : "Not quite"}
                </span>
              )}
            </label>
          );
        })}
      </div>
    </fieldset>
  );
}

/**
 * AssessmentResult: what happened in the set, stated as a sentence and a
 * register, with the honest caveat that one set never decides mastery.
 */
export function AssessmentResult({ result, labelFor }: { result: AssessmentResultT; labelFor: (id: string) => string }) {
  const correct = result.items.filter((i) => i.correct).length;
  const total = result.items.length;
  return (
    <section aria-labelledby="result-title" className="plate p-4 sm:p-5">
      <h2 id="result-title" className="text-xl font-bold">
        {correct} of {total} correct on {labelFor(result.skill_id)}
      </h2>
      <p className="mt-1 max-w-[62ch] text-[0.9375rem] text-ink-2">
        Your mastery estimate for this skill moved with each answer, weighted by difficulty. One set never decides it: EduPath treats mastery as an estimate with a confidence, not a verdict.
      </p>
      <ul className="mt-4 flex gap-1.5" aria-label="Answers in order">
        {result.items.map((i, n) => (
          <li
            key={i.item_id}
            className={cn("grid size-8 place-items-center border text-[0.8125rem] font-semibold", i.correct ? "border-verified bg-verified-wash text-verified" : "border-revision bg-revision-wash text-revision")}
            aria-label={`Question ${n + 1}: ${i.correct ? "correct" : "incorrect"}`}
          >
            {i.correct ? <Check className="size-4" aria-hidden /> : <X className="size-4" aria-hidden />}
          </li>
        ))}
      </ul>
    </section>
  );
}
