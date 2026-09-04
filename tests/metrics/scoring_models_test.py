import json
from copy import deepcopy
from decimal import Decimal
from pathlib import Path

import pytest
from pydantic import ValidationError

import slop_code.metrics.scoring.schema as scoring_schema
from slop_code.metrics.scoring import BENCHMARK_SCORE_FILENAME
from slop_code.metrics.scoring import CHECKPOINT_REPORT_ADDITIONS_FILENAME
from slop_code.metrics.scoring import CURRENT_POINTER_FILENAME
from slop_code.metrics.scoring import ELIGIBILITY_FILENAME
from slop_code.metrics.scoring import EVALUATOR_ENVIRONMENTS_DIR
from slop_code.metrics.scoring import EVALUATOR_LOCK_FILENAME
from slop_code.metrics.scoring import EVALUATOR_READY_FILENAME
from slop_code.metrics.scoring import EVIDENCE_INDEX_FILENAME
from slop_code.metrics.scoring import FINALIZE_LOCK_FILENAME
from slop_code.metrics.scoring import GENERATIONS_DIR
from slop_code.metrics.scoring import HISTORICAL_PROVENANCE_DIR
from slop_code.metrics.scoring import MANIFEST_FILENAME
from slop_code.metrics.scoring import MEASUREMENT_ANALYSIS_DIR
from slop_code.metrics.scoring import PENDING_ORACLES_DIR
from slop_code.metrics.scoring import PROBLEM_SCORE_FILENAME
from slop_code.metrics.scoring import PRODUCER_STATUS_FILENAME
from slop_code.metrics.scoring import PRODUCTION_QUALITY_CONTRACT
from slop_code.metrics.scoring import SCORING_DIR
from slop_code.metrics.scoring import STAGING_DIR
from slop_code.metrics.scoring import BenchmarkScore
from slop_code.metrics.scoring import BenchmarkScoreInput
from slop_code.metrics.scoring import Eligibility
from slop_code.metrics.scoring import ProblemScoreInput
from slop_code.metrics.scoring import calculate_problem_score
from slop_code.metrics.scoring import canonical_json_bytes
from slop_code.metrics.scoring import ranking_key
from slop_code.metrics.scoring import scoring_schema_id
from slop_code.metrics.scoring.models import CheckpointCorrectnessEvidence
from slop_code.metrics.scoring.models import CheckpointCostEvidence
from slop_code.metrics.scoring.models import LineageCandidate
from slop_code.metrics.scoring.models import LineageComponentEvidence
from slop_code.metrics.scoring.models import LineageLedgerEntry
from slop_code.metrics.scoring.models import OwnedLineEvidence
from slop_code.metrics.scoring.models import PhysicalLineEvidence
from slop_code.metrics.scoring.models import ProblemCostEvidence
from slop_code.metrics.scoring.models import ProductionGraphEvidence
from slop_code.metrics.scoring.models import ProductionQualityRawEvidence
from slop_code.metrics.scoring.models import ReworkCheckpointInput
from slop_code.metrics.scoring.models import SymbolDegreeEvidence
from slop_code.metrics.scoring.models import SymbolIdentity
from slop_code.metrics.scoring.models import TransitionReworkEvidence
from slop_code.metrics.scoring.models import TransitionScoreEvidence
from slop_code.metrics.scoring.schema import calculate_scores
from slop_code.metrics.scoring.schema import canonical_decimal

D = Decimal
FIXTURE_PATH = Path(__file__).parent / "fixtures/scoring_golden.json"


def checkpoints(rates):
    counts = {D("0"): (0, 1), D("0.5"): (1, 2), D("1"): (1, 1)}
    return tuple(
        CheckpointCorrectnessEvidence(
            checkpoint_id=f"checkpoint-{index}",
            passed=counts.get(rate, (1, 3))[0],
            total=counts.get(rate, (1, 3))[1],
            rate=rate,
        )
        for index, rate in enumerate(rates, start=1)
    )


