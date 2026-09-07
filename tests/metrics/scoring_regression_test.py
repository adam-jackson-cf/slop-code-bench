"""Controlled regression-breadth evidence scenarios."""

import json
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

import pytest

from slop_code import common
from slop_code.evaluation import CheckpointConfig
from slop_code.evaluation import GroupType
from slop_code.evaluation import ProblemConfig
from slop_code.evaluation import TestResult as EvaluationTestResult
from slop_code.metrics.scoring import CorpusEvidence
from slop_code.metrics.scoring import CoverageContextEvidence
from slop_code.metrics.scoring import Eligibility
from slop_code.metrics.scoring import EvaluatorEnvironmentEvidence
from slop_code.metrics.scoring import LineageCandidate
from slop_code.metrics.scoring import ProcessAuditEvent
from slop_code.metrics.scoring import RegressionBreadthInput
from slop_code.metrics.scoring import RegressionInvocationEvidence
from slop_code.metrics.scoring import RegressionLedgerEvidence
from slop_code.metrics.scoring import RegressionOutcome
from slop_code.metrics.scoring import RegressionOutcomeEvidence
from slop_code.metrics.scoring import RegressionPhase
from slop_code.metrics.scoring import RegressionRunEvidence
from slop_code.metrics.scoring import SymbolIdentity
from slop_code.metrics.scoring import calculate_regression_breadth
from slop_code.metrics.scoring.live_regression import (
    _accepted_changed_current_symbols,
)
from slop_code.metrics.scoring.live_regression import (
    _changed_production_symbols,
)
from slop_code.metrics.scoring.live_regression import _run_evidence
from slop_code.metrics.scoring.live_regression import (
    produce_live_regression_evidence,
)

HASH = "a" * 64


def test_accepted_changed_lineage_endpoints_extend_regression_symbol_scope() -> (
    None
):
    prior = SymbolIdentity(
        path="src/old.py",
        qualified_name="f",
        kind="function",
        start_line=1,
        end_line=3,
    )
    current = prior.model_copy(update={"path": "src/new.py"})
    rejected = LineageCandidate(
        prior=prior,
        current=current.model_copy(update={"qualified_name": "rejected"}),
        body_hash_equal=False,
        structure_hash_equal=True,
        signature_hash_equal=True,
        accepted=False,
        match="none",
        ambiguous_set_id="ambiguous",
    )
    accepted = LineageCandidate(
        prior=prior,
        current=current,
        body_hash_equal=True,
        structure_hash_equal=True,
        signature_hash_equal=True,
        accepted=True,
        ambiguous_set_id=None,
        match="hash",
    )
    path = "problems/key/transitions/one--two/lineage.json"
    sidecars = {
        path: json.dumps(
            {
                "lineage_candidates": [
                    rejected.model_dump(mode="json"),
                    accepted.model_dump(mode="json"),
                ]
            }
        ).encode()
    }

    assert _accepted_changed_current_symbols(sidecars, path) == (current,)


def _run(
    *,
    environment: str = HASH,
    project: str = HASH,
    lock: str = HASH,
    plugin: str = HASH,
    platform_sha256: str = HASH,
    corpus: str = HASH,
    manifest: str = HASH,
    argv: tuple[str, ...] = ("pytest", "-q"),
    cwd: str = ".",
    node_id: str = "test.py::test_case[param]",
    phase: RegressionPhase = RegressionPhase.CALL,
    outcome: RegressionOutcome = RegressionOutcome.FAILED,
    ledger_outcome: RegressionOutcome | None = None,
    event: bool = False,
) -> RegressionRunEvidence:
    return RegressionRunEvidence(
        environment=EvaluatorEnvironmentEvidence(
            environment_id=environment,
            project_sha256=project,
            lock_sha256=lock,
            platform_sha256=platform_sha256,
            plugin_sha256=plugin,
            interpreter_sha256=HASH,
        ),
        corpus=CorpusEvidence(corpus_id=corpus, manifest_sha256=manifest),
        invocation=RegressionInvocationEvidence(argv=argv, cwd=cwd),
        outcomes=(
            RegressionOutcomeEvidence(
                node_id=node_id,
                group_type="Regression",
                phase=phase,
                outcome=outcome,
            ),
        ),
        ledger=(
            RegressionLedgerEvidence(
                node_id=node_id,
                phase=phase,
                outcome=ledger_outcome or outcome,
            ),
        ),
        coverage=(
            CoverageContextEvidence(
                node_id=node_id,
                path="src/app.py",
                executed_lines=(11, 12),
            ),
        ),
        process_events=(
            ProcessAuditEvent(
                node_id=node_id,
                phase=phase,
                event="subprocess.Popen",
            ),
        )
        if event
        else (),
    )


