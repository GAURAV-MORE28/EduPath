"""Skill Graph Service — read-only traversal queries over an already-loaded
`SkillGraph` (app/graph/loader.py). Deterministic, no LLM
(ARCHITECTURE_CONTRACTS.md §2). This is the "Graph retrieval" plane of
design §14.1: prerequisites, dependents, role relevance, paths — pure
NetworkX traversal, never embedding similarity.

Explicitly NOT here (Phase 4, Gap Engine — see DO NOT IMPLEMENT in the phase
brief): comparing this structure against a learner's evidence/mastery to
produce `SkillGap[]`/statuses. This module answers "what is true about the
curated graph," not "what is true for this learner."
"""
from __future__ import annotations

from dataclasses import dataclass, field

import networkx as nx

from app.graph.loader import NODE_TYPE_SKILL, SkillGraph

HARD = "hard"


class UnknownRoleError(Exception):
    """Raised when a requested role is not in the curated graph.
    ARCHITECTURE_CONTRACTS.md §5: "If a requested role is not in the curated
    graph: return 'role not supported'. Never invent a graph at runtime."
    """


class UnknownSkillError(Exception):
    pass


@dataclass
class SkillNode:
    skill_id: str
    label: str
    kind: str
    area: str
    aliases: list[str]
    description: str
    assessable: bool


@dataclass
class PathStep:
    skill_id: str
    label: str
    edge_strength: str | None = None  # strength of the edge leading TO this step, if any


@dataclass
class RoleSubgraph:
    role_id: str
    required_skill_ids: set[str]  # exactly what REQUIRES targets (no closure)
    skill_ids: set[str]  # required skills + hard-prerequisite closure
    required_levels: dict[str, int] = field(default_factory=dict)
    weights: dict[str, int] = field(default_factory=dict)