def costs(problem_id, values, produced=None):
    return ProblemCostEvidence(
        problem_id=problem_id,
        checkpoints=tuple(
            CheckpointCostEvidence(
                checkpoint_id=f"checkpoint-{index}",
                produced=value is not None
                if produced is None
                else produced[index - 1],
                cost=value,
            )
            for index, value in enumerate(values, start=1)
        ),
    )


def cost_checkpoint(checkpoint_id, produced, cost):
    return CheckpointCostEvidence(
        checkpoint_id=checkpoint_id,
        produced=produced,
        cost=cost,
    )


def problem(problem_id="alpha", correctness=(D("1"), D("1")), value=D("1")):
    return calculate_problem_score(
        problem_id,
        checkpoints(correctness),
        (value,) * len(correctness),
        (value,) * len(correctness),
        (value,) * len(correctness),
        (value,) * (len(correctness) - 1),
        (value,) * (len(correctness) - 1),
    )


def _benchmark_fixture(
    configured_problem_ids,
    configured_checkpoint_counts,
    scores,
    problem_costs,
    run_identity,
):
    supplied = {score.problem_id: score for score in scores}
    completed = tuple(supplied.get(name) for name in configured_problem_ids)
    invalid_cost = any(
        checkpoint.produced and checkpoint.cost is None
        for item in problem_costs
        for checkpoint in item.checkpoints
    )
    total_cost = sum(
        (
            checkpoint.cost or D("0")
            for item in problem_costs
            for checkpoint in item.checkpoints
            if checkpoint.produced
        ),
        D("0"),
    )
    denominator = sum(configured_checkpoint_counts)
    return BenchmarkScore(
        problems=tuple(item for item in completed if item is not None),
        benchmark_score=canonical_decimal(
            sum(
                (
                    item.score if item is not None else D("0")
                    for item in completed
                ),
                D("0"),
            )
            / len(configured_problem_ids),
            D("0.000001"),
        ),
        correctness=canonical_decimal(
            sum(
                (
                    item.components.correctness if item is not None else D("0")
                    for item in completed
                ),
                D("0"),
            )
            / len(configured_problem_ids)
        ),
        inertia=canonical_decimal(
            sum(
                (
                    item.components.inertia if item is not None else D("0")
                    for item in completed
                ),
                D("0"),
            )
            / len(configured_problem_ids)
        ),
        cost_per_configured_checkpoint=(
            None
            if invalid_cost
            else canonical_decimal(total_cost / D(denominator))
        ),
        run_identity=run_identity,
    )


def test_benchmark_aggregation_uses_raw_values_before_quantization() -> None:
    def score_input(problem_id: str, value: Decimal) -> ProblemScoreInput:
        return ProblemScoreInput(
            problem_id=problem_id,
            checkpoint_ids=("one", "two"),
            checkpoint_correctness=(
                CheckpointCorrectnessEvidence(
                    checkpoint_id="one", passed=1, total=1, rate=D("1")
                ),
                CheckpointCorrectnessEvidence(
                    checkpoint_id="two", passed=1, total=1, rate=D("1")
                ),
            ),
            verbosity=(value, value),
            erosion=(value, value),
            architecture=(value, value),
            rework=(value,),
            regression=(value,),
        )

    inputs = (
        score_input("alpha", D("0.0000000196")),
        score_input("beta", D("0.0000000596")),
    )
    benchmark_input = BenchmarkScoreInput(
        configured_problem_ids=("alpha", "beta"),
        configured_checkpoint_counts=(2, 2),
        costs=(
            costs("alpha", (D("0"), D("0"))),
            costs("beta", (D("0"), D("0"))),
        ),
        run_identity="raw-rounding-boundary",
    )

    problems, benchmark = calculate_scores(inputs, benchmark_input)
    persisted_mean = sum((item.score for item in problems), D("0")) / D("2")

    assert benchmark.benchmark_score == D("70.000001")
    assert persisted_mean == D("70.0000015")
    assert canonical_decimal(persisted_mean, D("0.000001")) == D("70.000002")


