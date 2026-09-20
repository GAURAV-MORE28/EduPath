"use client";

import { motion } from "motion/react";
import { useMemo } from "react";
import { SKILL_STATE_META, gapState, type SkillState } from "@/lib/format";
import type { SkillGap } from "@/lib/types";
import { cn } from "@/lib/utils";
import { SkillGlyph } from "./skill-status";

const COL_W = 232;
const NODE_W = 204;
const NODE_H = 36;
const ROW_H = 46;
const PAD = 16;

interface Placed {
  id: string;
  layer: number;
  row: number;
  x: number;
  y: number;
}

/** Longest-path layering (prerequisites left), then barycentre ordering to cut crossings. */
export function layoutGraph(ids: string[], edges: Array<[string, string]>, labelOf: (id: string) => string) {
  const preds = new Map<string, string[]>();
  const succs = new Map<string, string[]>();
  ids.forEach((id) => {
    preds.set(id, []);
    succs.set(id, []);
  });
  edges.forEach(([p, c]) => {
    if (preds.has(c) && succs.has(p)) {
      preds.get(c)!.push(p);
      succs.get(p)!.push(c);
    }
  });

  const layer: Record<string, number> = {};
  const visiting = new Set<string>();
  const visit = (id: string): number => {
    if (layer[id] !== undefined) return layer[id];
    if (visiting.has(id)) return 0;
    visiting.add(id);
    const ps = preds.get(id) ?? [];
    layer[id] = ps.length ? Math.max(...ps.map(visit)) + 1 : 0;
    visiting.delete(id);
    return layer[id];
  };
  ids.forEach(visit);

  const layers: string[][] = [];
  ids.forEach((id) => (layers[layer[id]] = [...(layers[layer[id]] ?? []), id]));
  const cleaned = layers.map((l) => l ?? []);
  cleaned.forEach((l) => l.sort((a, b) => labelOf(a).localeCompare(labelOf(b))));

  const rowOf: Record<string, number> = {};
  const setRows = () => cleaned.forEach((l) => l.forEach((id, i) => (rowOf[id] = i)));
  setRows();
  const bary = (id: string, neighbours: string[]) => (neighbours.length ? neighbours.reduce((s, n) => s + (rowOf[n] ?? 0), 0) / neighbours.length : rowOf[id]);
  for (let sweep = 0; sweep < 4; sweep++) {
    for (let L = 1; L < cleaned.length; L++) {
      cleaned[L].sort((a, b) => bary(a, preds.get(a)!) - bary(b, preds.get(b)!));
      setRows();
    }
    for (let L = cleaned.length - 2; L >= 0; L--) {
      cleaned[L].sort((a, b) => bary(a, succs.get(a)!) - bary(b, succs.get(b)!));
      setRows();
    }
  }

  const placed: Record<string, Placed> = {};
  cleaned.forEach((l, L) =>
    l.forEach((id, r) => {
      placed[id] = { id, layer: L, row: r, x: PAD + L * COL_W, y: PAD + 28 + r * ROW_H };
    }),
  );
  const rows = Math.max(1, ...cleaned.map((l) => l.length));
  return {
    placed,
    layers: cleaned,
    preds,
    succs,
    width: PAD * 2 + Math.max(1, cleaned.length) * COL_W - (COL_W - NODE_W),
    height: PAD * 2 + 28 + rows * ROW_H,
  };
}

function closure(start: string, next: Map<string, string[]>): Set<string> {
  const seen = new Set<string>();
  const stack = [start];
  while (stack.length) {
    const cur = stack.pop()!;
    (next.get(cur) ?? []).forEach((n) => {
      if (!seen.has(n)) {
        seen.add(n);
        stack.push(n);
      }
    });
  }
  return seen;
}

/**
 * SkillGraph: the role's skills as a drawn network. Prerequisites run left
 * to right; state is drawn as line form (see SkillGlyph). Selecting a skill
 * traces its prerequisite chain in ink and dims the rest. On small screens the
 * same data reads as a staged list, because a 2,000px diagram is not a
 * phone interface.
 */
