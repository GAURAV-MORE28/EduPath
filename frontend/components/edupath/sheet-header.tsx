"use client";

import { revisionLetter } from "@/lib/derived";
import { usePlan } from "@/lib/hooks";
import { cn } from "@/lib/utils";
import { useLearner } from "./learner-context";
import { RevisionMark } from "./plan";

/**
 * SheetHeader: the title block that opens every sheet. Title and one-line
 * purpose on the left; role, week and revision registers on the right; an
 * optional single next-action strip beneath. Values come from the learner's
 * real plan, not from copy.
 */
export function SheetHeader({
  title,
  description,
  action,
  next,
  className,
}: {
  title: string;
  description?: React.ReactNode;
  /** Buttons that act on this sheet (right of the title on wide screens). */
  action?: React.ReactNode;
  /** The one imperative for this sheet: a ruled strip at the bottom of the block. */
  next?: React.ReactNode;
  className?: string;
}) {
  const { role, profile } = useLearner();
  const { data: plan } = usePlan();
  const cells: Array<[string, string]> = [
    ["Role", role?.title ?? "Your target role"],
    ["Week", plan ? String(plan.week_index + 1) : "-"],
    ["Revision", plan ? revisionLetter(plan.revision_no) : "-"],
    ["Hours", `${profile.weekly_hours} a week`],
  ];
  return (
    <header className={cn("plate", className)}>
      <div className="grid md:grid-cols-[minmax(0,1fr)_auto]">
        <div className="flex flex-wrap items-start justify-between gap-3 p-4 sm:p-5">
          <div className="min-w-0 max-w-[62ch] space-y-1.5">
            <h1 className="text-[1.75rem] font-bold leading-tight sm:text-[2.125rem]">{title}</h1>
            {description && <p className="text-[0.9375rem] text-ink-2">{description}</p>}
          </div>
          {action && <div className="flex flex-wrap items-center gap-2">{action}</div>}
        </div>
        <dl className="grid grid-cols-2 border-t border-rule-strong md:grid-cols-2 md:border-l md:border-t-0">
          {cells.map(([k, v], i) => (
            <div key={k} className={cn("min-w-0 px-4 py-2.5 md:min-w-[8.5rem]", i % 2 === 1 && "border-l border-rule", i > 1 && "border-t border-rule")}>
              <dt className="text-[0.75rem] text-ink-3">{k}</dt>
              <dd className={cn("flex items-center gap-2 break-words text-[1.0625rem] font-semibold leading-snug", k !== "Role" && "draft", k === "Revision" && "text-[1.25rem]")}>
                {v}
                {k === "Revision" && plan && plan.revision_no >= 2 && <RevisionMark letter={v} />}
              </dd>
            </div>
          ))}
        </dl>
      </div>
      {next && <div className="border-t border-rule-strong bg-plate/60 px-4 py-3 sm:px-5">{next}</div>}
    </header>
  );
}