def test_hand_calculated_problem_golden_cases_preserve_raw_counts_and_quantization():
    fixture = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
    for case in fixture["problem_cases"]:
        rates = tuple(D(value) for value in case["checkpoint_correctness"])
        score = calculate_problem_score(
            case["name"],
            checkpoints(rates),
            *(
                tuple(D(value) for value in case[name])
                for name in (
                    "verbosity",
                    "erosion",
                    "architecture",
                    "rework",
                    "regression",
                )
            ),
        )
        assert str(score.score) == case["score"]
        assert tuple(
            (item.passed, item.total, item.rate)
            for item in score.checkpoint_correctness
        ) == tuple(
            (passed, total, rate)
            for passed, total, rate in zip(
                case["canonical_passed"],
                case["canonical_totals"],
                rates,
                strict=True,
            )
        )


def test_raw_checkpoint_counts_reject_rounding_and_duplicate_ordered_identity():
    with pytest.raises(ValidationError, match="passed / total"):
        CheckpointCorrectnessEvidence(
            checkpoint_id="one", passed=1, total=3, rate=D("0.333333333333")
        )
    duplicate = (
        CheckpointCorrectnessEvidence(
            checkpoint_id="one", passed=1, total=1, rate=D("1")
        ),
        CheckpointCorrectnessEvidence(
            checkpoint_id="one", passed=1, total=1, rate=D("1")
        ),
    )
    with pytest.raises(ValueError, match="identifiers must be unique"):
        calculate_problem_score(
            "alpha",
            duplicate,
            (D("1"),) * 2,
            (D("1"),) * 2,
            (D("1"),) * 2,
            (D("1"),),
            (D("1"),),
        )


def test_zero_graph_edges_no_changed_symbol_and_lineage_boundaries_are_explicit():
    graph = ProductionGraphEvidence(
        checkpoint_id="two",
        nodes=(),
        edges=(),
        sccs=(),
        cyclic_mass=D("0"),
        total_mass=D("0"),
        architecture=D("1"),
    )
    prior = SymbolIdentity(
        path="src/a.py",
        qualified_name="f",
        kind="function",
        start_line=1,
        end_line=3,
    )
    current = prior.model_copy(update={"start_line": 5, "end_line": 7})
    accepted = LineageCandidate(
        prior=prior,
        current=current,
        body_hash_equal=True,
        structure_hash_equal=True,
        signature_hash_equal=False,
        accepted=True,
        ambiguous_set_id=None,
    )
    transition = TransitionScoreEvidence(
        prior_checkpoint_id="one",
        current_checkpoint_id="two",
        changed_lines=3,
        repeated_lines=0,
        lineage_candidates=(accepted,),
        symbol_degrees=(
            SymbolDegreeEvidence(symbol=prior, inbound=0, outbound=1),
        ),
        owned_lines=(OwnedLineEvidence(symbol=current, lines=(5, 6, 7)),),
        lineage_ledger=(
            LineageLedgerEntry(
                candidate=accepted,
                disposition="accepted",
                reason="exact lineage",
            ),
        ),
        rework=D("1"),
    )
    repeated = transition.model_copy(
        update={"repeated_lines": 3, "rework": D("0")}
    )
    ambiguous = accepted.model_copy(
        update={"accepted": False, "ambiguous_set_id": "union"}
    )
    assert graph.architecture == D("1")
    assert (
        transition.changed_lines,
        transition.repeated_lines,
        transition.rework,
    ) == (3, 0, D("1"))
    assert (repeated.repeated_lines, repeated.rework) == (3, D("0"))
    assert ambiguous.ambiguous_set_id == "union"


