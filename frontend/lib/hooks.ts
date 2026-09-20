"use client";

import { useMemo } from "react";
import { api } from "./api-client";
import { useQuery } from "./query";
import type { Resource, Skill } from "./types";

export const useProfile = () => useQuery("profile", api.profile);
export const useRoles = () => useQuery("roles", api.roles);
export const useGaps = (enabled = true) => useQuery(enabled ? "gaps" : null, api.gaps);
export const usePlan = (enabled = true) => useQuery(enabled ? "plan" : null, api.currentPlan);
export const useRevisions = (enabled = true) => useQuery(enabled ? "revisions" : null, api.revisions);
export const useEvidence = (enabled = true) => useQuery(enabled ? "evidence" : null, api.evidence);
export const useProgress = (enabled = true) => useQuery(enabled ? "progress" : null, api.progress);
export const useSkillDetail = (skillId: string | null) =>
  useQuery(skillId ? `skill:${skillId}` : null, () => api.skillDetail(skillId!));

/** Every skill in the curated catalog, indexed by id (labels and descriptions come from the API). */
export function useSkillIndex() {
  const q = useQuery("skills:all", () => api.skills());
  const byId = useMemo(() => {
    const map: Record<string, Skill> = {};
    (q.data ?? []).forEach((s) => (map[s.skill_id] = s));
    return map;
  }, [q.data]);
  return { ...q, byId };
}

/** Resource metadata for a set of ids (plan items only carry ids). */
export function useResources(ids: Array<string | null | undefined>) {
  const wanted = useMemo(() => [...new Set(ids.filter((i): i is string => !!i))].sort(), [ids]);
  const q = useQuery(wanted.length ? `resources:${wanted.join(",")}` : null, () => api.resources(wanted));
  const byId = useMemo(() => {
    const map: Record<string, Resource> = {};
    (q.data ?? []).forEach((r) => (map[r.resource_id] = r));
    return map;
  }, [q.data]);
  return { ...q, byId };
}
