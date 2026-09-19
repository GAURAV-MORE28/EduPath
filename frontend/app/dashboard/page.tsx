import { apiClient } from "@/lib/api-client";

// This page depends on live backend/database/orchestration state, so it must
// never be statically prerendered at build time.
export const dynamic = "force-dynamic";

/**
 * Base dashboard shell. Real widgets (gap graph, weekly plan, agent trace
 * panel, chat) are added by the phases that own that data (4, 5, 8/31, 9).
 * This page only proves the API client + loading/error conventions work
 * end to end against a real backend call (`GET /api/health`).
 */
export default async function DashboardPage() {
  const health = await apiClient.getHealth();

  return (
    <div className="mx-auto flex w-full max-w-5xl flex-1 flex-col gap-6 px-6 py-10">
      <h1 className="text-2xl font-semibold tracking-tight">Dashboard</h1>

      <section className="grid grid-cols-1 gap-4 sm:grid-cols-3">
        <StatusCard
          label="API"
          ok={health.status === "ok"}
          detail={health.status}
        />
        <StatusCard
          label="Database"
          ok={health.database.ok}
          detail={health.database.error ?? "connected"}
        />
        <StatusCard
          label="Orchestration"
          ok={health.orchestration.ok}
          detail={health.orchestration.error ?? "compiled"}
        />
      </section>

      <section className="grid grid-cols-1 gap-4 sm:grid-cols-2">
        <PlaceholderPanel title="Skill gaps" />
        <PlaceholderPanel title="Weekly plan" />
        <PlaceholderPanel title="Agent trace" />
        <PlaceholderPanel title="Tutor chat" />
      </section>
    </div>
  );
}

function StatusCard({
  label,
  ok,
  detail,
}: {
  label: string;
  ok: boolean;
  detail: string;
}) {
  return (
    <div className="rounded-lg border border-zinc-200 p-4 dark:border-zinc-800">
      <div className="flex items-center justify-between">
        <span className="text-sm font-medium text-zinc-600 dark:text-zinc-400">
          {label}
        </span>
        <span
          className={`h-2 w-2 rounded-full ${ok ? "bg-green-500" : "bg-red-500"}`}
        />
      </div>
      <p className="mt-2 text-sm text-zinc-500">{detail}</p>
    </div>
  );
}

function PlaceholderPanel({ title }: { title: string }) {
  return (
    <div className="flex min-h-32 flex-col items-center justify-center rounded-lg border border-dashed border-zinc-300 p-6 text-sm text-zinc-400 dark:border-zinc-700">
      {title} — coming in a later phase
    </div>
  );
}
