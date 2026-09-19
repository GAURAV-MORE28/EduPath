"use client";

/**
 * Route-level error boundary (Next.js app router convention). Catches
 * failures from the dashboard's server-side API calls — most commonly the
 * backend being unreachable — and offers a retry instead of a hard crash.
 */
export default function DashboardError({
  error,
  retry,
}: {
  error: Error & { digest?: string };
  retry: () => void;
}) {
  return (
    <div className="mx-auto flex w-full max-w-5xl flex-1 flex-col items-center justify-center gap-4 px-6 py-10 text-center">
      <h2 className="text-lg font-semibold">Couldn&apos;t load the dashboard</h2>
      <p className="max-w-md text-sm text-zinc-500">
        {error.message || "The API may be unreachable. Check that the backend is running."}
      </p>
      <button
        onClick={() => retry()}
        className="rounded-full bg-zinc-900 px-5 py-2 text-sm font-medium text-white hover:bg-zinc-700 dark:bg-white dark:text-black dark:hover:bg-zinc-200"
      >
        Try again
      </button>
    </div>
  );
}
