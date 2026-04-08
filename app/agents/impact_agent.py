"""Impact Agent — Graph-based dependency traversal and blast radius calculation.

Determines what breaks if a proposed change is applied by traversing the
code graph to find all callers, dependents, and transitive consumers of
the modified code.  High-impact changes are flagged for human review.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from app.intelligence.graph_builder import CodeGraph, GraphNode, NodeType, RelationType

logger = logging.getLogger(__name__)


# ─── Configuration ────────────────────────────────────────────────────────

# Blast radius thresholds
BLAST_RADIUS_LOW = 3       # <= 3 dependents
BLAST_RADIUS_MEDIUM = 8    # <= 8 dependents
BLAST_RADIUS_HIGH = 15     # <= 15 dependents
# Above HIGH = CRITICAL


# ─── Data Models ──────────────────────────────────────────────────────────

@dataclass(slots=True)
class AffectedNode:
    """A node that would be affected by a proposed change."""
    id: str
    name: str
    type: str
    file: str
    distance: int       # hops from the modified node
    relationship: str   # how it's related (CALLS, IMPORTS, DEPENDS_ON)


@dataclass(slots=True)
class ImpactResult:
    """Complete impact analysis for a proposed change."""
    target_file: str
    target_functions: list[str]
    blast_radius: int                          # total affected nodes
    blast_level: str                           # LOW / MEDIUM / HIGH / CRITICAL
    affected_nodes: list[AffectedNode] = field(default_factory=list)
    affected_files: list[str] = field(default_factory=list)
    requires_human_review: bool = False
    reasoning: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "target_file": self.target_file,
            "target_functions": self.target_functions,
            "blast_radius": self.blast_radius,
            "blast_level": self.blast_level,
            "affected_files": self.affected_files,
            "affected_node_count": len(self.affected_nodes),
            "requires_human_review": self.requires_human_review,
            "reasoning": self.reasoning,
            "affected_nodes": [
                {
                    "id": n.id,
                    "name": n.name,
                    "type": n.type,
                    "file": n.file,
                    "distance": n.distance,
                    "relationship": n.relationship,
                }
                for n in self.affected_nodes[:50]  # Cap for API response size
            ],
        }


# ─── Impact Agent ─────────────────────────────────────────────────────────

class ImpactAgent:
    """Analyzes the blast radius of proposed code changes using the graph.

    Given a file path and optionally a set of modified functions,
    traverses the code graph to find all transitive dependents and
    quantifies the blast radius.
    """

    def __init__(self, graph: CodeGraph) -> None:
        self.graph = graph

    def analyze(
        self,
        file_path: str,
        modified_functions: list[str] | None = None,
    ) -> ImpactResult:
        """Compute the blast radius for changes to a file.

        Args:
            file_path: The file being modified.
            modified_functions: Specific functions being changed.
                If None, all functions in the file are considered affected.

        Returns:
            ImpactResult with blast radius score and affected node list.
        """
        # Find nodes in the target file
        file_nodes = [
            n for n in self.graph.nodes
            if n.file_path == file_path
            and n.type in (NodeType.FUNCTION, NodeType.CLASS)
        ]

        if modified_functions:
            file_nodes = [n for n in file_nodes if n.name in modified_functions]

        if not file_nodes:
            return ImpactResult(
                target_file=file_path,
                target_functions=modified_functions or [],
                blast_radius=0,
                blast_level="LOW",
                reasoning="No parseable definitions found in target file.",
            )

        # BFS to find all transitive dependents
        affected = self._bfs_dependents(file_nodes)

        # Deduplicate affected files
        affected_files = sorted({n.file for n in affected if n.file != file_path})

        # Classify blast radius
        blast_radius = len(affected)
        blast_level = self._classify_blast_radius(blast_radius)
        requires_review = blast_level in ("HIGH", "CRITICAL")

        # Build reasoning
        func_names = [n.name for n in file_nodes]
        if requires_review:
            reasoning = (
                f"Modifying {', '.join(func_names)} in {file_path} affects "
                f"{blast_radius} dependent node(s) across {len(affected_files)} file(s). "
                f"Blast level: {blast_level} — HUMAN REVIEW REQUIRED."
            )
        else:
            reasoning = (
                f"Modifying {', '.join(func_names)} in {file_path} affects "
                f"{blast_radius} dependent node(s). Blast level: {blast_level}."
            )

        result = ImpactResult(
            target_file=file_path,
            target_functions=func_names,
            blast_radius=blast_radius,
            blast_level=blast_level,
            affected_nodes=affected,
            affected_files=affected_files,
            requires_human_review=requires_review,
            reasoning=reasoning,
        )

        logger.info(
            "Impact analysis for %s: blast_radius=%d, level=%s, review=%s",
            file_path, blast_radius, blast_level, requires_review,
        )

        return result

    def _bfs_dependents(self, seed_nodes: list[GraphNode]) -> list[AffectedNode]:
        """Breadth-first traversal to find all transitive dependents.

        Follows CALLS, IMPORTS, and DEPENDS_ON edges in reverse direction.
        """
        visited: set[str] = {n.id for n in seed_nodes}
        queue: list[tuple[str, int]] = [(n.id, 0) for n in seed_nodes]
        affected: list[AffectedNode] = []

        # Build reverse adjacency for efficient lookup
        reverse_adj: dict[str, list[tuple[str, str]]] = {}
        for edge in self.graph.edges:
            if edge.relation in (
                RelationType.CALLS, RelationType.IMPORTS, RelationType.DEPENDS_ON,
            ):
                reverse_adj.setdefault(edge.target_id, []).append(
                    (edge.source_id, edge.relation.value),
                )

        while queue:
            current_id, distance = queue.pop(0)

            for neighbor_id, relationship in reverse_adj.get(current_id, []):
                if neighbor_id in visited:
                    continue
                visited.add(neighbor_id)

                node = self.graph.get_node(neighbor_id)
                if node:
                    affected.append(AffectedNode(
                        id=node.id,
                        name=node.name,
                        type=node.type.value,
                        file=node.file_path,
                        distance=distance + 1,
                        relationship=relationship,
                    ))
                    queue.append((neighbor_id, distance + 1))

        # Sort by distance (closest first)
        affected.sort(key=lambda n: n.distance)
        return affected

    @staticmethod
    def _classify_blast_radius(count: int) -> str:
        """Classify the blast radius into severity tiers."""
        if count <= BLAST_RADIUS_LOW:
            return "LOW"
        if count <= BLAST_RADIUS_MEDIUM:
            return "MEDIUM"
        if count <= BLAST_RADIUS_HIGH:
            return "HIGH"
        return "CRITICAL"
