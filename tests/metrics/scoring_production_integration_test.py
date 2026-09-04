"""Phase 2 canonical producer integration contracts."""

from __future__ import annotations

from decimal import Decimal
from decimal import localcontext
from hashlib import sha256
from pathlib import Path

import networkx as nx

from slop_code import common
from slop_code.evaluation import CheckpointConfig
from slop_code.evaluation import ProblemConfig
from slop_code.metrics.scoring.contract import EXPECTED_INTERPRETER
from slop_code.metrics.scoring.contract import PARSER_TOKENIZER_PROBE
from slop_code.metrics.scoring.inventory import InventoryResult
from slop_code.metrics.scoring.live_evidence import _produce_rework_evidence
from slop_code.metrics.scoring.models import FileRole
from slop_code.metrics.scoring.models import InventoryFile
from slop_code.metrics.scoring.production import PRODUCTION_GRAPH_FILENAME
from slop_code.metrics.scoring.production import PRODUCTION_QUALITY_FILENAME
from slop_code.metrics.scoring.production import produce_production_evidence
from slop_code.metrics.scoring.schema import problem_key


def _inventory(*rows: tuple[str, FileRole]) -> InventoryResult:
    return InventoryResult(
        files=tuple(InventoryFile(path=path, role=role) for path, role in rows),
        invalid_codes=(),
        unsupported_paths=(),
    )


def _quality_stubs(monkeypatch):
    from slop_code.metrics.scoring import production_quality

    def verified(_, sources):
        return {
            "interpreter": {
                "executable": "evaluator",
                "implementation": EXPECTED_INTERPRETER["implementation"],
                "version": f"{EXPECTED_INTERPRETER['version']}.0",
                "cache_tag": EXPECTED_INTERPRETER["cache_tag"],
                "executable_sha256": "0" * 64,
                "ast_sha256": "1" * 64,
                "tokenize_sha256": "2" * 64,
            },
            "parser_tokenizer_probe": PARSER_TOKENIZER_PROBE.hex(),
            "parser_tokenizer_schema_id": "0" * 64,
            "files": [
                {
                    "path": path,
                    "hash": sha256(data).hexdigest(),
                    "source_lines": [1, 2, 3, 4],
                }
                for path, data in sorted(sources.items())
            ],
            "clone_groups": [],
        }

    monkeypatch.setattr(production_quality, "_verified_payload", verified)
    monkeypatch.setattr(
        production_quality,
        "_ruff",
        lambda *_: (
            "ruff 0",
            (
                {
                    "code": "SIM102",
                    "path": "src/a.py",
                    "start": (1, 1),
                    "end": (1, 2),
                },
            ),
            ("evaluator", "-m", "ruff"),
        ),
    )


def _rows():
    return (
        ({"path": "src/a.py", "success": True},),
        (
            {
                "path": "src/a.py",
                "qualified_name": "a",
                "kind": "function",
                "start_line": 1,
                "end_line": 4,
                "cc": 11,
                "sloc": 4,
            },
            {
                "path": "src/a.py",
                "qualified_name": "b",
                "kind": "method",
                "start_line": 1,
                "end_line": 4,
                "cc": 1,
                "sloc": 4,
            },
            {
                "path": "src/a.py",
                "qualified_name": "C",
                "kind": "class",
                "start_line": 1,
                "end_line": 4,
                "cc": 1,
                "sloc": 4,
            },
            {
                "path": "tests/a_test.py",
                "qualified_name": "outside",
                "kind": "function",
                "start_line": 1,
                "end_line": 1,
                "cc": 1,
                "sloc": 1,
            },
        ),
    )