class SkillGraphService:
    def __init__(self, skill_graph: SkillGraph) -> None:
        self.skill_graph = skill_graph
        self.graph = skill_graph.graph
        self.graph_version = skill_graph.graph_version
        self._hard_graph = self._build_hard_prerequisite_graph()

    # -- construction -----------------------------------------------------

    def _build_hard_prerequisite_graph(self) -> nx.DiGraph:
        """A plain DiGraph of only hard PREREQUISITE_OF edges. Kept separate
        from the full MultiDiGraph so ancestor/descendant/topological-order
        queries only ever see the relationship they're defined over (design
        §11.4: "Ancestors of a failed skill; topological layers")."""
        hard = nx.DiGraph()
        hard.add_nodes_from(n for n, d in self.graph.nodes(data=True) if d.get("node_type") == NODE_TYPE_SKILL)
        for u, v, data in self.graph.edges(data=True):
            if data.get("type") == "PREREQUISITE_OF" and data.get("strength") == HARD:
                hard.add_edge(u, v)
        return hard

    # -- node lookups -------------------------------------------------------

    def get_skill(self, skill_id: str) -> SkillNode:
        if skill_id not in self.graph or self.graph.nodes[skill_id].get("node_type") != NODE_TYPE_SKILL:
            raise UnknownSkillError(f"Unknown skill: {skill_id!r}")
        d = self.graph.nodes[skill_id]
        return SkillNode(
            skill_id=skill_id,
            label=d["label"],
            kind=d["kind"],
            area=d["area"],
            aliases=d.get("aliases", []),
            description=d.get("description", ""),
            assessable=d.get("assessable", True),
        )

    def has_role(self, role_id: str) -> bool:
        return role_id in self.graph and self.graph.nodes[role_id].get("node_type") == "Role"

    # -- prerequisite traversal ---------------------------------------------

    def hard_ancestors(self, skill_id: str) -> set[str]:
        """Skills that must be learned before `skill_id` (transitively),
        over hard PREREQUISITE_OF edges only. design §11.4 "Prerequisite
        reasoning": Ancestors of a failed skill."""
        self._require_skill(skill_id)
        return nx.ancestors(self._hard_graph, skill_id) if skill_id in self._hard_graph else set()

    def hard_descendants(self, skill_id: str) -> set[str]:
        """Skills that (transitively) depend on `skill_id`."""
        self._require_skill(skill_id)
        return nx.descendants(self._hard_graph, skill_id) if skill_id in self._hard_graph else set()

    def direct_prerequisites(self, skill_id: str, include_soft: bool = True) -> list[str]:
        """Immediate PREREQUISITE_OF predecessors of `skill_id`."""
        self._require_skill(skill_id)
        out = []
        for u, _, data in self.graph.in_edges(skill_id, data=True):
            if data.get("type") != "PREREQUISITE_OF":
                continue
            if not include_soft and data.get("strength") != HARD:
                continue
            out.append(u)
        return out

    def direct_dependents(self, skill_id: str, include_soft: bool = True) -> list[str]:
        """Immediate PREREQUISITE_OF successors of `skill_id` (skills this
        one unlocks)."""
        self._require_skill(skill_id)
        out = []
        for _, v, data in self.graph.out_edges(skill_id, data=True):
            if data.get("type") != "PREREQUISITE_OF":
                continue
            if not include_soft and data.get("strength") != HARD:
                continue
            out.append(v)
        return out

    def is_dag(self) -> bool:
        return nx.is_directed_acyclic_graph(self._hard_graph)

    def hard_prerequisite_out_edges(self, skill_id: str) -> list[tuple[str, int]]:
        """`(to_skill_id, min_level)` for every hard `PREREQUISITE_OF` edge
        leading out of `skill_id` (design §13.3's `graph.hard_out_edges(s)` —
        used by the Gap Engine to compute each skill's effective required
        level: the max of its own role-required level and the `min_level`
        demanded by any in-scope dependent)."""
        self._require_skill(skill_id)
        out = []
        for _, v, data in self.graph.out_edges(skill_id, data=True):
            if data.get("type") == "PREREQUISITE_OF" and data.get("strength") == HARD:
                out.append((v, data.get("min_level") or 1))
        return out

    def part_of_children(self, parent_skill_id: str) -> list[str]:
        """Skills `c` with a `PART_OF` edge `c -> parent_skill_id` (design
        §11.3: "PART_OF | Skill -> Skill (area/parent)"). Used by the Gap
        Engine's claim-evidence-mismatch audit (design §12.4): a claim on a
        parent skill (e.g. "Full Stack") while evidence covers only some of
        its PART_OF children (e.g. "React", not backend/database)."""
        self._require_skill(parent_skill_id)
        return [u for u, _, data in self.graph.in_edges(parent_skill_id, data=True) if data.get("type") == "PART_OF"]

    # -- topological ordering -----------------------------------------------

    def topological_order(self, subset: set[str] | None = None) -> list[str]:
        """A valid learning order for `subset` (default: every skill) w.r.t.
        hard prerequisites. Raises `networkx.NetworkXUnfeasible` if the
        induced subgraph has a cycle (should never happen if
        app/graph/validation.py's DAG check passed at ingestion time)."""
        g = self._hard_graph if subset is None else self._hard_graph.subgraph(subset)
        return list(nx.topological_sort(g))

    def topological_layers(self, subset: set[str] | None = None) -> list[list[str]]:
        """Skills grouped into layers with no hard-prerequisite dependency
        within a layer (design §13.3's `graph.topological_layers(...)` —
        used by the Gap Engine for scheduling order; exposed here as a pure
        graph-structural query the Gap Engine will call in Phase 4)."""
        g = self._hard_graph if subset is None else self._hard_graph.subgraph(subset)
        return [list(layer) for layer in nx.topological_generations(g)]

    # -- role subgraph --------------------------------------------------------

    def role_subgraph(self, role_id: str) -> RoleSubgraph:
        """design §12.1: "Target-role subgraph: role's required skills plus
        prerequisite closure — derived view (not stored), recomputed on
        demand." Raises `UnknownRoleError` if the role isn't curated."""
        if not self.has_role(role_id):
            raise UnknownRoleError(f"role not supported: {role_id!r}")

        required_levels: dict[str, int] = {}
        weights: dict[str, int] = {}
        for _, skill_id, data in self.graph.out_edges(role_id, data=True):
            if data.get("type") != "REQUIRES":
                continue
            required_levels[skill_id] = data["required_level"]
            weights[skill_id] = data["weight"]

        required = set(required_levels)
        closure = set(required)
        for s in required:
            closure |= self.hard_ancestors(s)

        return RoleSubgraph(
            role_id=role_id,
            required_skill_ids=required,
            skill_ids=closure,
            required_levels=required_levels,
            weights=weights,
        )

    # -- explanation ------------------------------------------------------

    def shortest_prerequisite_path(self, source_skill_id: str, target_skill_id: str) -> list[PathStep] | None:
        """Shortest hard-prerequisite path from `source_skill_id` to
        `target_skill_id` (in prerequisite -> dependent direction). Returns
        `None` if no such path exists."""
        self._require_skill(source_skill_id)
        self._require_skill(target_skill_id)
        if source_skill_id not in self._hard_graph or target_skill_id not in self._hard_graph:
            return None
        try:
            path = nx.shortest_path(self._hard_graph, source_skill_id, target_skill_id)
        except nx.NetworkXNoPath:
            return None
        return [PathStep(skill_id=sid, label=self.get_skill(sid).label) for sid in path]

    def explain_skill_path(self, skill_id: str, role_id: str) -> list[PathStep] | None:
        """design §11.4/§14.4: `explain_skill_path(skill)` — the shortest
        hard-prerequisite path from `skill_id` to the *nearest*
        role-required skill it unlocks (e.g. "chain rule -> backpropagation
        -> training neural networks"). Answers "why do I need this skill for
        my role?" Returns `None` if `skill_id` has no hard-prerequisite path
        to any of the role's required skills (e.g. it is itself unrelated to
        this role, or is already a leaf requirement with nothing beyond it).
        """
        role = self.role_subgraph(role_id)
        self._require_skill(skill_id)
        if skill_id in role.required_skill_ids:
            return [PathStep(skill_id=skill_id, label=self.get_skill(skill_id).label)]
        if skill_id not in self._hard_graph:
            return None

        best: list[str] | None = None
        for target in role.required_skill_ids:
            if target not in self._hard_graph:
                continue
            try:
                path = nx.shortest_path(self._hard_graph, skill_id, target)
            except nx.NetworkXNoPath:
                continue
            if best is None or len(path) < len(best):
                best = path
        if best is None:
            return None
        return [PathStep(skill_id=sid, label=self.get_skill(sid).label) for sid in best]

    # -- misconception context ------------------------------------------------

    def misconceptions_for_skill(self, skill_id: str) -> list[str]:
        """Misconception IDs whose `MISCONCEPTION_OF` target is `skill_id`."""
        self._require_skill(skill_id)
        return [
            u
            for u, _, data in self.graph.in_edges(skill_id, data=True)
            if data.get("type") == "MISCONCEPTION_OF"
        ]

    def remediation_resources_for_misconception(self, misconception_id: str) -> list[str]:
        if misconception_id not in self.graph:
            raise ValueError(f"Unknown misconception: {misconception_id!r}")
        return [v for _, v, data in self.graph.out_edges(misconception_id, data=True) if data.get("type") == "REMEDIATED_BY"]

    # -- resource targeting ------------------------------------------------

    def resources_targeting(self, skill_id: str) -> list[str]:
        """Resource IDs whose `TARGETS` edge points at `skill_id` (design
        §11.4 "Resource recommendation": "TARGETS edges anchor candidates to
        the exact gap node")."""
        self._require_skill(skill_id)
        return [u for u, _, data in self.graph.in_edges(skill_id, data=True) if data.get("type") == "TARGETS"]

    # -- internal -----------------------------------------------------------

    def _require_skill(self, skill_id: str) -> None:
        if skill_id not in self.graph or self.graph.nodes[skill_id].get("node_type") != NODE_TYPE_SKILL:
            raise UnknownSkillError(f"Unknown skill: {skill_id!r}")
