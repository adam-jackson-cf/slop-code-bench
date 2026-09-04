"""Tests for immutable strict-baseline oracle capture."""

from __future__ import annotations

import base64
import hashlib
import json
import shutil
import threading
from pathlib import Path
from typing import cast

import pytest

from slop_code.evaluation.config import ProblemConfig
from slop_code.metrics.scoring.finalization import finalize_benchmark_score
from slop_code.metrics.scoring.historical import capture_historical_provenance
from slop_code.metrics.scoring.models import OracleBundle
from slop_code.metrics.scoring.oracle import BASELINE_DIRECTORY_NAMES
from slop_code.metrics.scoring.oracle import capture_baseline_oracle
from slop_code.metrics.scoring.oracle import capture_live_checkpoint_oracle
from slop_code.metrics.scoring.oracle import serialize_baseline_oracle
from slop_code.metrics.scoring.oracle import validate_baseline_oracle

REPOSITORY_ROOT = Path(__file__).parents[2]
FIXTURE_PATH = (
    REPOSITORY_ROOT / "tests/metrics/fixtures/scoring_baseline_oracle.json"
)


def _fixture_oracle() -> OracleBundle:
    return OracleBundle.model_validate_json(
        FIXTURE_PATH.read_text(encoding="utf-8")
    )


def test_capture_matches_checked_baseline_oracle() -> None:
    oracle = _fixture_oracle()

    validate_baseline_oracle(REPOSITORY_ROOT, oracle)
    assert (
        serialize_baseline_oracle(capture_baseline_oracle(REPOSITORY_ROOT))
        == FIXTURE_PATH.read_bytes()
    )
    assert (
        tuple(baseline.name for baseline in oracle.baselines)
        == BASELINE_DIRECTORY_NAMES
    )
    assert sum(len(baseline.artifacts) for baseline in oracle.baselines) == 12


def test_capture_is_path_independent_and_repeatable(tmp_path: Path) -> None:
    for baseline_name in BASELINE_DIRECTORY_NAMES:
        shutil.copytree(
            REPOSITORY_ROOT / "experiments" / baseline_name,
            tmp_path / "experiments" / baseline_name,
        )

    first = capture_baseline_oracle(tmp_path)
    second = capture_baseline_oracle(tmp_path)

    assert serialize_baseline_oracle(first) == serialize_baseline_oracle(second)
    assert serialize_baseline_oracle(first) == serialize_baseline_oracle(
        capture_baseline_oracle(REPOSITORY_ROOT)
    )


def _archived_tree_hashes(baseline_directory: Path) -> dict[str, str]:
    return {
        path.relative_to(baseline_directory).as_posix(): hashlib.sha256(
            path.read_bytes()
        ).hexdigest()
        for path in sorted(baseline_directory.rglob("*"))
        if path.is_file()
    }