def test_missing_checkpoint_costs_are_zero_and_produced_missing_cost_is_null():
    fixture = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
    score = problem()
    cases = {case["name"]: case for case in fixture["benchmark_cases"]}

    def benchmark(case):
        return _benchmark_fixture(
            tuple(case["configured_problem_ids"]),
            tuple(case["configured_checkpoint_counts"]),
            (score,),
            (
                costs(
                    "alpha",
                    tuple(
                        D(value) if value is not None else None
                        for value in case["costs"]
                    ),
                    tuple(case["produced"]),
                ),
            ),
            case["name"],
        )

    for name in (
        "unproduced_checkpoint_zero_cost",
        "produced_checkpoint_missing_cost",
    ):
        case = cases[name]
        result = benchmark(case)
        if case["cost_per_configured_checkpoint"] is None:
            assert result.cost_per_configured_checkpoint is None
        else:
            assert (
                format(result.cost_per_configured_checkpoint, "f")
                == case["cost_per_configured_checkpoint"]
            )
        assert str(result.benchmark_score) == case["benchmark_score"]
        assert str(result.correctness) == case["correctness"]
        assert str(result.inertia) == case["inertia"]


def test_benchmark_ties_independently_order_score_correctness_inertia_cost_null_and_identity():
    perfect = problem("alpha")
    weak = problem("beta", (D("1"), D("1")), D("0"))
    high = _benchmark_fixture(
        ("alpha",), (2,), (perfect,), (costs("alpha", (D("2"), D("2"))),), "z"
    )
    low = _benchmark_fixture(
        ("beta",), (2,), (weak,), (costs("beta", (D("0"), D("0"))),), "a"
    )
    cheap = _benchmark_fixture(
        ("alpha",), (2,), (perfect,), (costs("alpha", (D("1"), D("1"))),), "z"
    )
    costly = _benchmark_fixture(
        ("alpha",), (2,), (perfect,), (costs("alpha", (D("2"), D("2"))),), "a"
    )
    null = _benchmark_fixture(
        ("alpha",),
        (2,),
        (perfect,),
        (costs("alpha", (D("2"), None), (True, True)),),
        "0",
    )
    same = _benchmark_fixture(
        ("alpha",), (2,), (perfect,), (costs("alpha", (D("1"), D("1"))),), "a"
    )
    assert ranking_key(high) < ranking_key(low)
    assert ranking_key(cheap) < ranking_key(costly) < ranking_key(null)
    assert ranking_key(same) < ranking_key(cheap)


@pytest.mark.parametrize(
    "component,lower_key,higher_key",
    [
        ("verbosity", "verbosity_lower", "verbosity_higher"),
        ("erosion", "erosion_lower", "erosion_higher"),
        ("architecture", "architecture_lower", "architecture_higher"),
        ("rework", "rework_lower", "rework_higher"),
        ("regression", "regression_lower", "regression_higher"),
    ],
)
def test_inertia_components_are_directionally_monotonic(
    component, lower_key, higher_key
):
    fixture = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
    cases = {case["name"]: case for case in fixture["problem_cases"]}

    def score(name):
        case = cases[name]
        result = calculate_problem_score(
            case["name"],
            checkpoints(
                tuple(D(value) for value in case["checkpoint_correctness"])
            ),
            *(
                tuple(D(value) for value in case[field])
                for field in (
                    "verbosity",
                    "erosion",
                    "architecture",
                    "rework",
                    "regression",
                )
            ),
        )
        return result.score

    lower = score(lower_key)
    higher = score(higher_key)
    assert lower <= higher, component
    assert lower != higher, component


