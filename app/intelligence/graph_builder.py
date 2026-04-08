"""Graph Builder — AST-based code intelligence engine.

Parses Python source files using the ``ast`` module to extract a structured
graph of functions, classes, imports, and their relationships.  The resulting
``CodeGraph`` can be persisted to Neo4j or queried in-memory.

Node Types:
    File, Function, Class, Module, Import

Relationship Types:
    CONTAINS, CALLS, IMPORTS, DEPENDS_ON, INHERITS
"""

from __future__ import annotations

import ast
import logging
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


# ─── Enums ────────────────────────────────────────────────────────────────

class NodeType(str, Enum):
    """Types of nodes in the code graph."""
    FILE = "File"
    FUNCTION = "Function"
    CLASS = "Class"
    MODULE = "Module"
    IMPORT = "Import"


class RelationType(str, Enum):
    """Types of relationships between nodes."""
    CONTAINS = "CONTAINS"
    CALLS = "CALLS"
    IMPORTS = "IMPORTS"
    DEPENDS_ON = "DEPENDS_ON"
    INHERITS = "INHERITS"


# ─── Data Models ──────────────────────────────────────────────────────────

@dataclass(slots=True)
class GraphNode:
    """A single node in the code graph."""
    id: str
    type: NodeType
    name: str
    file_path: str
    line_start: int = 0
    line_end: int = 0
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class GraphEdge:
    """A directed relationship between two nodes."""
    source_id: str
    target_id: str
    relation: RelationType
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class CodeGraph:
    """Full code graph for a project or a single file."""
    nodes: list[GraphNode] = field(default_factory=list)
    edges: list[GraphEdge] = field(default_factory=list)

    # ── Lookup helpers ────────────────────────────────────────────────

    def get_node(self, node_id: str) -> GraphNode | None:
        """Find a node by ID."""
        for node in self.nodes:
            if node.id == node_id:
                return node
        return None

    def get_nodes_by_type(self, node_type: NodeType) -> list[GraphNode]:
        """Return all nodes of a given type."""
        return [n for n in self.nodes if n.type == node_type]

    def get_callers(self, node_id: str) -> list[GraphNode]:
        """Return all nodes that *call* the given node."""
        caller_ids = {
            e.source_id for e in self.edges
            if e.target_id == node_id and e.relation == RelationType.CALLS
        }
        return [n for n in self.nodes if n.id in caller_ids]

    def get_dependents(self, node_id: str) -> list[GraphNode]:
        """Return all nodes that *depend on* the given node (callers + importers)."""
        dep_ids: set[str] = set()
        for edge in self.edges:
            if edge.target_id == node_id and edge.relation in (
                RelationType.CALLS, RelationType.IMPORTS, RelationType.DEPENDS_ON,
            ):
                dep_ids.add(edge.source_id)
        return [n for n in self.nodes if n.id in dep_ids]

    def get_dependencies(self, node_id: str) -> list[GraphNode]:
        """Return all nodes that the given node *depends on*."""
        dep_ids: set[str] = set()
        for edge in self.edges:
            if edge.source_id == node_id and edge.relation in (
                RelationType.CALLS, RelationType.IMPORTS, RelationType.DEPENDS_ON,
            ):
                dep_ids.add(edge.target_id)
        return [n for n in self.nodes if n.id in dep_ids]

    def merge(self, other: CodeGraph) -> None:
        """Merge another graph into this one (in-place, deduplicates by ID)."""
        existing_ids = {n.id for n in self.nodes}
        for node in other.nodes:
            if node.id not in existing_ids:
                self.nodes.append(node)
                existing_ids.add(node.id)
        existing_edges = {(e.source_id, e.target_id, e.relation) for e in self.edges}
        for edge in other.edges:
            key = (edge.source_id, edge.target_id, edge.relation)
            if key not in existing_edges:
                self.edges.append(edge)
                existing_edges.add(key)

    def to_dict(self) -> dict[str, Any]:
        """Serialize the graph for JSON/API responses."""
        return {
            "nodes": [
                {
                    "id": n.id,
                    "type": n.type.value,
                    "name": n.name,
                    "file": n.file_path,
                    "line_start": n.line_start,
                    "line_end": n.line_end,
                    "metadata": n.metadata,
                }
                for n in self.nodes
            ],
            "edges": [
                {
                    "source": e.source_id,
                    "target": e.target_id,
                    "relation": e.relation.value,
                    "metadata": e.metadata,
                }
                for e in self.edges
            ],
            "stats": {
                "total_nodes": len(self.nodes),
                "total_edges": len(self.edges),
                "files": len(self.get_nodes_by_type(NodeType.FILE)),
                "functions": len(self.get_nodes_by_type(NodeType.FUNCTION)),
                "classes": len(self.get_nodes_by_type(NodeType.CLASS)),
                "imports": len(self.get_nodes_by_type(NodeType.IMPORT)),
            },
        }


