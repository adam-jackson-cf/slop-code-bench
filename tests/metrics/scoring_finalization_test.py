from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from slop_code.evaluation import CheckpointConfig
from slop_code.evaluation import ProblemConfig
from slop_code.evaluation.locked_environment import LockedEnvironmentError
from slop_code.metrics.scoring import live_evidence
from slop_code.metrics.scoring import score_evidence_sidecar
from slop_code.metrics.scoring.finalization import _build_score_evidence
from slop_code.metrics.scoring.finalization import _producer_status_rows
from slop_code.metrics.scoring.finalization import finalize_benchmark_score
from slop_code.metrics.scoring.generation import publish_generation
from slop_code.metrics.scoring.live_evidence import _changed_lines
from slop_code.metrics.scoring.models import BenchmarkScoreInput
from slop_code.metrics.scoring.models import CheckpointCorrectnessEvidence
from slop_code.metrics.scoring.models import CheckpointCostEvidence
from slop_code.metrics.scoring.models import Eligibility
from slop_code.metrics.scoring.models import ProblemCostEvidence
from slop_code.metrics.scoring.models import ProblemScoreInput
from slop_code.metrics.scoring.models import ScoreEvidenceIndex
from slop_code.metrics.scoring.schema import problem_key


def _problem() -> MagicMock:
    problem = MagicMock()
    problem.name = "problem"
    problem.iterate_checkpoint_items.side_effect = lambda: iter(
        (("checkpoint_1", object()), ("checkpoint_2", object()))
    )
    return problem


def _configured_problem(tmp_path: Path) -> ProblemConfig:
    return ProblemConfig(
        name="problem",
        path=tmp_path / "problem-config",
        version=1,
        description="fixture",
        tags=["test"],
        checkpoints={
            name: CheckpointConfig(name=name, version=1, order=order)
            for order, name in enumerate(
                ("checkpoint_1", "checkpoint_2"), start=1
            )
        },
        entry_file="main.py",
    )


def test_missing_live_oracle_preserves_current_generation(
    tmp_path: Path,
) -> None:
    publish_generation(
        tmp_path,
        {},
        Eligibility(
            eligible=False,
            reasons=("canonical_artifact_invalid",),
        ),
    )
    current = tmp_path / "measurement_analysis" / "current.json"
    pointer_before = current.read_bytes()
    legacy = tmp_path / "scoring" / "problems" / "problem" / "checkpoints"
    legacy.mkdir(parents=True)
    (legacy / "checkpoint_1.json").write_text("{}")

    checkpoint = tmp_path / "problem" / "checkpoint_1"
    checkpoint.mkdir(parents=True)
    (checkpoint / "inference_result.json").write_text("{}")
    with pytest.raises(RuntimeError, match="committed live oracle is missing"):
        finalize_benchmark_score(tmp_path, (_problem(),))

    assert current.read_bytes() == pointer_before


def test_live_changed_lines_are_root_independent_and_deduplicated(
    tmp_path: Path,
) -> None:
    roots: list[tuple[Path, Path]] = []
    for name in ("one", "two"):
        prior, current = tmp_path / name / "prior", tmp_path / name / "current"
        prior.mkdir(parents=True)
        current.mkdir(parents=True)
        (prior / "module.py").write_text("same\nold\nold\n")
        (current / "module.py").write_text("same\nnew\nnew\n")
        roots.append((prior, current))

    first = _changed_lines(*roots[0], ("module.py", "module.py"))
    second = _changed_lines(*roots[1], ("module.py",))

    assert first == second
    assert [line.model_dump() for line in first[0]] == [
        {"path": "module.py", "line": 2, "side": "removed", "owner": None},
        {"path": "module.py", "line": 3, "side": "removed", "owner": None},
    ]