export function SkillGraph({
  gaps,
  edges,
  selectedId,
  onSelect,
  hiddenStates,
  className,
}: {
  gaps: SkillGap[];
  edges: Array<{ from_skill_id: string; to_skill_id: string }>;
  selectedId?: string | null;
  onSelect: (skillId: string) => void;
  hiddenStates?: Set<SkillState>;
  className?: string;
}) {
  const byId = useMemo(() => Object.fromEntries(gaps.map((g) => [g.skill_id, g])), [gaps]);
  const graph = useMemo(
    () =>
      layoutGraph(
        gaps.map((g) => g.skill_id),
        edges.map((e) => [e.from_skill_id, e.to_skill_id] as [string, string]),
        (id) => byId[id]?.label ?? id,
      ),
    [gaps, edges, byId],
  );
  const ancestors = useMemo(() => (selectedId ? closure(selectedId, graph.preds) : new Set<string>()), [selectedId, graph]);
  const dependents = useMemo(() => (selectedId ? closure(selectedId, graph.succs) : new Set<string>()), [selectedId, graph]);
  const active = !!selectedId;

  const stateOf = (id: string) => gapState(byId[id]);
  const dimmed = (id: string) => {
    if (hiddenStates?.has(stateOf(id))) return true;
    return active && id !== selectedId && !ancestors.has(id) && !dependents.has(id);
  };

  return (
    <div className={className}>
      {/* Canvas: tablet and up */}
      <div className="relative hidden md:block"><div className="scroll-fine max-h-[38rem] overflow-auto border border-rule-strong bg-paper shadow-[inset_-14px_0_12px_-12px_rgb(22_32_42/0.28)]" tabIndex={0} role="region" aria-label="Skill map. Scroll to see all stages.">
        <div className="relative" style={{ width: graph.width, height: graph.height }}>
          <svg className="absolute inset-0" width={graph.width} height={graph.height} aria-hidden>
            <text x={PAD} y={PAD + 8} className="fill-ink-3" fontSize="12">
              Foundations
            </text>
            <text x={graph.width - PAD} y={PAD + 8} textAnchor="end" className="fill-ink-3" fontSize="12">
              Role skills
            </text>
            <line x1={PAD} y1={PAD + 16} x2={graph.width - PAD} y2={PAD + 16} stroke="var(--rule)" />
            {edges.map((e) => {
              const a = graph.placed[e.from_skill_id];
              const b = graph.placed[e.to_skill_id];
              if (!a || !b) return null;
              const x1 = a.x + NODE_W;
              const y1 = a.y + NODE_H / 2;
              const x2 = b.x;
              const y2 = b.y + NODE_H / 2;
              const xm = x1 + (COL_W - NODE_W) / 2;
              const onPath = active && (e.to_skill_id === selectedId || ancestors.has(e.to_skill_id)) && (e.from_skill_id === selectedId || ancestors.has(e.from_skill_id) || false) && (ancestors.has(e.from_skill_id) || e.to_skill_id === selectedId);
              const downstream = active && (e.from_skill_id === selectedId || dependents.has(e.from_skill_id)) && dependents.has(e.to_skill_id);
              return (
                <path
                  key={`${e.from_skill_id}>${e.to_skill_id}`}
                  d={`M${x1} ${y1} H${xm} V${y2} H${x2}`}
                  fill="none"
                  stroke={onPath ? "var(--ink)" : downstream ? "var(--ink-3)" : "var(--rule-strong)"}
                  strokeWidth={onPath ? 1.75 : 1}
                  strokeDasharray={downstream && !onPath ? "4 3" : undefined}
                  opacity={active && !onPath && !downstream ? 0.18 : hiddenStates ? 0.5 : 0.75}
                />
              );
            })}
          </svg>
          {graph.layers.flat().map((id) => {
            const p = graph.placed[id];
            const g = byId[id];
            const state = stateOf(id);
            const selected = id === selectedId;
            return (
              <motion.button
                key={id}
                type="button"
                onClick={() => onSelect(id)}
                aria-pressed={selected}
                aria-label={`${g.label}: ${SKILL_STATE_META[state].label}`}
                title={`${g.label}: ${SKILL_STATE_META[state].label}`}
                className={cn(
                  "absolute flex cursor-pointer items-center gap-2 border px-2 text-left text-[0.8125rem] leading-tight transition-[opacity,box-shadow] duration-200",
                  state === "mastered" ? "border-verified" : state === "blocked" ? "border-rule-strong" : "border-ink",
                  selected ? "z-10 border-ink font-bold shadow-[0_0_0_2px_var(--ink)]" : "hover:border-ink",
                  dimmed(id) && "opacity-25",
                )}
                style={{ left: p.x, top: p.y, width: NODE_W, height: NODE_H }}
                animate={{ backgroundColor: state === "mastered" ? "var(--verified-wash)" : state === "blocked" ? "var(--plate)" : "var(--paper)" }}
                transition={{ duration: 0.4 }}
              >
                <SkillGlyph state={state} size={16} title="" />
                <span className={cn("truncate", state === "blocked" && "text-ink-2")}>{g.label}</span>
              </motion.button>
            );
          })}
        </div>
      </div>
      <p className="mt-1.5 text-[0.8125rem] text-ink-2">Scroll sideways to follow the prerequisites toward the role.</p>
      </div>

      {/* Staged list: phones */}
      <div className="space-y-4 md:hidden">
        {graph.layers.map((ids, L) => (
          <section key={L} aria-label={`Stage ${L + 1}`}>
            <h3 className="mb-1.5 text-[0.8125rem] font-bold text-ink-2">
              {L === 0 ? "Start here: no prerequisites" : `Stage ${L + 1}: needs the stage before`}
            </h3>
            <ul className="plate-quiet reg">
              {ids.map((id) => {
                const state = stateOf(id);
                return (
                  <li key={id} className={cn(dimmed(id) && "opacity-30")}>
                    <button
                      type="button"
                      onClick={() => onSelect(id)}
                      aria-pressed={id === selectedId}
                      className={cn("flex min-h-11 w-full cursor-pointer items-center gap-3 px-3 py-2 text-left text-[0.9375rem]", id === selectedId && "bg-plate font-bold")}
                    >
                      <SkillGlyph state={state} size={18} title="" />
                      <span className="flex-1">{byId[id].label}</span>
                      <span className="text-[0.8125rem] text-ink-2">{SKILL_STATE_META[state].label}</span>
                    </button>
                  </li>
                );
              })}
            </ul>
          </section>
        ))}
      </div>
    </div>
  );
}