# ─── AST Visitor ──────────────────────────────────────────────────────────

class _PythonASTVisitor(ast.NodeVisitor):
    """Walks a Python AST and extracts graph nodes + edges."""

    def __init__(self, file_path: str, file_node_id: str) -> None:
        self.file_path = file_path
        self.file_node_id = file_node_id
        self.nodes: list[GraphNode] = []
        self.edges: list[GraphEdge] = []
        self._scope_stack: list[str] = [file_node_id]
        self._defined_names: dict[str, str] = {}  # name → node_id

    @property
    def _current_scope(self) -> str:
        return self._scope_stack[-1]

    def _make_id(self, kind: str, name: str) -> str:
        return f"{self.file_path}::{kind}::{name}"

    # ── Functions ─────────────────────────────────────────────────────

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._handle_function(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self._handle_function(node, is_async=True)

    def _handle_function(self, node: ast.FunctionDef | ast.AsyncFunctionDef, *, is_async: bool = False) -> None:
        node_id = self._make_id("func", node.name)

        # Extract argument info
        args_info = []
        for arg in node.args.args:
            annotation = ""
            if arg.annotation:
                annotation = ast.unparse(arg.annotation)
            args_info.append({"name": arg.arg, "annotation": annotation})

        # Extract return type
        return_type = ""
        if node.returns:
            return_type = ast.unparse(node.returns)

        # Extract decorators
        decorators = [ast.unparse(d) for d in node.decorator_list]

        graph_node = GraphNode(
            id=node_id,
            type=NodeType.FUNCTION,
            name=node.name,
            file_path=self.file_path,
            line_start=node.lineno,
            line_end=node.end_lineno or node.lineno,
            metadata={
                "args": args_info,
                "return_type": return_type,
                "decorators": decorators,
                "is_async": is_async,
                "docstring": ast.get_docstring(node) or "",
            },
        )
        self.nodes.append(graph_node)
        self._defined_names[node.name] = node_id

        # CONTAINS edge from current scope
        self.edges.append(GraphEdge(
            source_id=self._current_scope,
            target_id=node_id,
            relation=RelationType.CONTAINS,
        ))

        # Walk body for calls
        self._scope_stack.append(node_id)
        self.generic_visit(node)
        self._scope_stack.pop()

    # ── Classes ───────────────────────────────────────────────────────

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        node_id = self._make_id("class", node.name)

        # Extract bases
        bases = [ast.unparse(b) for b in node.bases]

        # Extract decorators
        decorators = [ast.unparse(d) for d in node.decorator_list]

        # Extract method names
        methods = [
            item.name for item in node.body
            if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef))
        ]

        graph_node = GraphNode(
            id=node_id,
            type=NodeType.CLASS,
            name=node.name,
            file_path=self.file_path,
            line_start=node.lineno,
            line_end=node.end_lineno or node.lineno,
            metadata={
                "bases": bases,
                "decorators": decorators,
                "methods": methods,
                "docstring": ast.get_docstring(node) or "",
            },
        )
        self.nodes.append(graph_node)
        self._defined_names[node.name] = node_id

        # CONTAINS from current scope
        self.edges.append(GraphEdge(
            source_id=self._current_scope,
            target_id=node_id,
            relation=RelationType.CONTAINS,
        ))

        # INHERITS edges
        for base_name in bases:
            base_id = self._make_id("class", base_name)
            self.edges.append(GraphEdge(
                source_id=node_id,
                target_id=base_id,
                relation=RelationType.INHERITS,
                metadata={"base": base_name},
            ))

        # Walk body for methods and nested calls
        self._scope_stack.append(node_id)
        self.generic_visit(node)
        self._scope_stack.pop()

    # ── Imports ───────────────────────────────────────────────────────

    def visit_Import(self, node: ast.Import) -> None:
        for alias in node.names:
            module_name = alias.name
            node_id = self._make_id("import", module_name)

            self.nodes.append(GraphNode(
                id=node_id,
                type=NodeType.IMPORT,
                name=module_name,
                file_path=self.file_path,
                line_start=node.lineno,
                line_end=node.end_lineno or node.lineno,
                metadata={"alias": alias.asname or "", "kind": "import"},
            ))

            self.edges.append(GraphEdge(
                source_id=self.file_node_id,
                target_id=node_id,
                relation=RelationType.IMPORTS,
            ))

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        module_name = node.module or ""
        for alias in (node.names or []):
            imported_name = f"{module_name}.{alias.name}" if module_name else alias.name
            node_id = self._make_id("import", imported_name)

            self.nodes.append(GraphNode(
                id=node_id,
                type=NodeType.IMPORT,
                name=imported_name,
                file_path=self.file_path,
                line_start=node.lineno,
                line_end=node.end_lineno or node.lineno,
                metadata={
                    "from_module": module_name,
                    "imported_name": alias.name,
                    "alias": alias.asname or "",
                    "kind": "from_import",
                },
            ))

            self.edges.append(GraphEdge(
                source_id=self.file_node_id,
                target_id=node_id,
                relation=RelationType.IMPORTS,
            ))

    # ── Function Calls ────────────────────────────────────────────────

    def visit_Call(self, node: ast.Call) -> None:
        call_name = self._extract_call_name(node)
        if call_name:
            target_id = self._make_id("func", call_name)
            self.edges.append(GraphEdge(
                source_id=self._current_scope,
                target_id=target_id,
                relation=RelationType.CALLS,
                metadata={"line": node.lineno},
            ))
        self.generic_visit(node)

    @staticmethod
    def _extract_call_name(node: ast.Call) -> str | None:
        """Extract the callable name from a Call AST node."""
        if isinstance(node.func, ast.Name):
            return node.func.id
        if isinstance(node.func, ast.Attribute):
            return node.func.attr
        return None


