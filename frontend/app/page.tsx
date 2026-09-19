import Link from "next/link";

export default function Home() {
  return (
    <div className="flex flex-1 flex-col items-center justify-center gap-6 px-6 py-24 text-center">
      <h1 className="max-w-xl text-4xl font-semibold tracking-tight">
        EduPath
      </h1>
      <p className="max-w-md text-lg text-zinc-600 dark:text-zinc-400">
        An adaptive learner-intelligence system. This is the Phase 1
        foundation shell — profiling, planning, and tutoring land in later
        phases.
      </p>
      <Link
        href="/dashboard"
        className="rounded-full bg-zinc-900 px-6 py-3 text-sm font-medium text-white transition-colors hover:bg-zinc-700 dark:bg-white dark:text-black dark:hover:bg-zinc-200"
      >
        Open dashboard
      </Link>
    </div>
  );
}
