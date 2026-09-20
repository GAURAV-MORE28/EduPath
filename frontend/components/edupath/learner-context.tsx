"use client";

import { createContext, useCallback, useContext, useMemo } from "react";
import { humanizeId } from "@/lib/format";
import { useRoles, useSkillIndex } from "@/lib/hooks";
import type { LearnerProfile, Role, Skill } from "@/lib/types";

interface LearnerCtx {
  profile: LearnerProfile;
  role: Role | undefined;
  skills: Record<string, Skill>;
  /** Catalog label for a skill id; humanised id until the catalog has loaded. */
  labelFor: (skillId: string) => string;
}

const Ctx = createContext<LearnerCtx | null>(null);

export function LearnerProvider({ profile, children }: { profile: LearnerProfile; children: React.ReactNode }) {
  const { data: roles } = useRoles();
  const { byId } = useSkillIndex();
  const labelFor = useCallback((id: string) => byId[id]?.label ?? humanizeId(id), [byId]);
  const value = useMemo<LearnerCtx>(
    () => ({ profile, role: roles?.find((r) => r.role_id === profile.target_role_id), skills: byId, labelFor }),
    [profile, roles, byId, labelFor],
  );
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function useLearner(): LearnerCtx {
  const v = useContext(Ctx);
  if (!v) throw new Error("useLearner must be used inside the dashboard shell");
  return v;
}
