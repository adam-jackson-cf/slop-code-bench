"""Production-only graph evidence contract tests."""

from __future__ import annotations

from decimal import Decimal

import networkx as nx
import pytest

from slop_code.metrics.scoring.models import ProductionGraphEvidence
from slop_code.metrics.scoring.production_graph import ProductionGraphError
from slop_code.metrics.scoring.production_graph import produce_production_graph


def _inventory(*rows: tuple[str, str]) -> list[dict[str, str]]:
    return [{"path": path, "role": role} for path, role in rows]


def test_weighted_cycle_evidence_recomputes_architecture():
    graph = nx.DiGraph()
    graph.add_edge("src/a.py::a", "src/b.py::b", weight=2)
    graph.add_edge("src/b.py::b", "src/a.py::a", weight=3)
    graph.add_edge("src/b.py::b", "src/c.py::c", weight=5)

    result = produce_production_graph(
        "checkpoint",
        _inventory(
            ("src/a.py", "production"),
            ("src/b.py", "production"),
            ("src/c.py", "production"),
        ),
        graph,
    )

    assert result.architecture == Decimal("0.5")
    assert result.evidence["total_mass"] == "10"
    assert result.evidence["cyclic_mass"] == "5"
    assert [
        edge["weight"] for edge in result.evidence["edges"] if edge["cyclic"]
    ] == ["2", "3"]
    typed = ProductionGraphEvidence.model_validate(result.evidence)
    assert typed.cyclic_mass == Decimal("5")


def test_singleton_self_loop_is_cyclic_production_mass():
    graph = nx.DiGraph()
    graph.add_edge("src/a.py::a", "src/a.py::a", weight=4)

    result = produce_production_graph(
        "checkpoint", _inventory(("src/a.py", "production")), graph
    )

    assert result.architecture == Decimal("0")
    assert result.evidence["sccs"] == (
        {
            "members": ("src/a.py::a",),
            "mass": "4",
            "cyclic": True,
            "self_loop": True,
        },
    )


def test_cross_role_edges_are_retained_but_not_scored():
    graph = nx.DiGraph()
    graph.add_edge("src/a.py::a", "tests/t.py::t", weight=7)
    graph.add_edge("tests/t.py::t", "src/a.py::a", weight=11)

    result = produce_production_graph(
        "checkpoint",
        _inventory(("src/a.py", "production"), ("tests/t.py", "test")),
        graph,
    )

    assert result.architecture == Decimal("1")
    assert result.evidence["edges"] == ()
    assert [
        (edge["source_role"], edge["target_role"], edge["weight"])
        for edge in result.evidence["cross_role_edges"]
    ] == [
        ("production", "test", "7"),
        ("test", "production", "11"),
    ]


def test_empty_graph_and_ordering_are_deterministic():
    empty = produce_production_graph(
        "checkpoint", _inventory(("src/a.py", "production")), nx.DiGraph()
    )
    assert empty.architecture == Decimal("1")
    assert empty.evidence["nodes"] == ()

    graph = nx.DiGraph()
    graph.add_edge("z.py::z", "a.py::a", weight=1)
    ordered = produce_production_graph(
        "checkpoint",
        _inventory(("z.py", "production"), ("a.py", "production")),
        graph,
    )
    assert [node["identity"] for node in ordered.evidence["nodes"]] == [
        "a.py::a",
        "z.py::z",
    ]


@pytest.mark.parametrize(
    ("inventory", "graph", "message"),
    [
        (
            _inventory(("src/a.py", "production"), ("src/a.py", "test")),
            nx.DiGraph(),
            "duplicate inventory",
        ),
        (
            _inventory(("src/a.py", "production")),
            nx.DiGraph(
                [("src/missing.py::x", "src/missing.py::x", {"weight": 1})]
            ),
            "reconciliation",
        ),
        (
            _inventory(("src/a.py", "production")),
            nx.DiGraph([("src/a.py::a", "src/a.py::a", {"weight": -1})]),
            "invalid graph edge weight",
        ),
        (
            _inventory(("src/a.py", "production")),
            nx.DiGraph([("src/a.py::a", "src/a.py::a", {"weight": 1.5})]),
            "malformed graph edge weight",
        ),
    ],
)
def test_duplicate_reconciliation_and_malformed_weights_are_rejected(
    inventory, graph, message
):
    with pytest.raises(ProductionGraphError, match=message):
        produce_production_graph("checkpoint", inventory, graph)


def test_inventory_mapping_with_non_string_key_is_rejected():
    inventory = [{"path": "src/a.py", "role": "production", 1: "invalid"}]

    with pytest.raises(
        ProductionGraphError, match="inventory mapping keys must be strings"
    ):
        produce_production_graph("checkpoint", inventory, nx.DiGraph())
