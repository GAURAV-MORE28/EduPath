import Link from "next/link";
import { EvidenceCard } from "@/components/edupath/evidence";
import { HeroSpecimen } from "@/components/edupath/hero-specimen";
import { LoopRibbon } from "@/components/edupath/loop-ribbon";
import { Wordmark } from "@/components/edupath/wordmark";
import { buttonVariants } from "@/components/ui/button";
import { cn } from "@/lib/utils";

const LOOP = [
  ["Evidence", "Claims tied to source text"],
  ["Understand", "Each skill graded by tier"],
  ["Diagnose", "Gap to your target role"],
  ["Plan", "A week that fits your hours"],
  ["Learn", "Resources and practice"],
  ["Assess", "Checks that update mastery"],
  ["Struggle", "Detected, never guessed"],
  ["Reflect", "Root cause traced"],
  ["Re-plan", "A dated, reversible revision"],
  ["Progress", "Skills acquired"],
] as const;

export default function Home() {
  return (
    <div className="min-h-dvh">
      <header className="border-b border-rule-strong bg-plate">
        <div className="mx-auto flex max-w-[76rem] items-center justify-between px-4 py-3 sm:px-6">
          <Link href="/" aria-label="EduPath home">
            <Wordmark />
          </Link>
          <nav aria-label="Primary" className="flex items-center gap-1">
            <Link href="/dashboard" className="inline-flex min-h-11 items-center px-3 text-[0.9375rem] font-semibold hover:bg-sheet">
              Dashboard
            </Link>
            <Link href="/start" className={cn(buttonVariants({ size: "sm" }))}>
              Start your set
            </Link>
          </nav>
        </div>
      </header>

      <main id="main">
        <section className="mx-auto grid max-w-[76rem] items-center gap-10 px-4 py-12 sm:px-6 sm:py-16 lg:grid-cols-[minmax(0,1fr)_minmax(0,36rem)] lg:gap-14 lg:py-20">
          <div className="space-y-6">
            <h1 className="max-w-[16ch] text-[2.5rem] font-bold leading-[1.05] tracking-[-0.03em] sm:text-[3.5rem] lg:text-[4rem]">
              Know what you can prove, and what to learn next.
            </h1>
            <p className="max-w-[54ch] text-[1.125rem] leading-relaxed text-ink-2">
              Upload your resume or GitHub. EduPath finds the skills in it, ties each one to the words that back it, compares them with the role you want,
              and plans a week that fits your hours. When you get stuck, it works out why and changes the plan, with the reasons written down.
            </p>
            <div className="flex flex-wrap gap-3">
              <Link href="/start" className={cn(buttonVariants({ size: "lg" }))}>
                Start your set
              </Link>
              <a href="#how-a-change-is-drawn" className={cn(buttonVariants({ size: "lg", variant: "outline" }))}>
                See how a revision works
              </a>
            </div>
          </div>
          <HeroSpecimen />
        </section>

        <section className="border-y border-rule-strong bg-paper">
          <div className="mx-auto grid max-w-[76rem] gap-10 px-4 py-14 sm:px-6 lg:grid-cols-[minmax(0,26rem)_minmax(0,1fr)] lg:gap-16">
            <div className="space-y-3">
              <h2 className="text-[1.75rem] font-bold sm:text-[2.125rem]">Every skill keeps its source.</h2>
              <p className="max-w-[46ch] text-[1rem] leading-relaxed text-ink-2">
                &ldquo;Python, 90%&rdquo; tells you nothing. EduPath shows the sentence a skill came from, where it came from, and how strong that kind of evidence
                is. Something you only listed never counts as much as something you built, and neither counts as much as something you have shown in an assessment.
              </p>
            </div>
            <div className="space-y-2">
              <EvidenceCard
                evidence={{
                  evidence_id: "example",
                  skill_id: "skill.python",
                  skill_label: "Python",
                  tier: "E2",
                  source_type: "document",
                  document_id: "example",
                  document_label: "Resume.pdf",
                  span_text: "Built and trained a YOLOv8-based object detector for a custom dataset of five object classes.",
                  span_offsets: { start: 412, end: 508 },
                  verified: true,
                  created_at: "",
                }}
              />
              <p className="text-[0.8125rem] text-ink-3">An example of how a claim is shown. Your own claims come from your own documents.</p>
            </div>
          </div>
        </section>

        <section id="how-a-change-is-drawn" className="mx-auto max-w-[76rem] space-y-8 px-4 py-14 sm:px-6">
          <div className="max-w-[60ch] space-y-3">
            <h2 className="text-[1.75rem] font-bold sm:text-[2.125rem]">A loop that closes.</h2>
            <p className="text-[1rem] leading-relaxed text-ink-2">
              Most plans stop at the plan. EduPath keeps going: it checks what you learned, notices when you are stuck, traces the cause back to a prerequisite,
              and redraws your week. Every step is deterministic code or a model checked by code, and every change can be undone.
            </p>
          </div>
          <LoopRibbon stages={LOOP.map(([label, hint], i) => ({ id: String(i), label, hint, state: "done" as const }))} />
        </section>

        <section className="border-t border-rule-strong bg-plate">
          <div className="mx-auto grid max-w-[76rem] gap-8 px-4 py-14 sm:px-6 md:grid-cols-2">
            <div className="space-y-2">
              <h2 className="text-xl font-bold">It says how sure it is.</h2>
              <p className="max-w-[52ch] text-[0.9375rem] leading-relaxed text-ink-2">
                Mastery is an estimate with a confidence, never a verdict. When the language model is unavailable, EduPath tells you it used its rules instead.
              </p>
            </div>
            <div className="space-y-2">
              <h2 className="text-xl font-bold">You stay in control.</h2>
              <p className="max-w-[52ch] text-[0.9375rem] leading-relaxed text-ink-2">
                Confirm every claim before it counts. Ask why on any plan item. Revert any revision in one step.
              </p>
            </div>
          </div>
        </section>
      </main>

      <footer className="border-t border-rule-strong px-4 py-8 sm:px-6">
        <div className="mx-auto flex max-w-[76rem] flex-wrap items-center justify-between gap-3 text-[0.8125rem] text-ink-2">
          <Wordmark size={20} className="text-ink" />
          <p>Roles come from a curated skill graph. If yours is not in it, EduPath says so instead of guessing.</p>
        </div>
      </footer>
    </div>
  );
}