def test_canonical_scoring_relative_names_are_exact():
    assert (
        SCORING_DIR,
        MEASUREMENT_ANALYSIS_DIR,
        GENERATIONS_DIR,
        STAGING_DIR,
        PENDING_ORACLES_DIR,
        HISTORICAL_PROVENANCE_DIR,
        EVALUATOR_ENVIRONMENTS_DIR,
        EVALUATOR_LOCK_FILENAME,
        EVALUATOR_READY_FILENAME,
        EVIDENCE_INDEX_FILENAME,
        PRODUCER_STATUS_FILENAME,
        ELIGIBILITY_FILENAME,
        PROBLEM_SCORE_FILENAME,
        BENCHMARK_SCORE_FILENAME,
        CHECKPOINT_REPORT_ADDITIONS_FILENAME,
        MANIFEST_FILENAME,
        CURRENT_POINTER_FILENAME,
        FINALIZE_LOCK_FILENAME,
    ) == (
        "scoring",
        "measurement_analysis",
        "generations",
        "staging",
        "oracles",
        "historical_provenance",
        "evaluator_environments",
        "evaluator.lock",
        "READY",
        "evidence_index.json",
        "producer_status.json",
        "eligibility.json",
        "problem_score.json",
        "benchmark_score.json",
        "checkpoint_report_additions.jsonl",
        "manifest.json",
        "current.json",
        "finalize.lock",
    )


def test_schema_bytes_and_eligibility_are_exact_and_closed():
    assert canonical_json_bytes({"x": D("0.10")}) == b'{"x":"0.10"}'
    assert scoring_schema_id() == scoring_schema_id()
    assert b"SIM111" in scoring_schema.scoring_schema_bytes()
    assert Eligibility(
        eligible=False,
        reasons=("coverage_parity_failed", "score_evidence_invalid"),
    ).reasons == ("coverage_parity_failed", "score_evidence_invalid")
    with pytest.raises(ValidationError):
        Eligibility(eligible=True, reasons=("score_evidence_invalid",))


@pytest.mark.parametrize(
    ("field", "change"),
    (
        (
            "expected interpreter",
            lambda contract: contract["expected_interpreter"].update(
                {"implementation": "pypy"}
            ),
        ),
        (
            "file-byte policy",
            lambda contract: contract["file_bytes"].update(
                {"input": "decoded_text"}
            ),
        ),
        (
            "parser/tokenizer probe",
            lambda contract: contract["parser_tokenizer"].update(
                {"probe_hex": "00"}
            ),
        ),
        (
            "parser/tokenizer algorithm",
            lambda contract: contract["parser_tokenizer"]["algorithm"][
                "ast"
            ].update({"include_attributes": True}),
        ),
        (
            "Ruff version",
            lambda contract: contract["ruff"].update(
                {"expected_version": "0.8.5"}
            ),
        ),
        (
            "Ruff invocation",
            lambda contract: contract["ruff"].update(
                {"arguments": ("--different",)}
            ),
        ),
        (
            "Ruff rules",
            lambda contract: contract["ruff"].update({"rules": ("SIM111",)}),
        ),
    ),
)
def test_schema_identity_includes_every_detector_contract_field(
    monkeypatch, field, change
):
    baseline = scoring_schema.scoring_schema_id()
    changed = deepcopy(PRODUCTION_QUALITY_CONTRACT)
    change(changed)
    monkeypatch.setattr(scoring_schema, "PRODUCTION_QUALITY_CONTRACT", changed)
    assert scoring_schema.scoring_schema_id() != baseline, field


