"use client";

import { useInView } from "motion/react";
import { useRef } from "react";
import { RevisionCloud } from "./revision";
import { RevisionMark } from "./plan";

/**
 * An illustration of a revision, not a learner's data: the plan before and
 * after a failed assessment, with the inserted work clouded. The cloud draws
 * once, when the sheet scrolls into view.
 */
export function HeroSpecimen() {
  const ref = useRef<HTMLDivElement>(null);
  const inView = useInView(ref, { once: true, margin: "-10% 0px" });

  return (
    <figure ref={ref} className="plate w-full max-w-[36rem]">
      <div className="grid grid-cols-[1fr_auto] border-b border-rule-strong">
        <p className="px-4 py-2.5 text-[0.9375rem] font-bold">Weekly plan: Backpropagation</p>
        <p className="draft border-l border-rule-strong px-4 py-2.5 text-[0.9375rem] font-semibold">Rev A &rarr; B</p>
      </div>
      <div className="grid gap-px bg-rule-strong sm:grid-cols-2">
        <div className="bg-paper p-4">
          <p className="mb-2 text-[0.8125rem] font-semibold text-ink-2">Revision A</p>
          <ul className="space-y-2 text-[0.9375rem]">
            <li className="border border-rule-strong p-2.5">Backpropagation</li>
            <li className="border border-rule-strong p-2.5">Optimization</li>
            <li className="border border-rule-strong p-2.5">Neural network training</li>
          </ul>
        </div>
        <div className="bg-paper p-4">
          <p className="mb-2 flex items-center justify-between text-[0.8125rem] font-semibold text-revision">
            Revision B <RevisionMark letter="B" />
          </p>
          <ul className="space-y-2 text-[0.9375rem]">
            <li className="pb-0.5 pt-0.5">
              <RevisionCloud active={inView}>
                <div className="border border-revision bg-revision-wash/50 p-2.5 font-semibold">Chain rule refresher</div>
              </RevisionCloud>
            </li>
            <li className="border border-revision bg-revision-wash/50 p-2.5 font-semibold">Chain rule probe</li>
            <li className="border border-rule-strong p-2.5">Backpropagation</li>
            <li className="border border-rule-strong p-2.5">Optimization</li>
          </ul>
        </div>
      </div>
      <figcaption className="border-t border-rule-strong bg-plate/60 px-4 py-2.5 text-[0.8125rem] text-ink-2">
        Illustration: how a revision is drawn. Your own set is built from your evidence, and every change carries its reason.
      </figcaption>
    </figure>
  );
}
