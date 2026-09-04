"""Behavioral boundaries for immutable evidence generation publication."""

from __future__ import annotations

import hashlib
import json
from decimal import Decimal

import pytest

import slop_code.metrics.scoring.generation as scoring_generation
from slop_code.dashboard.data import load_verified_score_summary
from slop_code.metrics.scoring import BenchmarkScoreInput
from slop_code.metrics.scoring import CheckpointCorrectnessEvidence
from slop_code.metrics.scoring import CheckpointCostEvidence
from slop_code.metrics.scoring import Eligibility
from slop_code.metrics.scoring import ProblemCostEvidence
from slop_code.metrics.scoring import ProblemScoreInput
from slop_code.metrics.scoring import PublicationBoundary
from slop_code.metrics.scoring import ScoreEvidenceIndex
from slop_code.metrics.scoring import aggregate_eligibility
from slop_code.metrics.scoring import calculate_scores_from_evidence
from slop_code.metrics.scoring import canonical_json_bytes
from slop_code.metrics.scoring import freeze_evidence_index
from slop_code.metrics.scoring import load_verified_current_generation
from slop_code.metrics.scoring import load_verified_current_generation_state
from slop_code.metrics.scoring import publish_generation
from slop_code.metrics.scoring import read_verified_evidence
from slop_code.metrics.scoring import score_evidence_sidecar


def _sidecars() -> dict[str, bytes]:
    checkpoints = (
        CheckpointCorrectnessEvidence(
            checkpoint_id="one", passed=1, total=2, rate=Decimal("0.5")
        ),
        CheckpointCorrectnessEvidence(
            checkpoint_id="two", passed=2, total=2, rate=Decimal("1")
        ),
    )
    evidence = ScoreEvidenceIndex(
        parser_tokenizer_schema_id="a" * 64,
        problems=(
            ProblemScoreInput(
                problem_id="problem",
                checkpoint_ids=("one", "two"),
                checkpoint_correctness=checkpoints,
                verbosity=(Decimal("0.2"), Decimal("0.4")),
                erosion=(Decimal("0.1"), Decimal("0.3")),
                architecture=(Decimal("0.5"), Decimal("0.6")),
                rework=(Decimal("0.7"),),
                regression=(Decimal("0.8"),),
            ),
        ),
        benchmark=BenchmarkScoreInput(
            configured_problem_ids=("problem",),
            configured_checkpoint_counts=(2,),
            run_identity="run",
            costs=(
                ProblemCostEvidence(
                    problem_id="problem",
                    checkpoints=(
                        CheckpointCostEvidence(
                            checkpoint_id="one",
                            produced=True,
                            cost=Decimal("1"),
                        ),
                        CheckpointCostEvidence(
                            checkpoint_id="two", produced=False, cost=None
                        ),
                    ),
                ),
            ),
        ),
    )
    path, payload = score_evidence_sidecar(evidence)
    return {path: payload, "checkpoint.json": b"raw"}


def _current_generation_id(tmp_path) -> str:
    pointer = json.loads(
        (tmp_path / "measurement_analysis" / "current.json").read_text()
    )
    return pointer["generation_id"]


def test_eligibility_reasons_are_a_closed_sorted_set() -> None:
    assert aggregate_eligibility(
        (
            Eligibility(
                eligible=False,
                reasons=("score_evidence_invalid",),
            ),
            Eligibility(
                eligible=False,
                reasons=("coverage_parity_failed",),
            ),
        )
    ) == Eligibility(
        eligible=False,
        reasons=(
            "coverage_parity_failed",
            "score_evidence_invalid",
        ),
    )


def test_pure_consumer_reproduces_raw_formula_inputs() -> None:
    problems, benchmark = calculate_scores_from_evidence(_sidecars())
    assert problems[0].components.correctness == Decimal("0.750000000000")
    assert benchmark.problems == problems
    assert benchmark.cost_per_configured_checkpoint == Decimal("0.500000000000")