def test_production_quality_raw_evidence_rejects_impossible_component_counts():
    evidence = {
        "checkpoint_id": "checkpoint",
        "interpreter": {
            "executable": "evaluator",
            "implementation": "cpython",
            "version": "3.12.0",
            "cache_tag": "cpython-312",
            "executable_sha256": "0" * 64,
            "ast_sha256": "1" * 64,
            "tokenize_sha256": "2" * 64,
        },
        "parser_tokenizer_schema_id": "3" * 64,
        "parser_tokenizer_probe": "78203d20310a696620783a0a2020202079203d20277a270a",
        "files": (
            {
                "path": "src/a.py",
                "hash": "4" * 64,
                "source_lines": (1,),
            },
        ),
        "ruff": {
            "version": "ruff 0.8.6",
            "invocation": (
                "evaluator",
                "-m",
                "ruff",
                "check",
                "--isolated",
                "--output-format",
                "json",
                "--select",
                "SIM102,SIM103,SIM108,SIM109,SIM110,SIM111,SIM114,SIM116,SIM401",
                "src/a.py",
            ),
            "rules": (
                "SIM102",
                "SIM103",
                "SIM108",
                "SIM109",
                "SIM110",
                "SIM111",
                "SIM114",
                "SIM116",
                "SIM401",
            ),
            "diagnostics": (),
        },
        "clones": (),
        "verbosity_lines": (("src/a.py", 1),),
        "clone_lines": (),
        "union_numerator": 0,
        "source_loc_denominator": 1,
        "eligible_symbols": (
            {
                "identity": ("src/a.py", "f", "function", 1, 1),
                "cc": D("0"),
                "sloc": 1,
                "mass": D("0"),
                "high_complexity": False,
            },
        ),
        "excluded_symbols": (
            {
                "reason": "symbol_kind_ineligible",
                "kind": "class",
                "path": "src/a.py",
            },
        ),
        "erosion_numerator": D("0"),
        "erosion_denominator": D("0"),
        "decimal_context": {"precision": 50, "rounding": "ROUND_HALF_EVEN"},
        "verbosity": D("1"),
        "erosion": D("1"),
    }
    assert ProductionQualityRawEvidence.model_validate(evidence).verbosity == D(
        "1"
    )
    with pytest.raises(ValidationError, match="verbosity numerator"):
        ProductionQualityRawEvidence.model_validate(
            {**evidence, "union_numerator": 2}
        )
    with pytest.raises(ValidationError, match="erosion numerator"):
        ProductionQualityRawEvidence.model_validate(
            {**evidence, "erosion_numerator": D("1")}
        )


def test_history_gap_golden_cases_reset_and_resume_transition_components():
    fixture = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
    for case in fixture["history_cases"]:
        produced = case["produced"]
        if "expected_score" in case:
            result = _benchmark_fixture(
                ("missing",),
                (2,),
                (),
                (costs("missing", (None, None), tuple(produced)),),
                case["name"],
            )
            assert str(result.benchmark_score) == case["expected_score"]
            assert result.problems == ()
            continue
        transition = calculate_problem_score(
            case["name"],
            checkpoints((D("1"),) * len(produced)),
            (D("1"),) * len(produced),
            (D("1"),) * len(produced),
            (D("1"),) * len(produced),
            (D(case["expected_rework"]),) * (len(produced) - 1),
            (D(case["expected_regression"]),) * (len(produced) - 1),
        )
        assert transition.components.rework == D(case["expected_rework"])
        assert transition.components.regression == D(
            case["expected_regression"]
        )


def test_multi_problem_golden_preserves_raw_and_persisted_decimal_stages():
    fixture = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))[
        "multi_problem_case"
    ]
    alpha = problem("alpha")
    beta = problem("beta", (D("1"), D("0")), D("0.5"))
    result = _benchmark_fixture(
        tuple(fixture["configured_problem_ids"]),
        tuple(fixture["configured_checkpoint_counts"]),
        (alpha, beta),
        (costs("alpha", (D("1"), D("1"))), costs("beta", (D("0.5"), D("0.5")))),
        "multi",
    )
    assert sum((alpha.score, beta.score), D("0")) == D(
        fixture["raw_score_numerator"]
    )
    assert sum(
        (alpha.components.correctness, beta.components.correctness), D("0")
    ) == D(fixture["raw_correctness_numerator"])
    assert sum(
        (alpha.components.inertia, beta.components.inertia), D("0")
    ) == D(fixture["raw_inertia_numerator"])
    assert sum((D("1"), D("1"), D("0.5"), D("0.5")), D("0")) == D(
        fixture["raw_cost_numerator"]
    )
    assert (
        str(result.benchmark_score),
        str(result.correctness),
        str(result.inertia),
        str(result.cost_per_configured_checkpoint),
    ) == (
        fixture["benchmark_score"],
        fixture["correctness"],
        fixture["inertia"],
        fixture["cost_per_configured_checkpoint"],
    )


