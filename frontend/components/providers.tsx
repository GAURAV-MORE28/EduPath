"use client";

import { MotionConfig } from "motion/react";

/**
 * App-wide client providers. `reducedMotion="user"` makes every Motion
 * component honour the OS `prefers-reduced-motion` setting: transform and
 * layout animations are disabled, opacity/colour still resolve.
 */
export function Providers({ children }: { children: React.ReactNode }) {
  return <MotionConfig reducedMotion="user">{children}</MotionConfig>;
}