def test_current_generation_loader_verifies_integrity_and_exposes_components(
    tmp_path,
) -> None:
    published = publish_generation(
        tmp_path, _sidecars(), Eligibility(eligible=True)
    )
    assert published is not None

    benchmark, additions = load_verified_current_generation(tmp_path)
    assert tuple(
        (item.problem_name, item.checkpoint_id, item.checkpoint_index)
        for item in additions
    ) == (("problem", "one", 0), ("problem", "two", 1))
    assert published.benchmark == benchmark
    projected = load_verified_score_summary(tmp_path)
    assert projected["correctness"] == benchmark.correctness
    assert projected["inertia"] == benchmark.inertia
    assert (
        projected["problems"]["problem"]["components"]["verbosity"]
        == "0.300000000000"
    )

    ready = (
        tmp_path
        / "measurement_analysis"
        / "generations"
        / _current_generation_id(tmp_path)
        / "READY"
    )
    ready.write_bytes(b"torn")
    with pytest.raises(ValueError, match="manifest is invalid"):
        load_verified_current_generation(tmp_path)


def test_problem_scores_use_exact_hash_keys_independent_of_configuration_order(
    tmp_path,
) -> None:
    def sidecars(names: tuple[str, ...]) -> dict[str, bytes]:
        checkpoint_rows = (
            CheckpointCorrectnessEvidence(
                checkpoint_id="one", passed=1, total=1, rate=Decimal("1")
            ),
            CheckpointCorrectnessEvidence(
                checkpoint_id="two", passed=1, total=1, rate=Decimal("1")
            ),
        )
        evidence = ScoreEvidenceIndex(
            parser_tokenizer_schema_id="a" * 64,
            problems=tuple(
                ProblemScoreInput(
                    problem_id=name,
                    checkpoint_ids=("one", "two"),
                    checkpoint_correctness=checkpoint_rows,
                    verbosity=(Decimal("1"), Decimal("1")),
                    erosion=(Decimal("1"), Decimal("1")),
                    architecture=(Decimal("1"), Decimal("1")),
                    rework=(Decimal("1"),),
                    regression=(Decimal("1"),),
                )
                for name in names
            ),
            benchmark=BenchmarkScoreInput(
                configured_problem_ids=names,
                configured_checkpoint_counts=tuple(2 for _ in names),
                run_identity="ordered",
                costs=tuple(
                    ProblemCostEvidence(
                        problem_id=name,
                        checkpoints=(
                            CheckpointCostEvidence(
                                checkpoint_id="one", produced=False, cost=None
                            ),
                            CheckpointCostEvidence(
                                checkpoint_id="two", produced=False, cost=None
                            ),
                        ),
                    )
                    for name in names
                ),
            ),
        )
        path, payload = score_evidence_sidecar(evidence)
        return {path: payload}

    expected = {
        hashlib.sha256(name.encode()).hexdigest() for name in ("alpha", "beta")
    }
    for index, names in enumerate((("alpha", "beta"), ("beta", "alpha"))):
        root = tmp_path / str(index)
        publish_generation(root, sidecars(names), Eligibility(eligible=True))
        generation = (
            root
            / "measurement_analysis"
            / "generations"
            / _current_generation_id(root)
        )
        assert {
            path.parent.name
            for path in generation.glob("problems/*/problem_score.json")
        } == expected
        assert not tuple(generation.glob("problem_*_problem_score.json"))


def test_input_defects_are_closed_set_aggregated() -> None:
    with pytest.raises(ValueError, match="score_evidence_invalid"):
        calculate_scores_from_evidence({"score_evidence.json": b"{}"})


def test_ineligible_input_publishes_complete_generation_without_scores(
    tmp_path,
) -> None:
    result = publish_generation(
        tmp_path,
        _sidecars(),
        Eligibility(eligible=False, reasons=("score_evidence_invalid",)),
    )
    assert result.eligibility == Eligibility(
        eligible=False, reasons=("score_evidence_invalid",)
    )
    analysis = tmp_path / "measurement_analysis"
    generation = analysis / "generations" / _current_generation_id(tmp_path)
    assert json.loads((generation / "eligibility.json").read_text()) == {
        "eligible": False,
        "reasons": ["score_evidence_invalid"],
    }
    assert (generation / "READY").is_file()
    assert not (generation / "benchmark_score.json").exists()
    assert not tuple(generation.glob("problems/*/problem_score.json"))
    manifest, evidence = load_verified_current_generation_state(tmp_path)
    assert manifest.eligibility == result.eligibility
    assert evidence["checkpoint.json"] == b"raw"