def test_canonical_producer_joins_once_and_raw_payloads_recompute(
    tmp_path, monkeypatch
):
    _quality_stubs(monkeypatch)
    root = tmp_path / "snapshot"
    (root / "src").mkdir(parents=True)
    (root / "src" / "a.py").write_text(
        "def a():\n    x = 1\n    return x\n", encoding="utf-8"
    )
    inventory = _inventory(("src/a.py", FileRole.PRODUCTION))
    file_rows, symbol_rows = _rows()
    graph = nx.DiGraph([("src/a.py::a", "src/a.py::b", {"weight": 3})])

    result = produce_production_evidence(
        "checkpoint",
        root,
        inventory,
        file_rows,
        symbol_rows,
        graph,
        Path("evaluator"),
    )

    assert result.eligibility.eligible
    assert tuple(result.payloads) == (
        PRODUCTION_QUALITY_FILENAME,
        PRODUCTION_GRAPH_FILENAME,
    )
    quality = result.production_quality
    graph_evidence = result.production_graph
    assert quality is not None and graph_evidence is not None
    assert [row.identity[1] for row in quality.eligible_symbols] == ["a", "b"]
    assert [
        (row.reason.value, row.kind, row.path)
        for row in quality.excluded_symbols
    ] == [
        ("symbol_kind_ineligible", "class", "src/a.py"),
        ("symbol_path_not_production", "function", "tests/a_test.py"),
    ]
    serialized_quality = quality.model_dump(mode="json")
    assert serialized_quality["eligible_symbols"][0]["identity"] == [
        "src/a.py",
        "a",
        "function",
        1,
        4,
    ]
    assert serialized_quality["excluded_symbols"][1]["reason"] == (
        "symbol_path_not_production"
    )
    with localcontext() as context:
        context.prec = 50
        assert quality.verbosity == Decimal(1) - (
            Decimal(quality.union_numerator)
            / Decimal(quality.source_loc_denominator)
        )
        assert quality.erosion == Decimal(1) - (
            quality.erosion_numerator / quality.erosion_denominator
        )
        assert graph_evidence.architecture == Decimal(1) - (
            graph_evidence.cyclic_mass / graph_evidence.total_mass
        )

    checkpoints = {
        checkpoint_id: CheckpointConfig(
            name=checkpoint_id, version=1, order=order
        )
        for order, checkpoint_id in enumerate(("one", "two", "three"), start=1)
    }
    problem = ProblemConfig(
        name="problem",
        path=tmp_path / "problem-config",
        version=1,
        description="fixture",
        tags=["test"],
        checkpoints=checkpoints,
        entry_file="main.py",
    )
    checkpoint_raw = {}
    for checkpoint_id, value in zip(
        checkpoints,
        (
            "def a():\n    return 1\n",
            "def a():\n    return 2\n",
            "def a():\n    return 3\n",
        ),
    ):
        snapshot = (
            tmp_path
            / problem.name
            / checkpoint_id
            / common.SNAPSHOT_DIR_NAME
            / "src"
        )
        snapshot.mkdir(parents=True)
        (snapshot / "a.py").write_text(value, encoding="utf-8")
        prefix = (
            f"problems/{problem_key(problem.name)}/checkpoints/{checkpoint_id}"
        )
        checkpoint_raw[f"{prefix}/production_quality.json"] = (
            quality.model_dump_json().encode()
        )

    rework, eligibility = _produce_rework_evidence(
        tmp_path, problem, checkpoint_raw
    )
    transition_prefix = (
        f"problems/{problem_key(problem.name)}/transitions"
    )
    assert eligibility.eligible
    assert (
        rework[f"{transition_prefix}/one--two/rework.json"]
        == b'{"rework":"1"}'
    )
    assert (
        rework[f"{transition_prefix}/two--three/rework.json"]
        == b'{"rework":"0"}'
    )

    malformed = dict(checkpoint_raw)
    malformed[
        f"problems/{problem_key(problem.name)}/checkpoints/two/"
        "production_quality.json"
    ] = b"{}"
    rework, eligibility = _produce_rework_evidence(
        tmp_path, problem, malformed
    )
    assert rework == {}
    assert eligibility.reasons == ("canonical_provenance_unavailable",)


def test_duplicate_or_missing_file_joins_are_ineligible(tmp_path, monkeypatch):
    _quality_stubs(monkeypatch)
    root = tmp_path / "snapshot"
    (root / "src").mkdir(parents=True)
    (root / "src" / "a.py").write_text("x = 1\n", encoding="utf-8")
    inventory = _inventory(("src/a.py", FileRole.PRODUCTION))

    for file_rows in ((), ({"path": "src/a.py"}, {"path": "src/a.py"})):
        result = produce_production_evidence(
            "checkpoint",
            root,
            inventory,
            file_rows,
            (),
            nx.DiGraph(),
            Path("evaluator"),
        )
        assert result.eligibility.reasons == ("score_evidence_invalid",)
        assert result.production_quality is None
        assert result.production_graph is not None


def test_unsupported_and_invalid_evidence_reasons_are_aggregated(
    tmp_path, monkeypatch
):
    _quality_stubs(monkeypatch)
    root = tmp_path / "snapshot"
    (root / "src").mkdir(parents=True)
    (root / "src" / "a.py").write_text("x = 1\n", encoding="utf-8")
    inventory = InventoryResult(
        files=(
            InventoryFile(path="src/a.py", role=FileRole.PRODUCTION),
            InventoryFile(path="src/a.js", role=FileRole.PRODUCTION),
        ),
        invalid_codes=(),
        unsupported_paths=("src/a.js",),
    )
    result = produce_production_evidence(
        "checkpoint",
        root,
        inventory,
        ({"path": "src/a.py", "success": True},),
        (
            {
                "path": "src/a.py",
                "qualified_name": "a",
                "kind": "function",
                "start_line": 1,
                "end_line": 1,
                "cc": "bad",
                "sloc": 1,
            },
        ),
        nx.DiGraph([("missing.py::a", "missing.py::a", {"weight": 1})]),
        Path("evaluator"),
    )

    assert result.eligibility.reasons == (
        "production_language_unsupported",
        "production_symbol_evidence_invalid",
        "score_evidence_invalid",
    )
    assert not result.payloads


def test_root_and_inventory_order_do_not_change_payload_order(
    tmp_path, monkeypatch
):
    _quality_stubs(monkeypatch)
    root = tmp_path / "snapshot"
    (root / "src").mkdir(parents=True)
    (root / "src" / "a.py").write_text("x = 1\n", encoding="utf-8")
    file_rows, symbol_rows = _rows()
    graph = nx.DiGraph([("src/a.py::a", "src/a.py::b", {"weight": 3})])
    first = produce_production_evidence(
        "checkpoint",
        root,
        _inventory(("src/a.py", FileRole.PRODUCTION)),
        file_rows,
        symbol_rows,
        graph,
        Path("evaluator"),
    )
    second = produce_production_evidence(
        "checkpoint",
        root / ".",
        _inventory(("src/a.py", FileRole.PRODUCTION)),
        file_rows,
        symbol_rows,
        graph,
        Path("evaluator"),
    )

    assert first.model_dump(mode="json") == second.model_dump(mode="json")
