"use client";

import { ErrorState } from "@/components/edupath/states";

/**
 * Route-level error boundary (Next.js 16 `retry` convention). Catches
 * rendering failures inside a dashboard sheet; data-loading failures are
 * handled inline by each sheet's own ErrorState.
 */
export default function DashboardError({ error, retry }: { error: Error & { digest?: string }; retry: () => void }) {
  return <ErrorState error={error} onRetry={() => retry()} title="This sheet could not be drawn" />;
}