def test_saved_docker_runtime_selects_exact_image_and_interpreter(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    run_dir = tmp_path / "run"
    checkpoint = run_dir / "problem" / "checkpoint_1"
    checkpoint.mkdir(parents=True)
    (run_dir / "environment.yaml").write_text(
        "type: docker\n"
        "name: python\n"
        "commands:\n"
        "  entry_file: '{entry_file}.py'\n"
        "docker:\n"
        "  image: base-image\n"
        "  binary: docker-bin\n"
    )
    (checkpoint.parent / "run_info.yaml").write_text("image: exact-image\n")
    expected_hash = "a" * 64
    monkeypatch.setattr(
        live_evidence.CorrectnessResults,
        "from_dir",
        lambda _: SimpleNamespace(
            evaluator_environment={
                "interpreter": (f"\n/usr/local/bin/python3\n{expected_hash}\n")
            }
        ),
    )

    executor, observed_hash = live_evidence._measurement_executor(checkpoint)

    assert isinstance(executor, live_evidence.DockerProcessExecutor)
    assert executor.binary == "docker-bin"
    assert executor.image == "exact-image"
    assert executor.mount_root == run_dir.resolve()
    assert observed_hash == expected_hash
    assert (
        live_evidence._saved_environment(checkpoint).format_entry_file("main")
        == "main.py"
    )


def test_invalid_saved_docker_runtime_is_rejected(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    checkpoint = run_dir / "problem" / "checkpoint_1"
    checkpoint.mkdir(parents=True)
    (run_dir / "environment.yaml").write_text(
        "type: docker\ndocker:\n  image: ignored\n"
    )

    with pytest.raises(LockedEnvironmentError, match="Docker binary"):
        live_evidence._measurement_executor(checkpoint)

def test_declared_zero_checkpoints_remain_eligible_and_successful() -> None:
    problem = _problem()
    prefix = (
        "problems/"
        "47a49356720831b66f38bbe12c06e6cf71a67277b1f5e6a28593e73afde6f226"
    )

    def checkpoint(checkpoint_id: str) -> dict[str, object]:
        return {
            "checkpoint_correctness": {
                "checkpoint_id": checkpoint_id,
                "produced": False,
                "passed": 0,
                "total": 0,
                "rate": "0",
            },
            "produced": False,
            "verbosity": "0",
            "erosion": "0",
            "architecture": "0",
            "cost": None,
        }

    sidecars = {
        f"{prefix}/checkpoints/checkpoint_1.json": (
            json.dumps(checkpoint("checkpoint_1")).encode()
        ),
        f"{prefix}/checkpoints/checkpoint_2.json": (
            json.dumps(checkpoint("checkpoint_2")).encode()
        ),
        f"{prefix}/transitions/checkpoint_1--checkpoint_2/rework.json": (
            b'{"rework":"0"}'
        ),
        f"{prefix}/transitions/checkpoint_1--checkpoint_2/regression.json": (
            b'{"regression":"0"}'
        ),
    }

    evidence, eligibility = _build_score_evidence(sidecars, (problem,))
    statuses = _producer_status_rows((problem,), sidecars, eligibility)

    assert eligibility == Eligibility(eligible=True)
    assert evidence is not None
    assert all(
        row["status"] == "successful"
        for row in statuses
        if row["producer"] == "checkpoint_evidence"
    )


@pytest.mark.parametrize("missing", ("rework.json", "regression.json"))
def test_missing_transition_component_blocks_score_assembly(missing: str):
    problem = _problem()
    prefix = (
        "problems/"
        "47a49356720831b66f38bbe12c06e6cf71a67277b1f5e6a28593e73afde6f226"
    )
    def checkpoint(checkpoint_id: str) -> bytes:
        return json.dumps(
            {
                "checkpoint_correctness": {
                    "checkpoint_id": checkpoint_id,
                    "produced": False,
                    "passed": 0,
                    "total": 0,
                    "rate": "0",
                },
                "produced": False,
                "verbosity": "0",
                "erosion": "0",
                "architecture": "0",
                "cost": None,
            }
        ).encode()

    transition = f"{prefix}/transitions/checkpoint_1--checkpoint_2"
    sidecars = {
        f"{prefix}/checkpoints/checkpoint_1.json": checkpoint("checkpoint_1"),
        f"{prefix}/checkpoints/checkpoint_2.json": checkpoint("checkpoint_2"),
        f"{transition}/rework.json": b'{"rework":"1"}',
        f"{transition}/regression.json": b'{"regression":"1"}',
    }
    sidecars.pop(f"{transition}/{missing}")

    evidence, eligibility = _build_score_evidence(sidecars, (problem,))
    statuses = _producer_status_rows((problem,), sidecars, eligibility)

    assert evidence is None
    assert eligibility.reasons == ("canonical_provenance_unavailable",)
    assert {
        row["producer"]: row["status"]
        for row in statuses
        if row["producer"] in {"transition_evidence", "score_assembly"}
    } == {
        "transition_evidence": "blocked",
        "score_assembly": "blocked",
    }


def test_finalizer_blocks_wholly_missing_problem_without_transition_evidence(
    tmp_path: Path,
) -> None:
    benchmark = finalize_benchmark_score(
        tmp_path, (_configured_problem(tmp_path),)
    )
    generation_id = json.loads(
        (tmp_path / "measurement_analysis" / "current.json").read_text()
    )["generation_id"]
    generation = (
        tmp_path / "measurement_analysis" / "generations" / generation_id
    )
    statuses = json.loads((generation / "producer_status.json").read_text())[
        "rows"
    ]

    assert benchmark is None
    assert {
        row["producer"]: row["status"]
        for row in statuses
        if row["producer"] in {"transition_evidence", "score_assembly"}
    } == {
        "transition_evidence": "blocked",
        "score_assembly": "blocked",
    }
    assert (generation / "eligibility.json").read_text() == (
        '{"eligible":false,"reasons":["canonical_provenance_unavailable"]}'
    )


def test_finalizer_publishes_mixed_produced_and_missing_checkpoints(
    tmp_path: Path, monkeypatch
) -> None:
    problem = _configured_problem(tmp_path)
    key = problem_key(problem.name)
    prefix = f"problems/{key}"
    score_evidence = ScoreEvidenceIndex(
        parser_tokenizer_schema_id="a" * 64,
        problems=(
            ProblemScoreInput(
                problem_id=problem.name,
                checkpoint_ids=("checkpoint_1", "checkpoint_2"),
                checkpoint_correctness=(
                    CheckpointCorrectnessEvidence(
                        checkpoint_id="checkpoint_1",
                        produced=True,
                        passed=1,
                        total=1,
                        rate=Decimal("1"),
                    ),
                    CheckpointCorrectnessEvidence(
                        checkpoint_id="checkpoint_2",
                        produced=False,
                        passed=0,
                        total=0,
                        rate=Decimal("0"),
                    ),
                ),
                verbosity=(Decimal("1"), Decimal("0")),
                erosion=(Decimal("1"), Decimal("0")),
                architecture=(Decimal("1"), Decimal("0")),
                rework=(Decimal("0"),),
                regression=(Decimal("0"),),
            ),
        ),
        benchmark=BenchmarkScoreInput(
            configured_problem_ids=(problem.name,),
            configured_checkpoint_counts=(2,),
            costs=(
                ProblemCostEvidence(
                    problem_id=problem.name,
                    checkpoints=(
                        CheckpointCostEvidence(
                            checkpoint_id="checkpoint_1",
                            produced=True,
                            cost=Decimal("2"),
                        ),
                        CheckpointCostEvidence(
                            checkpoint_id="checkpoint_2",
                            produced=False,
                            cost=None,
                        ),
                    ),
                ),
            ),
            run_identity="mixed",
        ),
    )
    evidence_path, evidence_payload = score_evidence_sidecar(score_evidence)

    def materialize(sidecars, _problems, _run_dir):
        sidecars.update(
            {
                evidence_path: evidence_payload,
                f"{prefix}/checkpoints/checkpoint_1.json": (
                    b'{"produced":true}'
                ),
                f"{prefix}/checkpoints/checkpoint_1/production_quality.json": b"{}",
                f"{prefix}/checkpoints/checkpoint_1/production_graph.json": b"{}",
                f"{prefix}/checkpoints/checkpoint_2.json": (
                    b'{"produced":false}'
                ),
                f"{prefix}/transitions/checkpoint_1--checkpoint_2/rework.json": b"{}",
                f"{prefix}/transitions/checkpoint_1--checkpoint_2/regression.json": b"{}",
            }
        )
        return Eligibility(eligible=True)

    monkeypatch.setattr(
        "slop_code.metrics.scoring.finalization._materialize_score_evidence",
        materialize,
    )
    benchmark = finalize_benchmark_score(tmp_path, (problem,))
    generation_id = json.loads(
        (tmp_path / "measurement_analysis" / "current.json").read_text()
    )["generation_id"]
    statuses = json.loads(
        (
            tmp_path
            / "measurement_analysis"
            / "generations"
            / generation_id
            / "producer_status.json"
        ).read_text()
    )["rows"]

    assert benchmark is not None
    assert benchmark.cost_per_configured_checkpoint == Decimal("1.000000000000")
    assert all(row["status"] == "successful" for row in statuses)