# ─── Public API ───────────────────────────────────────────────────────────

def parse_python_file(file_path: str, source: str) -> CodeGraph:
    """Parse a single Python source file and return its code graph.

    Args:
        file_path: Relative or absolute path of the file (used as identifiers).
        source: Python source code as a string.

    Returns:
        A ``CodeGraph`` with the file's nodes and edges.

    Raises:
        SyntaxError: If the source cannot be parsed (logged and returned empty).
    """
    graph = CodeGraph()

    try:
        tree = ast.parse(source, filename=file_path)
    except SyntaxError as exc:
        logger.warning("Failed to parse %s: %s", file_path, exc)
        return graph

    # Create the File node
    file_node_id = f"file::{file_path}"
    file_node = GraphNode(
        id=file_node_id,
        type=NodeType.FILE,
        name=Path(file_path).name,
        file_path=file_path,
        line_start=1,
        line_end=source.count("\n") + 1,
        metadata={
            "total_lines": source.count("\n") + 1,
            "docstring": ast.get_docstring(tree) or "",
        },
    )
    graph.nodes.append(file_node)

    # Walk AST
    visitor = _PythonASTVisitor(file_path, file_node_id)
    visitor.visit(tree)

    graph.nodes.extend(visitor.nodes)
    graph.edges.extend(visitor.edges)

    return graph


def build_project_graph(
    files: list[dict[str, str]],
    *,
    extensions: tuple[str, ...] = (".py",),
) -> CodeGraph:
    """Build a complete code graph from a list of project files.

    Args:
        files: List of ``{"name": str, "content": str}`` file dicts.
        extensions: File extensions to parse (default: Python only).

    Returns:
        A merged ``CodeGraph`` for the entire project.
    """
    project_graph = CodeGraph()
    parsed_count = 0

    for file_info in files:
        name = file_info.get("name", "")
        content = file_info.get("content", "")

        if not any(name.endswith(ext) for ext in extensions):
            continue

        file_graph = parse_python_file(name, content)
        project_graph.merge(file_graph)
        parsed_count += 1

    # Cross-file dependency resolution: link imports to actual definitions
    _resolve_cross_file_dependencies(project_graph)

    logger.info(
        "Built project graph: %d files parsed, %d nodes, %d edges",
        parsed_count, len(project_graph.nodes), len(project_graph.edges),
    )

    return project_graph


def _resolve_cross_file_dependencies(graph: CodeGraph) -> None:
    """Link imports to actual function/class definitions across files.

    Creates DEPENDS_ON edges when an import node can be resolved to a
    concrete definition within the same project.
    """
    # Build a lookup: definition name → node id
    definitions: dict[str, str] = {}
    for node in graph.nodes:
        if node.type in (NodeType.FUNCTION, NodeType.CLASS):
            definitions[node.name] = node.id

    # For each import, try to resolve to a local definition
    for node in graph.nodes:
        if node.type != NodeType.IMPORT:
            continue

        # Try the imported name (e.g., "call_llm" from "app.services.llm_service.call_llm")
        imported_name = node.metadata.get("imported_name", "") or node.name.rsplit(".", 1)[-1]

        if imported_name in definitions:
            target_id = definitions[imported_name]
            graph.edges.append(GraphEdge(
                source_id=node.id,
                target_id=target_id,
                relation=RelationType.DEPENDS_ON,
                metadata={"resolved": True},
            ))