def test_reader_rejects_missing_altered_and_noncanonical_index_sidecars(
    tmp_path,
) -> None:
    generation = tmp_path / "generation"
    generation.mkdir()
    entries = freeze_evidence_index({"checkpoint.json": b"original"})
    (generation / "evidence_index.json").write_bytes(
        canonical_json_bytes(
            [entry.model_dump(mode="json") for entry in entries]
        )
    )
    with pytest.raises(ValueError, match="missing"):
        read_verified_evidence(generation)
    (generation / "checkpoint.json").write_bytes(b"tampered")
    with pytest.raises(ValueError, match="hash mismatch"):
        read_verified_evidence(generation)
    (generation / "evidence_index.json").write_text(
        json.dumps([entry.model_dump(mode="json") for entry in entries])
    )
    with pytest.raises(ValueError, match="canonical evidence index is invalid"):
        read_verified_evidence(generation)


def test_failure_before_pointer_preserves_existing_pointer(tmp_path) -> None:
    analysis = tmp_path / "measurement_analysis"
    analysis.mkdir()
    (analysis / "current.json").write_text('{"generation_id":"old"}')
    sidecars = _sidecars()
    sidecars["score_evidence.json"] = b"{}"
    with pytest.raises(ValueError, match="score_evidence_invalid"):
        publish_generation(tmp_path, sidecars, Eligibility(eligible=True))
    assert (analysis / "current.json").read_text() == '{"generation_id":"old"}'


def test_reuse_revalidates_scores_and_repairs_pointer(tmp_path) -> None:
    first = publish_generation(
        tmp_path, _sidecars(), Eligibility(eligible=True)
    )
    assert first is not None
    analysis = tmp_path / "measurement_analysis"
    (analysis / "current.json").write_text('{"generation_id":"stale"}')
    reused = publish_generation(
        tmp_path, _sidecars(), Eligibility(eligible=True)
    )
    assert reused == first
    assert json.loads((analysis / "current.json").read_text()) == {
        "generation_id": _current_generation_id(tmp_path)
    }


@pytest.mark.parametrize(
    "boundary", ("before_pointer_write", "after_pointer_rename")
)
def test_reuse_pointer_repair_observes_atomic_boundaries(
    tmp_path, boundary: PublicationBoundary
) -> None:
    published = publish_generation(
        tmp_path, _sidecars(), Eligibility(eligible=True)
    )
    assert published is not None
    generation_id = _current_generation_id(tmp_path)
    analysis = tmp_path / "measurement_analysis"
    (analysis / "current.json").write_text('{"generation_id":"stale"}')

    def fail_at(observed: PublicationBoundary) -> None:
        if observed == boundary:
            raise RuntimeError(boundary)

    with pytest.raises(RuntimeError, match=boundary):
        publish_generation(
            tmp_path,
            _sidecars(),
            Eligibility(eligible=True),
            failure_observer=fail_at,
        )

    pointer = json.loads((analysis / "current.json").read_text())
    if boundary == "after_pointer_rename":
        assert pointer == {"generation_id": _current_generation_id(tmp_path)}
    else:
        assert pointer == {"generation_id": "stale"}
    read_verified_evidence(analysis / "generations" / generation_id)


_ELIGIBLE_BOUNDARIES: tuple[PublicationBoundary, ...] = (
    "before_file_write",
    "after_file_write",
    "before_file_fsync",
    "after_file_fsync",
    "before_directory_fsync",
    "after_directory_fsync",
    "before_generation_rename",
    "after_generation_rename",
    "before_pointer_write",
    "after_pointer_write",
    "before_pointer_rename",
    "after_pointer_rename",
)


@pytest.mark.parametrize("boundary", _ELIGIBLE_BOUNDARIES)
def test_failure_observer_preserves_atomic_pointer_or_complete_generation(
    tmp_path, boundary: PublicationBoundary
) -> None:
    analysis = tmp_path / "measurement_analysis"
    analysis.mkdir()
    (analysis / "current.json").write_text('{"generation_id":"old"}')

    def fail_at(observed: PublicationBoundary) -> None:
        if observed == boundary:
            raise RuntimeError(boundary)

    with pytest.raises(RuntimeError, match=boundary):
        publish_generation(
            tmp_path,
            _sidecars(),
            Eligibility(eligible=True),
            failure_observer=fail_at,
        )

    pointer = json.loads((analysis / "current.json").read_text())
    generations = analysis / "generations"
    if boundary in {"after_generation_rename", "after_pointer_rename"}:
        if boundary == "after_pointer_rename":
            generation_id = pointer["generation_id"]
        else:
            generation_id = next(generations.iterdir()).name
        assert (generations / generation_id).is_dir()
        read_verified_evidence(generations / generation_id)
    if boundary == "after_pointer_rename":
        assert pointer["generation_id"] != "old"
    else:
        assert pointer == {"generation_id": "old"}