def test_historical_baselines_are_immutable_and_path_independent(
    tmp_path: Path,
) -> None:
    oracle = _fixture_oracle()
    archive_hashes = {
        name: _archived_tree_hashes(REPOSITORY_ROOT / "experiments" / name)
        for name in BASELINE_DIRECTORY_NAMES
    }
    roots = (tmp_path / "first", tmp_path / "second")
    for root in roots:
        for baseline_name in BASELINE_DIRECTORY_NAMES:
            shutil.copytree(
                REPOSITORY_ROOT / "experiments" / baseline_name,
                root.resolve() / "experiments" / baseline_name,
            )

    captures = tuple(capture_baseline_oracle(root.resolve()) for root in roots)
    assert all(
        serialize_baseline_oracle(capture) == serialize_baseline_oracle(oracle)
        for capture in captures
    )
    assert {
        Path(artifact.relative_path).name
        for baseline in oracle.baselines
        for artifact in baseline.artifacts
    } == {
        "checkpoint_results.jsonl",
        "files.jsonl",
        "overall_quality.json",
        "symbols.jsonl",
    }
    checkpoint_count = sum(
        len(artifact.projections)
        for baseline in oracle.baselines
        for artifact in baseline.artifacts
        if artifact.relative_path.endswith("checkpoint_results.jsonl")
    )
    assert checkpoint_count == 3
    assert checkpoint_count - len(oracle.baselines) == 0

    problem = type(
        "ArchivedProblem",
        (),
        {
            "name": "mocked_http",
            "entry_file": "hmock",
            "measurement_generated_globs": [],
            "measurement_test_globs": [],
            "iterate_checkpoint_items": lambda self: iter(
                (f"checkpoint_{index}", object()) for index in range(1, 9)
            ),
            "model_dump": lambda self, mode: {
                "name": self.name,
                "checkpoints": [f"checkpoint_{index}" for index in range(1, 9)],
            },
        },
    )()
    statuses: list[bytes] = []
    for root in roots:
        for baseline_name in BASELINE_DIRECTORY_NAMES:
            baseline = root.resolve() / "experiments" / baseline_name
            analysis = baseline / "measurement_analysis"
            prior_pointer = json.loads(
                (analysis / "current.json").read_bytes()
            )
            capture_historical_provenance(
                baseline, (cast("ProblemConfig", problem),)
            )
            assert (
                finalize_benchmark_score(
                    baseline, (cast("ProblemConfig", problem),)
                )
                is None
            )
            pointer = json.loads((analysis / "current.json").read_bytes())
            assert pointer["generation_id"] != prior_pointer["generation_id"]
            assert (
                analysis
                / "generations"
                / prior_pointer["generation_id"]
            ).is_dir()
            generation = analysis / "generations" / pointer["generation_id"]
            statuses.append((generation / "eligibility.json").read_bytes())
            assert not (generation / "benchmark_score.json").exists()
            copy_hashes = _archived_tree_hashes(baseline)
            assert {
                path: copy_hashes[path]
                for path in archive_hashes[baseline_name]
                if path != "measurement_analysis/current.json"
            } == {
                path: digest
                for path, digest in archive_hashes[baseline_name].items()
                if path != "measurement_analysis/current.json"
            }
    assert len(set(statuses)) == 1
    assert json.loads(statuses[0]) == {
        "eligible": False,
        "reasons": [
            "canonical_artifact_invalid",
            "canonical_provenance_unavailable",
        ],
    }
    assert {
        name: _archived_tree_hashes(REPOSITORY_ROOT / "experiments" / name)
        for name in BASELINE_DIRECTORY_NAMES
    } == archive_hashes
    assert all(
        serialize_baseline_oracle(capture_baseline_oracle(root.resolve()))
        == serialize_baseline_oracle(oracle)
        for root in roots
    )


def test_oracle_records_exact_bytes_hashes_and_typed_projections() -> None:
    oracle = _fixture_oracle()

    for baseline in oracle.baselines:
        for artifact in baseline.artifacts:
            source = REPOSITORY_ROOT / artifact.relative_path
            content = source.read_bytes()
            assert (
                base64.b64decode(artifact.bytes_base64, validate=True)
                == content
            )
            assert hashlib.sha256(content).hexdigest() == artifact.sha256

            raw_rows = (
                tuple(
                    json.loads(line) for line in content.decode().splitlines()
                )
                if source.suffix == ".jsonl"
                else (json.loads(content),)
            )
            assert tuple(
                projection.ordinal for projection in artifact.projections
            ) == tuple(range(len(raw_rows)))
            for projection, raw_row in zip(
                artifact.projections, raw_rows, strict=True
            ):
                assert (
                    projection.output_sha256
                    == hashlib.sha256(
                        json.dumps(
                            raw_row,
                            ensure_ascii=True,
                            sort_keys=True,
                            separators=(",", ":"),
                            allow_nan=False,
                        ).encode("utf-8")
                    ).hexdigest()
                )
                expected_rows = (
                    tuple(
                        (
                            key,
                            json.dumps(
                                value,
                                ensure_ascii=True,
                                sort_keys=True,
                                separators=(",", ":"),
                                allow_nan=False,
                            ),
                        )
                        for key, value in sorted(raw_row.items())
                    )
                    if isinstance(raw_row, dict)
                    else (
                        (
                            "value",
                            json.dumps(
                                raw_row,
                                ensure_ascii=True,
                                sort_keys=True,
                                separators=(",", ":"),
                                allow_nan=False,
                            ),
                        ),
                    )
                )
                assert projection.report_rows == expected_rows


def test_oracle_rejects_legacy_artifact_report_rows() -> None:
    fixture = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
    fixture["baselines"][0]["artifacts"][0]["report_rows"] = []

    with pytest.raises(ValueError):
        OracleBundle.model_validate(fixture)


