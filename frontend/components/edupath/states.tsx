"use client";

import { AlertTriangle, CloudOff, FileSearch, Info, RefreshCw, ServerCrash } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { ApiError, API_BASE_URL } from "@/lib/api-client";
import { cn } from "@/lib/utils";

/** EmptyState: teaches what belongs here and offers the one action that fills it. */
export function EmptyState({
  title,
  children,
  action,
  icon: Icon = FileSearch,
  className,
}: {
  title: string;
  children?: React.ReactNode;
  action?: React.ReactNode;
  icon?: React.ComponentType<{ className?: string }>;
  className?: string;
}) {
  return (
    <div
      className={cn(
        "flex flex-col items-start gap-3 border border-dashed border-rule-strong bg-paper/60 p-6 sm:p-8",
        className,
      )}
    >
      <Icon className="size-6 text-ink-2" />
      <div className="max-w-[52ch] space-y-1">
        <h3 className="text-lg font-bold">{title}</h3>
        {children && <div className="text-[0.9375rem] text-ink-2">{children}</div>}
      </div>
      {action && <div className="mt-1 flex flex-wrap gap-2">{action}</div>}
    </div>
  );
}

/** LoadingState: skeleton plates that hold the final layout's space, never a centered spinner. */
export function LoadingState({
  label = "Loading",
  rows = 4,
  variant = "register",
  className,
}: {
  label?: string;
  rows?: number;
  variant?: "register" | "plate" | "grid";
  className?: string;
}) {
  return (
    <div role="status" aria-live="polite" aria-busy="true" className={cn("w-full", className)}>
      <span className="sr-only">{label}</span>
      {variant === "register" && (
        <div className="plate-quiet divide-y divide-rule">
          {Array.from({ length: rows }).map((_, i) => (
            <div key={i} className="flex items-center gap-4 p-4">
              <Skeleton className="size-5 rounded-full bg-plate" />
              <div className="flex-1 space-y-2">
                <Skeleton className="h-4 w-2/5 bg-plate" />
                <Skeleton className="h-3 w-4/5 bg-plate" />
              </div>
              <Skeleton className="hidden h-4 w-14 bg-plate sm:block" />
            </div>
          ))}
        </div>
      )}
      {variant === "plate" && (
        <div className="plate-quiet space-y-3 p-6">
          <Skeleton className="h-5 w-1/3 bg-plate" />
          <Skeleton className="h-3 w-full bg-plate" />
          <Skeleton className="h-3 w-11/12 bg-plate" />
          <Skeleton className="h-3 w-4/5 bg-plate" />
        </div>
      )}
      {variant === "grid" && (
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {Array.from({ length: rows }).map((_, i) => (
            <div key={i} className="plate-quiet space-y-3 p-5">
              <Skeleton className="h-4 w-1/2 bg-plate" />
              <Skeleton className="h-3 w-full bg-plate" />
              <Skeleton className="h-3 w-3/4 bg-plate" />
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

function describeError(error: unknown): { title: string; body: string; icon: typeof AlertTriangle } {
  if (error instanceof ApiError) {
    if (error.isUnreachable) {
      return {
        title: "EduPath's API isn't answering",
        body: `The browser got no usable answer from ${API_BASE_URL}. Check that the backend is running (docker compose up, or uvicorn app.main:app). If it is, the server may have hit an error; its log names the cause.`,
        icon: ServerCrash,
      };
    }
    if (error.status === 422 && /role not supported/i.test(error.message)) {
      return {
        title: "That role isn't in the curated graph",
        body: "EduPath only plans for roles whose skills and prerequisites have been curated. Pick one of the supported roles.",
        icon: Info,
      };
    }
    if (error.status === 404) {
      return { title: "Nothing here yet", body: error.message, icon: FileSearch };
    }
    if (error.status >= 500) {
      return {
        title: "The API hit an error",
        body: "Something failed on the server. Your data is unchanged. Try again in a moment.",
        icon: CloudOff,
      };
    }
    return { title: "That request was rejected", body: error.message, icon: AlertTriangle };
  }
  return { title: "Something went wrong", body: error instanceof Error ? error.message : "Unexpected error.", icon: AlertTriangle };
}

/** ErrorState: says what failed and how to recover, with a retry. */
export function ErrorState({
  error,
  onRetry,
  title,
  className,
}: {
  error: unknown;
  onRetry?: () => void;
  title?: string;
  className?: string;
}) {
  const d = describeError(error);
  const Icon = d.icon;
  return (
    <div role="alert" className={cn("flex flex-col items-start gap-3 border border-revision bg-revision-wash/60 p-6", className)}>
      <Icon className="size-6 text-revision" aria-hidden />
      <div className="max-w-[56ch] space-y-1">
        <h3 className="text-lg font-bold">{title ?? d.title}</h3>
        <p className="text-[0.9375rem] text-ink-2">{d.body}</p>
      </div>
      {onRetry && (
        <Button variant="outline" onClick={onRetry}>
          <RefreshCw /> Try again
        </Button>
      )}
    </div>
  );
}

/**
 * DegradedNotice: the system ran, but on its deterministic path because the
 * language model was unavailable. Said plainly, never hidden.
 */
export function DegradedNotice({ children, className }: { children?: React.ReactNode; className?: string }) {
  return (
    <div className={cn("flex items-start gap-3 border border-dashed border-ink-3 bg-paper px-4 py-3 text-[0.875rem] text-ink-2", className)}>
      <Info className="mt-0.5 size-4 shrink-0 text-ink" aria-hidden />
      <p className="max-w-[70ch]">
        <span className="font-semibold text-ink">Running without a language model. </span>
        {children ??
          "EduPath used its deterministic path here: rules and the curated graph made this decision, and no model wrote the wording."}
      </p>
    </div>
  );
}
