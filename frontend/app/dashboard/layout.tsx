"use client";

import { useRouter } from "next/navigation";
import { useEffect } from "react";
import { AppShell } from "@/components/edupath/app-shell";
import { LearnerProvider } from "@/components/edupath/learner-context";
import { ErrorState, LoadingState } from "@/components/edupath/states";
import { useProfile } from "@/lib/hooks";

/**
 * The learner app. Guards every /dashboard route: no profile yet means the
 * learner has not been through intake, so send them to /start rather than
 * render screens with nothing to show.
 */
export default function DashboardLayout({ children }: { children: React.ReactNode }) {
  const router = useRouter();
  const { data: profile, status, error, reload } = useProfile();

  useEffect(() => {
    if (status === "ready" && profile === null) router.replace("/start");
  }, [status, profile, router]);

  if (status === "error") {
    return (
      <main id="main" className="mx-auto max-w-2xl px-4 py-16">
        <ErrorState error={error} onRetry={reload} />
      </main>
    );
  }
  if (status === "loading" || !profile) {
    return (
      <main id="main" className="mx-auto max-w-3xl px-4 py-16">
        <LoadingState label="Opening your set" variant="plate" />
      </main>
    );
  }

  return (
    <LearnerProvider profile={profile}>
      <AppShell>{children}</AppShell>
    </LearnerProvider>
  );
}