def test_ineligible_generation_observes_atomic_publication_boundaries(
    tmp_path,
) -> None:
    result = publish_generation(
        tmp_path,
        _sidecars(),
        Eligibility(eligible=False, reasons=("score_evidence_invalid",)),
    )
    generation = (
        tmp_path
        / "measurement_analysis"
        / "generations"
        / _current_generation_id(tmp_path)
    )
    assert result.publication_state.value == "ineligible"
    assert (generation / "READY").is_file()
    assert not (generation / "benchmark_score.json").exists()


@pytest.mark.parametrize("boundary", ("before_cleanup", "after_cleanup"))
def test_failure_observer_covers_cleanup(
    tmp_path, boundary: PublicationBoundary
) -> None:
    analysis = tmp_path / "measurement_analysis"
    analysis.mkdir()
    (analysis / "current.json").write_text('{"generation_id":"old"}')

    def fail_at(observed: PublicationBoundary) -> None:
        if observed == "before_file_write" or observed == boundary:
            raise RuntimeError(boundary)

    with pytest.raises(RuntimeError, match=boundary):
        publish_generation(
            tmp_path,
            _sidecars(),
            Eligibility(eligible=True),
            failure_observer=fail_at,
        )

    assert json.loads((analysis / "current.json").read_text()) == {
        "generation_id": "old"
    }


def test_producer_status_matrix_names_blocked_prerequisite(
    tmp_path,
) -> None:
    rows: tuple[dict[str, object], ...] = (
        {
            "producer": "checkpoint_evidence",
            "unit": "problem/one",
            "status": "successful",
            "blocked_by": None,
        },
        {
            "producer": "score_assembly",
            "unit": "benchmark",
            "status": "blocked",
            "blocked_by": "canonical_provenance_unavailable",
        },
    )
    publish_generation(
        tmp_path,
        _sidecars(),
        Eligibility(
            eligible=False,
            reasons=("canonical_provenance_unavailable",),
        ),
        producer_status_rows=rows,
    )
    generation = (
        tmp_path
        / "measurement_analysis"
        / "generations"
        / _current_generation_id(tmp_path)
    )
    assert json.loads((generation / "producer_status.json").read_text()) == {
        "rows": list(rows)
    }


def test_eligible_generation_never_degrades_to_ineligible(
    tmp_path,
) -> None:
    publish_generation(tmp_path, _sidecars(), Eligibility(eligible=True))
    generation_id = _current_generation_id(tmp_path)

    with pytest.raises(ValueError, match="eligible generation cannot degrade"):
        publish_generation(
            tmp_path,
            _sidecars(),
            Eligibility(
                eligible=False,
                reasons=("canonical_provenance_unavailable",),
            ),
        )

    assert _current_generation_id(tmp_path) == generation_id


def test_formula_cutover_may_publish_ineligible_generation(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        scoring_generation, "generation_formula_id", lambda _: "a" * 64
    )
    publish_generation(tmp_path, _sidecars(), Eligibility(eligible=True))
    prior_generation_id = _current_generation_id(tmp_path)

    monkeypatch.setattr(
        scoring_generation, "generation_formula_id", lambda _: "b" * 64
    )
    manifest = publish_generation(
        tmp_path,
        _sidecars(),
        Eligibility(
            eligible=False,
            reasons=("canonical_provenance_unavailable",),
        ),
        allow_formula_cutover=True,
    )

    assert manifest.formula_id == "b" * 64
    assert not manifest.eligibility.eligible
    assert _current_generation_id(tmp_path) != prior_generation_id
    assert (
        tmp_path
        / "measurement_analysis"
        / "generations"
        / prior_generation_id
    ).is_dir()


def test_identical_fingerprint_requires_deterministic_generation(
    tmp_path,
) -> None:
    publish_generation(tmp_path, _sidecars(), Eligibility(eligible=True))
    altered_rows: tuple[dict[str, object], ...] = (
        {
            "producer": "different",
            "unit": "checkpoint.json",
            "status": "successful",
            "blocked_by": None,
        },
    )

    with pytest.raises(
        ValueError,
        match="identical input fingerprint changed output",
    ):
        publish_generation(
            tmp_path,
            _sidecars(),
            Eligibility(eligible=True),
            producer_status_rows=altered_rows,
        )
