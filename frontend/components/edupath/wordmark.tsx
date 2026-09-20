import { cn } from "@/lib/utils";

/** EduPath mark: a framed sheet with a stepped path and a revision triangle. */
export function Wordmark({ className, size = 26 }: { className?: string; size?: number }) {
  return (
    <span className={cn("inline-flex items-center gap-2.5", className)}>
      <svg width={size} height={size} viewBox="0 0 26 26" aria-hidden>
        <rect x="1" y="1" width="24" height="24" fill="var(--paper)" stroke="var(--ink)" strokeWidth="1.5" />
        <path d="M5 19h5v-5h5V9h6" fill="none" stroke="var(--ink)" strokeWidth="1.5" strokeLinejoin="miter" />
        <path d="M17 4l4 6h-8z" fill="none" stroke="var(--revision)" strokeWidth="1.3" transform="translate(-1.5 3) scale(.85)" />
      </svg>
      <span className="text-[1.125rem] font-bold tracking-tight">EduPath</span>
    </span>
  );
}
