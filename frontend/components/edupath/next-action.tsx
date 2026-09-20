"use client";

import { ArrowRight, ExternalLink, PencilRuler } from "lucide-react";
import Link from "next/link";
import { buttonVariants } from "@/components/ui/button";
import { minutes } from "@/lib/format";
import { usePlan, useResources } from "@/lib/hooks";
import { cn } from "@/lib/utils";
import { useLearner } from "./learner-context";
import { itemTitle, practiceHref } from "./plan";

/**
 * NextAction: the one imperative for the sheet. It reads the learner's real
 * plan: the first planned item (by day) becomes "do this", otherwise it
 * points at the step that produces a plan.
 */
export function NextAction() {
  const { labelFor } = useLearner();
  const { data: plan, status } = usePlan();
  const next = plan?.items.filter((i) => i.status === "planned").sort((a, b) => a.day_slot - b.day_slot)[0];
  const { byId } = useResources([next?.resource_id]);
  const resource = next?.resource_id ? byId[next.resource_id] : undefined;

  let text = "Reading your plan";
  let cta: React.ReactNode = null;
  const btn = cn(buttonVariants({ size: "default" }));

  if (status === "ready") {
    if (!plan) {
      text = "You have no plan yet. Build week one.";
      cta = (
        <Link href="/dashboard/plan" className={btn}>
          Build week one <ArrowRight />
        </Link>
      );
    } else if (!next) {
      text = "This week's plan is done. Plan the next one.";
      cta = (
        <Link href="/dashboard/plan" className={btn}>
          Plan next week <ArrowRight />
        </Link>
      );
    } else {
      const practice = next.type === "probe" || next.type === "practice";
      text = `Next: ${itemTitle(next, resource, labelFor)}, ${minutes(next.est_minutes)}`;
      cta = practice ? (
        <Link href={practiceHref(next)} className={btn}>
          <PencilRuler /> Begin {next.type === "probe" ? "check" : "practice"}
        </Link>
      ) : resource ? (
        <a href={resource.url} target="_blank" rel="noopener noreferrer" className={btn}>
          <ExternalLink /> Open resource
        </a>
      ) : (
        <Link href="/dashboard/plan" className={btn}>
          See the plan <ArrowRight />
        </Link>
      );
    }
  }

  return (
    <div className="flex flex-wrap items-center justify-between gap-3">
      <p className="min-w-0 max-w-[60ch] text-[1rem] font-bold leading-snug">{text}</p>
      {cta}
    </div>
  );
}