def test_validation_rejects_altered_artifact_evidence() -> None:
    oracle = _fixture_oracle()
    first_baseline = oracle.baselines[0]
    first_artifact = first_baseline.artifacts[0]
    altered_artifact = first_artifact.model_copy(update={"sha256": "0" * 64})
    altered_baseline = first_baseline.model_copy(
        update={"artifacts": (altered_artifact, *first_baseline.artifacts[1:])}
    )
    altered_oracle = oracle.model_copy(
        update={"baselines": (altered_baseline, *oracle.baselines[1:])}
    )

    with pytest.raises(ValueError, match="does not match"):
        validate_baseline_oracle(REPOSITORY_ROOT, altered_oracle)


def _write_live_oracle_artifacts(checkpoint_dir: Path) -> None:
    quality_dir = checkpoint_dir / "quality_analysis"
    quality_dir.mkdir(parents=True)
    (checkpoint_dir / "evaluation.json").write_text(
        json.dumps(
            {
                "checkpoint_name": "one",
                "coverage_ledger": {
                    "outcomes": [],
                    "coverage": [],
                    "process_events": [],
                },
                "evaluator_environment": {
                    "environment_id": "a" * 64,
                    "input_sha256": {},
                },
                "test_collection_hash": "b" * 64,
                "environment_fingerprint": "c" * 64,
                "invocation": {
                    "command": "python -m coverage run --branch -m pytest",
                    "cwd": "snapshot",
                },
                "test_corpus": {
                    "files": [],
                    "manifest_sha256": "d" * 64,
                },
                "platform_identity": {
                    "machine": "arm64",
                    "platform": "test-platform",
                    "python_implementation": "CPython",
                    "python_version": "3.12.0",
                    "system": "Darwin",
                },
            }
        )
    )
    (quality_dir / "overall_quality.json").write_text('{"quality":1}\n')
    (quality_dir / "files.jsonl").write_text('{"path":"a.py"}\n')
    (quality_dir / "symbols.jsonl").write_text('{"symbol":"f"}\n')


def test_live_oracle_is_atomic_idempotent_and_conflict_detecting(
    tmp_path: Path,
) -> None:
    checkpoint = tmp_path / "problem" / "one"
    _write_live_oracle_artifacts(checkpoint)
    oracle_path = capture_live_checkpoint_oracle(checkpoint, "problem", "one")
    first = oracle_path.read_bytes()

    assert (
        capture_live_checkpoint_oracle(
            checkpoint, "problem", "one"
        ).read_bytes()
        == first
    )
    payload = json.loads(first)
    assert [artifact["relative_path"] for artifact in payload["artifacts"]] == [
        "evaluation.json",
        "quality_analysis/overall_quality.json",
        "quality_analysis/files.jsonl",
        "quality_analysis/symbols.jsonl",
    ]
    assert all(artifact["present"] for artifact in payload["artifacts"])
    assert all(
        artifact["byte_count"] > 0 and artifact["sha256"]
        for artifact in payload["artifacts"]
    )

    (checkpoint / "quality_analysis" / "overall_quality.json").write_text(
        '{"quality":2}\n'
    )
    with pytest.raises(ValueError, match="conflicting committed oracle"):
        capture_live_checkpoint_oracle(checkpoint, "problem", "one")


def test_live_oracle_recovers_stale_temp_and_concurrent_identical_capture(
    tmp_path: Path,
) -> None:
    checkpoint = tmp_path / "problem" / "one"
    _write_live_oracle_artifacts(checkpoint)
    problem_key = hashlib.sha256(b"problem").hexdigest()
    oracle_dir = (
        tmp_path
        / "measurement_analysis"
        / "pending"
        / problem_key
        / "one"
        / "oracles"
    )
    oracle_dir.mkdir(parents=True)
    (oracle_dir / ".oracle.stale").write_bytes(b"incomplete")
    failures: list[BaseException] = []

    def capture() -> None:
        try:
            capture_live_checkpoint_oracle(checkpoint, "problem", "one")
        except BaseException as error:  # noqa: BLE001
            failures.append(error)

    threads = [threading.Thread(target=capture) for _ in range(4)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert not failures
    assert not (oracle_dir / ".oracle.stale").exists()
    candidates = tuple(oracle_dir.glob("*.json"))
    assert len(candidates) == 1
    assert json.loads(candidates[0].read_text())["checkpoint_id"] == "one"