def _measurement_results(
    tests: list[EvaluationTestResult], node_ids: tuple[str, ...]
) -> SimpleNamespace:
    return SimpleNamespace(
        evaluator_environment={
            "environment_id": HASH,
            "input_sha256": {
                "pyproject.toml": HASH,
                "uv.lock": HASH,
                "coverage_plugin.py": HASH,
                "interpreter": HASH,
            },
        },
        coverage_ledger={
            "invalid_coverage_paths": 0,
            "ledger": [
                {"node_id": node, "phase": "call", "outcome": "failed"}
                for node in node_ids
            ],
            "coverage": [
                {"node_id": node, "path": "src/app.py", "executed_line": 11}
                for node in node_ids
            ],
            "process_events": [],
        },
        test_corpus={"manifest_sha256": HASH},
        invocation={"command": "pytest -q", "cwd": "."},
        environment_fingerprint=HASH,
        tests=tests,
    )


def _test_result(
    test_id: str,
    file_path: str,
    group_type: GroupType = GroupType.REGRESSION,
) -> EvaluationTestResult:
    return EvaluationTestResult(
        id=test_id,
        checkpoint="checkpoint_2",
        group_type=group_type,
        status="failed",
        duration_ms=1,
        file_path=file_path,
    )


@pytest.mark.parametrize(
    ("test_id", "file_path", "node_id"),
    [
        (
            "test_regression",
            "unmatched.py",
            ".evaluation_tests/test_checkpoint_2.py::test_regression",
        ),
        (
            "TestRegression::test_regression",
            "unmatched.py",
            ".evaluation_tests/test_checkpoint_2.py"
            "::TestRegression::test_regression",
        ),
        (
            ".evaluation_tests/test_checkpoint_2.py::test_regression",
            "unmatched.py",
            ".evaluation_tests/test_checkpoint_2.py::test_regression",
        ),
    ],
)
def test_run_evidence_maps_report_test_id_to_canonical_regression_node(
    test_id: str, file_path: str, node_id: str
):
    results = _measurement_results(
        [_test_result(test_id, file_path)],
        (node_id,),
    )

    evidence = _run_evidence(results, platform_identity={"system": "container"})

    assert evidence is not None
    assert [(row.node_id, row.group_type) for row in evidence.outcomes] == [
        (node_id, "Regression")
    ]
    assert [row.node_id for row in evidence.coverage] == [node_id]


def test_run_evidence_uses_file_path_to_resolve_duplicate_short_ids():
    node_ids = (
        ".evaluation_tests/a.py::test_same",
        ".evaluation_tests/b.py::test_same",
    )
    results = _measurement_results(
        [
            _test_result("test_same", ".evaluation_tests/a.py"),
            _test_result("test_same", ".evaluation_tests/b.py"),
        ],
        node_ids,
    )

    evidence = _run_evidence(results, platform_identity={"system": "container"})

    assert evidence is not None
    assert [row.node_id for row in evidence.outcomes] == list(node_ids)
    assert [row.node_id for row in evidence.coverage] == list(node_ids)


