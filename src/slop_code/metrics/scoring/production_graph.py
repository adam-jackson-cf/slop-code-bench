"""Deterministic production-only architecture evidence producer."""

from __future__ import annotations

from collections.abc import Iterable
from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal
from decimal import InvalidOperation
from decimal import localcontext
from typing import Any, TypeGuard

import networkx as nx

from slop_code.metrics.languages.python.graph import dependency_graph_traversal

from .models import FileRole
from .models import InventoryFile


class ProductionGraphError(ValueError):
    """Evidence cannot be used to compute the production architecture component."""


@dataclass(frozen=True)
class ProductionGraphResult:
    """Raw, independently recomputable production architecture evidence."""

    architecture: Decimal
    evidence: dict[str, Any]


def _is_string_mapping(row: object) -> TypeGuard[Mapping[str, object]]:
    return isinstance(row, Mapping) and all(isinstance(key, str) for key in row)


def _value(row: object, *names: str) -> object:
    mapping: Mapping[str, object] | None = None
    if isinstance(row, Mapping):
        if not _is_string_mapping(row):
            raise ProductionGraphError(
                "score_evidence_invalid: inventory mapping keys must be strings"
            )
        mapping = row
    for name in names:
        if mapping is not None and name in mapping:
            return mapping[name]
        if hasattr(row, name):
            return getattr(row, name)
    return None


def _role(value: object) -> str:
    if isinstance(value, FileRole):
        return value.value
    if isinstance(value, str) and value in {role.value for role in FileRole}:
        return value
    raise ProductionGraphError("score_evidence_invalid: invalid inventory role")


def _path(row: InventoryFile | Mapping[str, Any] | object) -> str:
    path = _value(row, "path", "file_path")
    if (
        not isinstance(path, str)
        or not path
        or path.startswith("/")
        or "\\" in path
    ):
        raise ProductionGraphError(
            "score_evidence_invalid: invalid lexical file identity"
        )
    return path


def _inventory_roles(
    inventory: Iterable[InventoryFile | Mapping[str, Any] | object],
) -> dict[str, str]:
    roles: dict[str, str] = {}
    for item in inventory:
        path = _path(item)
        if path in roles:
            raise ProductionGraphError(
                "score_evidence_invalid: duplicate inventory identity"
            )
        roles[path] = _role(_value(item, "role"))
    return roles


def _weight(value: object) -> Decimal:
    if isinstance(value, bool) or not isinstance(value, int | Decimal):
        raise ProductionGraphError(
            "score_evidence_invalid: malformed graph edge weight"
        )
    try:
        result = Decimal(value)
    except (InvalidOperation, ValueError) as error:
        raise ProductionGraphError(
            "score_evidence_invalid: malformed graph edge weight"
        ) from error
    if not result.is_finite() or result < 0:
        raise ProductionGraphError(
            "score_evidence_invalid: invalid graph edge weight"
        )
    return result


def _edge_key(edge: Mapping[str, Any]) -> tuple[bytes, bytes]:
    return edge["source"].encode("utf-8"), edge["target"].encode("utf-8")


def produce_production_graph(
    checkpoint_id: str,
    inventory: Iterable[InventoryFile | Mapping[str, Any] | object],
    graph: nx.DiGraph,
) -> ProductionGraphResult:
    """Join canonical inventory roles to a Python call graph and compute H.

    Every graph node must reconcile to one inventory identity.  Edges that cross
    role boundaries remain in evidence but are excluded from the production-only
    graph and component calculation.
    """

    if not checkpoint_id:
        raise ProductionGraphError(
            "score_evidence_invalid: checkpoint identity missing"
        )
    roles = _inventory_roles(inventory)
    traversal_nodes, traversal_edges = dependency_graph_traversal(graph)
    node_paths: dict[str, str] = {}
    for node in traversal_nodes:
        if "::" not in node.identity or not node.path or node.path not in roles:
            raise ProductionGraphError(
                "score_evidence_invalid: graph node reconciliation failed"
            )
        node_paths[node.identity] = node.path

    production_nodes = tuple(
        {"identity": node.identity, "path": node.path}
        for node in traversal_nodes
        if roles[node.path] == FileRole.PRODUCTION.value
    )
    production_node_ids = {node["identity"] for node in production_nodes}
    all_edges: list[dict[str, Any]] = []
    cross_role_edges: list[dict[str, Any]] = []
    internal_graph = nx.DiGraph()
    internal_graph.add_nodes_from(production_node_ids)
    for edge in traversal_edges:
        source_path = node_paths.get(edge.source)
        target_path = node_paths.get(edge.target)
        if source_path is None or target_path is None:
            raise ProductionGraphError(
                "score_evidence_invalid: graph edge reconciliation failed"
            )
        weight = _weight(edge.weight)
        source_role = roles[source_path]
        target_role = roles[target_path]
        record = {
            "source": edge.source,
            "target": edge.target,
            "weight": str(weight),
            "source_role": source_role,
            "target_role": target_role,
            "cyclic": False,
            "self_loop": edge.source == edge.target,
        }
        if source_role == target_role == FileRole.PRODUCTION.value:
            internal_graph.add_edge(edge.source, edge.target, weight=weight)
            all_edges.append(record)
        elif source_role != target_role:
            cross_role_edges.append(record)

    membership: dict[str, tuple[str, ...]] = {}
    sccs: list[dict[str, Any]] = []
    for members in nx.strongly_connected_components(internal_graph):
        ordered = tuple(
            sorted(members, key=lambda value: value.encode("utf-8"))
        )
        for member in ordered:
            membership[member] = ordered
        singleton = len(ordered) == 1
        self_loop = singleton and internal_graph.has_edge(
            ordered[0], ordered[0]
        )
        cyclic = len(ordered) > 1 or self_loop
        mass = sum(
            (
                data["weight"]
                for source, target, data in internal_graph.edges(data=True)
                if source in members and target in members
            ),
            Decimal(0),
        )
        sccs.append(
            {
                "members": ordered,
                "mass": str(mass),
                "cyclic": cyclic,
                "self_loop": self_loop,
            }
        )

    for edge in all_edges:
        source_members = membership[edge["source"]]
        edge["cyclic"] = source_members == membership[edge["target"]] and (
            len(source_members) > 1 or edge["self_loop"]
        )
    all_edges.sort(key=_edge_key)
    cross_role_edges.sort(key=_edge_key)
    sccs.sort(
        key=lambda item: tuple(
            member.encode("utf-8") for member in item["members"]
        )
    )
    total_mass = sum(
        (Decimal(edge["weight"]) for edge in all_edges), Decimal(0)
    )
    cyclic_mass = sum(
        (Decimal(edge["weight"]) for edge in all_edges if edge["cyclic"]),
        Decimal(0),
    )
    if cyclic_mass > total_mass:
        raise ProductionGraphError(
            "score_evidence_invalid: cyclic graph mass exceeds total"
        )
    with localcontext() as context:
        context.prec = 50
        architecture = (
            Decimal(1)
            if total_mass == 0
            else Decimal(1) - cyclic_mass / total_mass
        )
    evidence = {
        "checkpoint_id": checkpoint_id,
        "nodes": production_nodes,
        "edges": tuple(all_edges),
        "cross_role_edges": tuple(cross_role_edges),
        "sccs": tuple(sccs),
        "cyclic_mass": str(cyclic_mass),
        "total_mass": str(total_mass),
        "architecture": str(architecture),
    }
    return ProductionGraphResult(architecture=architecture, evidence=evidence)
