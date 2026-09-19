"""NetworkX graph loader (ARCHITECTURE_CONTRACTS.md §5: "Graph is curated
offline, versioned, loaded from Postgres into NetworkX at process startup.
The LLM cannot add graph edges at runtime.").

Builds one `networkx.MultiDiGraph` holding all five closed-set node types
(Role, Skill, Misconception, Resource, PracticeItem — design §11.2) and all
nine closed-set edge types (design §11.3), regardless of which relational
table each edge actually lives in (see app/db/models.py's `SkillEdge`
docstring for why only three of the nine live in one table). Node IDs are
globally unique curated slugs (`skill.*`, `role.*`, `res.*`, `misc.*`,
`item.*` — ARCHITECTURE_CONTRACTS.md §7), so one graph namespace is safe.

This module only *builds* the graph from an already-validated
`CatalogSnapshot` (app/repositories/catalog_repository.py); it does not talk
to the database beyond that snapshot fetch, and does not run structural
invariant checks (app/graph/validation.py). Traversal/query operations live
in app/graph/queries.py, kept separate so "load" and "query" can be tested
independently.
"""
from __future__ import annotations

from dataclasses import dataclass

import networkx as nx

from app.repositories.catalog_repository import CatalogRepository, CatalogSnapshot

NODE_TYPE_ROLE = "Role"
NODE_TYPE_SKILL = "Skill"
NODE_TYPE_MISCONCEPTION = "Misconception"
NODE_TYPE_RESOURCE = "Resource"
NODE_TYPE_PRACTICE_ITEM = "PracticeItem"


@dataclass
class SkillGraph:
    graph: nx.MultiDiGraph
    graph_version: str


class GraphLoader:
    """Loads the curated catalog from Postgres and builds the in-process
    NetworkX graph. One instance per load; call `load()` once at process
    startup (or on an admin-triggered reload, per design §35) and hold the
    resulting `SkillGraph` for the process lifetime.
    """

    def __init__(self, repository: CatalogRepository) -> None:
        self.repository = repository

    async def load(self) -> SkillGraph:
        snapshot = await self.repository.fetch_all()
        return self.build(snapshot)

    @staticmethod
    def build(snapshot: CatalogSnapshot) -> SkillGraph:
        g = nx.MultiDiGraph()

        for s in snapshot.skills:
            g.add_node(
                s.skill_id,
                node_type=NODE_TYPE_SKILL,
                label=s.label,
                kind=s.kind,
                area=s.area,
                aliases=s.aliases,
                description=s.description,
                assessable=s.assessable,
            )
        for r in snapshot.roles:
            g.add_node(r.role_id, node_type=NODE_TYPE_ROLE, title=r.title, description=r.description)
        for m in snapshot.misconceptions:
            g.add_node(
                m.misconception_id,
                node_type=NODE_TYPE_MISCONCEPTION,
                description=m.description,
                severity=m.severity,
            )
        for res in snapshot.resources:
            g.add_node(
                res.resource_id,
                node_type=NODE_TYPE_RESOURCE,
                title=res.title,
                url=res.url,
                difficulty=res.difficulty,
                modality=res.modality,
                link_status=res.link_status,
            )
        for it in snapshot.practice_items:
            g.add_node(it.item_id, node_type=NODE_TYPE_PRACTICE_ITEM, difficulty=it.difficulty, purpose=it.purpose)

        # Skill <-> Skill: PREREQUISITE_OF / PART_OF / RELATED_TO
        for e in snapshot.skill_edges:
            g.add_edge(
                e.from_skill,
                e.to_skill,
                key=f"{e.type}:{e.edge_id}",
                type=e.type,
                strength=e.strength,
                min_level=e.min_level,
                weight=e.weight,
                source=e.source,
                reviewed_by=e.reviewed_by,
            )
            if e.type == "RELATED_TO":
                # design §11.3: RELATED_TO is Skill <-> Skill (bidirectional).
                # Stored once in Postgres; materialized both directions here.
                g.add_edge(
                    e.to_skill,
                    e.from_skill,
                    key=f"{e.type}:{e.edge_id}:rev",
                    type=e.type,
                    weight=e.weight,
                    source=e.source,
                    reviewed_by=e.reviewed_by,
                )

        # Role -> Skill: REQUIRES
        for rr in snapshot.role_requirements:
            g.add_edge(
                rr.role_id,
                rr.skill_id,
                key=f"REQUIRES:{rr.id}",
                type="REQUIRES",
                required_level=rr.required_level,
                weight=rr.weight,
            )

        # Resource -> Skill: TARGETS
        for rs in snapshot.resource_skills:
            g.add_edge(
                rs.resource_id,
                rs.skill_id,
                key=f"TARGETS:{rs.id}",
                type="TARGETS",
                level_from=rs.level_from,
                level_to=rs.level_to,
            )

        # PracticeItem -> Skill: ASSESSES
        for it in snapshot.practice_items:
            g.add_edge(it.item_id, it.skill_id, key=f"ASSESSES:{it.item_id}", type="ASSESSES", primary=True)

        # Misconception -> Skill: MISCONCEPTION_OF, ROOTED_IN; Misconception -> Resource: REMEDIATED_BY
        for m in snapshot.misconceptions:
            g.add_edge(
                m.misconception_id, m.skill_id, key=f"MISCONCEPTION_OF:{m.misconception_id}", type="MISCONCEPTION_OF"
            )
            g.add_edge(m.misconception_id, m.root_skill_id, key=f"ROOTED_IN:{m.misconception_id}", type="ROOTED_IN")
            for rid in m.remediation_candidates:
                if rid not in g:
                    continue
                g.add_edge(
                    m.misconception_id, rid, key=f"REMEDIATED_BY:{m.misconception_id}:{rid}", type="REMEDIATED_BY"
                )

        graph_version = snapshot.graph_meta.graph_version if snapshot.graph_meta else "unknown"
        return SkillGraph(graph=g, graph_version=graph_version)