@pytest.mark.parametrize(
    ("tests", "node_ids"),
    [
        (
            [
                _test_result("test_missing", ".evaluation_tests/test.py"),
            ],
            (".evaluation_tests/test.py::test_other",),
        ),
        (
            [
                _test_result("test_same", "unmatched.py"),
            ],
            ("a.py::test_same", "b.py::test_same"),
        ),
        (
            [
                _test_result(
                    "test_same",
                    ".evaluation_tests/test.py",
                    GroupType.REGRESSION,
                ),
                _test_result(
                    "test_same",
                    ".evaluation_tests/test.py",
                    GroupType.CORE,
                ),
            ],
            (".evaluation_tests/test.py::test_same",),
        ),
    ],
)
def test_run_evidence_rejects_unresolved_ambiguous_or_conflicting_groups(
    tests: list[EvaluationTestResult], node_ids: tuple[str, ...]
):
    assert (
        _run_evidence(
            _measurement_results(tests, node_ids),
            platform_identity={"system": "container"},
        )
        is None
    )


def test_live_regression_producer_unions_persisted_accepted_lineage(
    tmp_path, monkeypatch
) -> None:
    checkpoints = {
        name: CheckpointConfig(name=name, version=1, order=order)
        for order, name in enumerate(("one", "two"), start=1)
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
    for checkpoint_id in checkpoints:
        checkpoint_dir = tmp_path / problem.name / checkpoint_id
        (checkpoint_dir / common.SNAPSHOT_DIR_NAME).mkdir(parents=True)
        (checkpoint_dir / common.SNAPSHOT_DIR_NAME / "src.py").write_text(
            "def f():\n    return 1\n"
        )
        (checkpoint_dir / common.INFERENCE_RESULT_FILENAME).write_text("{}")
    prior = SymbolIdentity(
        path="src.py",
        qualified_name="old",
        kind="function",
        start_line=1,
        end_line=2,
    )
    current = prior.model_copy(
        update={"qualified_name": "new", "path": "renamed.py"}
    )
    accepted = LineageCandidate(
        prior=prior,
        current=current,
        body_hash_equal=True,
        structure_hash_equal=True,
        signature_hash_equal=True,
        accepted=True,
        ambiguous_set_id=None,
        match="hash",
    )
    key = "47a49356720831b66f38bbe12c06e6cf71a67277b1f5e6a28593e73afde6f226"
    lineage_path = f"problems/{key}/transitions/one--two/lineage.json"
    lineage = {
        lineage_path: json.dumps(
            {"lineage_candidates": [accepted.model_dump(mode="json")]}
        ).encode()
    }
    canonical_platform = {"system": "container"}
    measurement_platform = {"system": "container"}
    canonical_result = object()
    measurement_result = SimpleNamespace(platform_identity=measurement_platform)
    monkeypatch.setattr(
        "slop_code.metrics.scoring.live_regression._validate_live_oracle",
        lambda *_args: {"platform": canonical_platform},
    )
    monkeypatch.setattr(
        "slop_code.metrics.scoring.live_regression.resolve_environment",
        lambda *_args: object(),
    )
    monkeypatch.setattr(
        "slop_code.metrics.scoring.live_regression.CorrectnessResults.from_dir",
        lambda *_args: canonical_result,
    )
    monkeypatch.setattr(
        "slop_code.metrics.scoring.live_regression.run_checkpoint_pytest",
        lambda *_args, **_kwargs: measurement_result,
    )
    projected: list[tuple[object, dict[str, str]]] = []

    def project_run(
        result: object, *, platform_identity: dict[str, str]
    ) -> RegressionRunEvidence:
        projected.append((result, platform_identity))
        return _run()

    monkeypatch.setattr(
        "slop_code.metrics.scoring.live_regression._run_evidence",
        project_run,
    )
    monkeypatch.setattr(
        "slop_code.metrics.scoring.live_regression._changed_production_symbols",
        lambda *_args, **_kwargs: (),
    )

    sidecars, eligibility = produce_live_regression_evidence(
        tmp_path,
        (problem,),
        {("problem", "one", "two")},
        lineage_sidecars=lineage,
    )

    attribution = json.loads(
        sidecars[
            f"problems/{key}/transitions/one--two/regression_attribution.json"
        ]
    )
    assert eligibility == Eligibility(eligible=True)
    assert attribution["input"]["changed_symbols"] == [
        current.model_dump(mode="json")
    ]
    assert json.loads(
        sidecars[f"problems/{key}/transitions/one--two/regression.json"]
    ) == {"regression": "1.000000000000"}
    assert projected == [
        (canonical_result, canonical_platform),
        (measurement_result, measurement_platform),
    ]


def _input(
    produced: RegressionRunEvidence | None = None,
) -> RegressionBreadthInput:
    return RegressionBreadthInput(
        transition_id="c1-c2",
        baseline=_run(),
        produced=produced or _run(),
        changed_symbols=(
            SymbolIdentity(
                path="src/app.py",
                qualified_name="outer",
                kind="function",
                start_line=1,
                end_line=20,
            ),
            SymbolIdentity(
                path="src/app.py",
                qualified_name="outer.inner",
                kind="function",
                start_line=10,
                end_line=15,
            ),
            SymbolIdentity(
                path="src/app.py",
                qualified_name="other",
                kind="function",
                start_line=30,
                end_line=40,
            ),
        ),
    )


def _assert_ineligible(evidence: RegressionBreadthInput) -> None:
    result = calculate_regression_breadth(evidence)
    assert result.regression is None
    assert result.eligibility.reasons == ("coverage_parity_unavailable",)


def test_attributes_failing_parametrized_node_to_innermost_changed_symbol():
    result = calculate_regression_breadth(_input())
    assert result.eligibility.eligible
    assert result.regression == Decimal("0.666666666667")
    assert {item.node_id for item in result.attributions} == {
        "test.py::test_case[param]"
    }
    assert {item.symbol.qualified_name for item in result.attributions} == {
        "outer.inner"
    }


def test_no_changed_symbols_scores_one():
    evidence = _input()
    result = calculate_regression_breadth(
        evidence.model_copy(update={"changed_symbols": ()})
    )
    assert result.eligibility.eligible
    assert result.regression == Decimal("1.000000000000")


def test_all_affected_changed_symbols_score_zero():
    evidence = _input()
    result = calculate_regression_breadth(
        evidence.model_copy(
            update={"changed_symbols": (evidence.changed_symbols[1],)}
        )
    )
    assert result.eligibility.eligible
    assert result.regression == Decimal("0E-12")


def _checkpoint(
    root: Path, source: str, symbols: list[dict[str, object]]
) -> Path:
    checkpoint = root
    (checkpoint / common.SNAPSHOT_DIR_NAME / "src").mkdir(parents=True)
    (checkpoint / common.SNAPSHOT_DIR_NAME / "src" / "app.py").write_text(
        source
    )
    quality = checkpoint / common.QUALITY_DIR
    quality.mkdir()
    (quality / common.SYMBOLS_QUALITY_SAVENAME).write_text(
        "\n".join(json.dumps(symbol) for symbol in symbols)
    )
    return checkpoint


def test_snapshot_diff_uses_deduplicated_innermost_current_production_symbols(
    tmp_path: Path,
):
    prior = _checkpoint(
        tmp_path / "prior",
        "def outer():\n    def inner():\n        return 1\n    return inner()\n"
        "\ndef other():\n    return 2\n",
        [],
    )
    symbols = [
        {
            "file_path": "src/app.py",
            "name": "outer",
            "type": "function",
            "start": 1,
            "end": 4,
        },
        {
            "file_path": "src/app.py",
            "name": "outer.inner",
            "type": "function",
            "start": 2,
            "end": 3,
            "body_hash": "b" * 64,
        },
        {
            "file_path": "src/app.py",
            "name": "outer.inner",
            "type": "function",
            "start": 2,
            "end": 3,
            "body_hash": "b" * 64,
        },
        {
            "file_path": "src/app.py",
            "name": "other",
            "type": "function",
            "start": 6,
            "end": 7,
        },
    ]
    current = _checkpoint(
        tmp_path / "current",
        "def outer():\n    def inner():\n        return 2\n    return inner()\n"
        "\ndef other():\n    return 3\n",
        symbols,
    )

    changed = _changed_production_symbols(prior, current)

    assert [(item.qualified_name, item.body_sha256) for item in changed] == [
        ("other", ""),
        ("outer.inner", "b" * 64),
    ]
    coverage = CoverageContextEvidence(
        node_id="test.py::test_case[param]",
        path="src/app.py",
        executed_lines=(3,),
    )
    result = calculate_regression_breadth(
        _input().model_copy(
            update={
                "produced": _run().model_copy(update={"coverage": (coverage,)}),
                "changed_symbols": changed,
            }
        )
    )
    assert result.regression == Decimal("0.500000000000")
    assert [item.symbol.qualified_name for item in result.attributions] == [
        "outer.inner"
    ]


def test_snapshot_diff_with_no_changes_retains_empty_symbol_semantics(
    tmp_path: Path,
):
    source = "def stable():\n    return 1\n"
    symbols = [
        {
            "file_path": "src/app.py",
            "name": "stable",
            "type": "function",
            "start": 1,
            "end": 2,
        }
    ]
    prior = _checkpoint(tmp_path / "prior", source, symbols)
    current = _checkpoint(tmp_path / "current", source, symbols)

    assert _changed_production_symbols(prior, current) == ()


def test_process_event_on_covered_failing_regression_is_attributable():
    covered_run = _run(event=True)
    result = calculate_regression_breadth(
        _input(covered_run).model_copy(update={"baseline": covered_run})
    )

    assert result.eligibility.eligible
    assert result.regression == Decimal("0.666666666667")
    assert {item.symbol.qualified_name for item in result.attributions} == {
        "outer.inner"
    }


def test_process_event_without_failing_regression_coverage_is_ineligible():
    uncovered_run = _run(event=True).model_copy(update={"coverage": ()})
    _assert_ineligible(
        _input(uncovered_run).model_copy(update={"baseline": uncovered_run})
    )


def test_collection_process_event_is_ineligible():
    collection_run = _run(phase=RegressionPhase.COLLECTION, event=True)
    _assert_ineligible(
        _input(collection_run).model_copy(update={"baseline": collection_run})
    )


def test_process_event_on_passing_regression_is_neutral():
    passing = _run(
        outcome=RegressionOutcome.PASSED,
        event=True,
    )
    result = calculate_regression_breadth(
        _input(passing).model_copy(update={"baseline": passing})
    )

    assert result.eligibility.eligible
    assert result.regression == Decimal("1")


def test_process_event_on_failing_non_regression_is_neutral():
    run = _run(event=True)
    outcomes = (run.outcomes[0].model_copy(update={"group_type": "Core"}),)
    neutral = run.model_copy(update={"outcomes": outcomes})
    result = calculate_regression_breadth(
        _input(neutral).model_copy(update={"baseline": neutral})
    )

    assert result.eligibility.eligible
    assert result.regression == Decimal("1")


@pytest.mark.parametrize(
    "produced",
    (
        _run(environment="b" * 64),
        _run(project="b" * 64),
        _run(lock="b" * 64),
        _run(plugin="b" * 64),
        _run(corpus="b" * 64),
        _run(platform_sha256="b" * 64),
        _run(manifest="b" * 64),
        _run(argv=("pytest", "-x")),
        _run(cwd="subproject"),
        _run(node_id="test.py::test_case[other]"),
        _run(phase=RegressionPhase.SETUP),
        _run(outcome=RegressionOutcome.PASSED),
        _run(ledger_outcome=RegressionOutcome.PASSED),
        _run(event=True),
    ),
)
def test_exact_parity_mismatches_are_ineligible(
    produced: RegressionRunEvidence,
):
    _assert_ineligible(_input(produced))