def test_zero_loc_execution_failure_and_producer_order_are_ineligible_without_scores():
    fixture = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))[
        "eligibility_case"
    ]
    expected = tuple(fixture["reasons"])
    for discovered in fixture["producer_orders"]:
        eligibility = Eligibility(
            eligible=False, reasons=tuple(sorted(discovered))
        )
        assert eligibility.reasons == expected
        assert not eligibility.eligible
        assert "production_source_loc_zero" in eligibility.reasons
        assert "score_evidence_invalid" in eligibility.reasons
        assert not hasattr(eligibility, "benchmark_score")
        assert not hasattr(eligibility, "components")


def test_no_changed_symbol_first_transition_and_ambiguous_union_are_explicit():
    symbol = SymbolIdentity(
        path="src/a.py",
        qualified_name="f",
        kind="function",
        start_line=1,
        end_line=1,
    )
    candidate = LineageCandidate(
        prior=symbol,
        current=symbol,
        body_hash_equal=True,
        structure_hash_equal=True,
        signature_hash_equal=True,
        accepted=False,
        ambiguous_set_id="union",
    )
    transition = TransitionScoreEvidence(
        prior_checkpoint_id="first",
        current_checkpoint_id="second",
        changed_lines=0,
        repeated_lines=0,
        lineage_candidates=(candidate,),
        symbol_degrees=(),
        owned_lines=(),
        lineage_ledger=(
            LineageLedgerEntry(
                candidate=candidate,
                disposition="rejected",
                reason="ambiguous union",
            ),
        ),
        rework=D("1"),
    )
    assert transition.changed_lines == transition.repeated_lines == 0
    assert transition.lineage_candidates[0].ambiguous_set_id == "union"


def test_rework_public_models_require_canonical_hashes_ordered_ownership_and_endpoint_components():
    digest = "a" * 64
    prior = SymbolIdentity(
        path="src/a.py",
        qualified_name="f",
        parent_qualified_name="C",
        kind="method",
        start_line=1,
        end_line=3,
        body_sha256=digest,
        structure_sha256=digest,
        signature_sha256=digest,
    )
    current = prior.model_copy(update={"path": "src/b.py"})
    candidate = LineageCandidate(
        prior=prior,
        current=current,
        body_hash_equal=True,
        structure_hash_equal=True,
        signature_hash_equal=True,
        accepted=True,
        ambiguous_set_id=None,
        match="hash",
    )
    component = LineageComponentEvidence(
        component_id=digest,
        priors=(prior,),
        currents=(current,),
        ambiguous=False,
    )
    transition = TransitionReworkEvidence(
        changed_physical_lines=(
            PhysicalLineEvidence(
                path="src/a.py", line=2, side="removed", owner=prior
            ),
            PhysicalLineEvidence(
                path="src/b.py", line=2, side="added", owner=current
            ),
        ),
        lineage_candidates=(candidate,),
        symbol_degrees=(
            SymbolDegreeEvidence(symbol=prior, inbound=0, outbound=1),
            SymbolDegreeEvidence(symbol=current, inbound=1, outbound=0),
        ),
        lineage_components=(component,),
        owned_lines=(
            OwnedLineEvidence(symbol=prior, lines=(2,)),
            OwnedLineEvidence(symbol=current, lines=(2,)),
        ),
        lineage_ledger=(
            LineageLedgerEntry(
                candidate=candidate,
                disposition="accepted",
                reason="body and structure degree-one",
            ),
        ),
        ledger_transitions=(),
        changed_lines=2,
        repeated_lines=0,
        rework=D("1"),
    )

    assert prior.exact_identity == ("python", "method", "C", "f", "src/a.py")
    assert transition.lineage_components[0].component_id == digest
    assert (
        ReworkCheckpointInput(checkpoint_id="gap", symbols=None).symbols is None
    )
    with pytest.raises(ValidationError, match="SHA-256"):
        SymbolIdentity(
            path="src/a.py",
            qualified_name="f",
            kind="function",
            start_line=1,
            end_line=1,
            body_sha256="invalid",
        )
