"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import {
  Activity,
  CalendarCheck,
  FileSearch,
  LayoutDashboard,
  MessageSquareText,
  MoreHorizontal,
  Network,
  PencilRuler,
  Target,
  TrendingUp,
} from "lucide-react";
import { useState } from "react";
import { Sheet, SheetContent, SheetHeader as DrawerHeader, SheetTitle } from "@/components/ui/sheet";
import { DEMO_MODE, api } from "@/lib/api-client";
import { useQuery } from "@/lib/query";
import { cn } from "@/lib/utils";
import { useLearner } from "./learner-context";
import { Wordmark } from "./wordmark";

export const NAV = [
  { href: "/dashboard", label: "Overview", icon: LayoutDashboard, primary: true },
  { href: "/dashboard/plan", label: "Plan", icon: CalendarCheck, primary: true },
  { href: "/dashboard/skills", label: "Skill map", icon: Network, primary: true },
  { href: "/dashboard/tutor", label: "Tutor", icon: MessageSquareText, primary: true },
  { href: "/dashboard/evidence", label: "Evidence", icon: FileSearch },
  { href: "/dashboard/gaps", label: "Gaps", icon: Target },
  { href: "/dashboard/practice", label: "Practice", icon: PencilRuler },
  { href: "/dashboard/progress", label: "Progress", icon: TrendingUp },
  { href: "/dashboard/trace", label: "Agent trace", icon: Activity },
] as const;

function isActive(pathname: string, href: string) {
  return href === "/dashboard" ? pathname === href : pathname.startsWith(href);
}

function SystemStatus() {
  const { data, status } = useQuery("health", api.health);
  const rows: Array<[string, boolean | null]> = [
    ["API", status === "ready" ? data?.status === "ok" || data?.status === "degraded" : status === "error" ? false : null],
    ["Database", data ? data.database.ok : status === "error" ? false : null],
    ["Orchestration", data ? data.orchestration.ok : status === "error" ? false : null],
  ];
  return (
    <div className="space-y-1.5">
      <p className="text-[0.75rem] font-semibold text-ink-2">System</p>
      <ul className="space-y-1">
        {rows.map(([name, ok]) => (
          <li key={name} className="flex items-center justify-between text-[0.8125rem] text-ink-2">
            {name}
            <span className="inline-flex items-center gap-1.5 font-semibold text-ink">
              <span
                aria-hidden
                className={cn("size-2 border", ok === true ? "border-verified bg-verified" : ok === false ? "border-revision bg-paper" : "border-rule-strong bg-paper")}
              />
              {ok === true ? "Up" : ok === false ? "Down" : "Checking"}
            </span>
          </li>
        ))}
      </ul>
    </div>
  );
}

function NavLink({ item, pathname, onNavigate }: { item: (typeof NAV)[number]; pathname: string; onNavigate?: () => void }) {
  const active = isActive(pathname, item.href);
  const Icon = item.icon;
  return (
    <Link
      href={item.href}
      onClick={onNavigate}
      aria-current={active ? "page" : undefined}
      className={cn(
        "flex min-h-11 items-center gap-3 border px-3 text-[0.9375rem] transition-colors duration-150",
        active ? "border-rule-strong bg-paper font-bold text-ink" : "border-transparent text-ink-2 hover:bg-sheet hover:text-ink",
      )}
    >
      <Icon className="size-[18px] shrink-0" aria-hidden />
      {item.label}
    </Link>
  );
}

export function AppShell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const { profile, role } = useLearner();
  const [more, setMore] = useState(false);

  return (
    <div className="min-h-dvh lg:grid lg:grid-cols-[15.5rem_minmax(0,1fr)]">
      {/* Index rail: desktop */}
      <aside className="sticky top-0 hidden h-dvh flex-col justify-between overflow-y-auto border-r border-rule-strong bg-plate p-4 lg:flex">
        <div className="space-y-6">
          <Link href="/" className="block px-1 py-1" aria-label="EduPath home">
            <Wordmark />
          </Link>
          <nav aria-label="Sheets" className="space-y-1">
            {NAV.map((item) => (
              <NavLink key={item.href} item={item} pathname={pathname} />
            ))}
          </nav>
        </div>
        <div className="space-y-4">
          <div className="space-y-0.5 border-t border-rule-strong pt-4">
            <p className="text-[0.75rem] font-semibold text-ink-2">Target role</p>
            <p className="text-[0.9375rem] font-bold leading-snug">{role?.title ?? "Loading role"}</p>
            <p className="text-[0.8125rem] text-ink-2">{profile.weekly_hours} h a week</p>
          </div>
          <SystemStatus />
          {DEMO_MODE && (
            <p className="border border-dashed border-ink-3 px-2 py-1 text-[0.75rem] font-semibold text-ink-2">Demo mode is on</p>
          )}
        </div>
      </aside>

      {/* Top bar: mobile and tablet */}
      <header className="sticky top-0 z-30 flex items-center justify-between border-b border-rule-strong bg-plate px-4 py-2 lg:hidden">
        <Link href="/" aria-label="EduPath home">
          <Wordmark />
        </Link>
        <p className="max-w-[55%] truncate text-right text-[0.8125rem] font-semibold text-ink-2">{role?.title ?? ""}</p>
      </header>

      <main id="main" className="min-w-0 px-4 pb-28 pt-5 sm:px-6 lg:px-10 lg:pb-16 lg:pt-8">
        <div className="mx-auto w-full max-w-[75rem]">{children}</div>
      </main>

      {/* Bottom tabs: mobile and tablet */}
      <nav
        aria-label="Sheets"
        className="fixed inset-x-0 bottom-0 z-30 grid grid-cols-5 border-t border-rule-strong bg-plate pb-[env(safe-area-inset-bottom,0px)] lg:hidden"
      >
        {NAV.filter((n) => "primary" in n && n.primary).map((item) => {
          const active = isActive(pathname, item.href);
          const Icon = item.icon;
          return (
            <Link
              key={item.href}
              href={item.href}
              aria-current={active ? "page" : undefined}
              className={cn(
                "flex min-h-14 flex-col items-center justify-center gap-0.5 text-[0.75rem]",
                active ? "bg-paper font-bold text-ink shadow-[inset_0_2px_0_var(--ink)]" : "text-ink-2",
              )}
            >
              <Icon className="size-5" aria-hidden />
              {item.label}
            </Link>
          );
        })}
        <button
          type="button"
          onClick={() => setMore(true)}
          className="flex min-h-14 cursor-pointer flex-col items-center justify-center gap-0.5 text-[0.75rem] text-ink-2"
        >
          <MoreHorizontal className="size-5" aria-hidden />
          More
        </button>
      </nav>

      <Sheet open={more} onOpenChange={setMore}>
        <SheetContent side="bottom" className="max-h-[80dvh] overflow-y-auto border-t border-rule-strong bg-paper pb-[env(safe-area-inset-bottom,0px)]">
          <DrawerHeader>
            <SheetTitle className="text-lg font-bold">More sheets</SheetTitle>
          </DrawerHeader>
          <div className="space-y-1 px-4 pb-4">
            {NAV.filter((n) => !("primary" in n && n.primary)).map((item) => (
              <NavLink key={item.href} item={item} pathname={pathname} onNavigate={() => setMore(false)} />
            ))}
            <div className="pt-4">
              <SystemStatus />
            </div>
          </div>
        </SheetContent>
      </Sheet>
    </div>
  );
}
