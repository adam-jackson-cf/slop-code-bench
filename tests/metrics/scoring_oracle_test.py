"""Tests for immutable live checkpoint oracle capture."""

from __future__ import annotations

import hashlib
import json
import threading
from pathlib import Path
from typing import cast

import pytest

from slop_code.evaluation.config import ProblemConfig
from slop_code.metrics.scoring.live_evidence import _committed_artifacts
from slop_code.metrics.scoring.oracle import capture_live_checkpoint_oracle


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


def test_committed_oracle_requires_complete_unmodified_artifacts(
    tmp_path: Path,
) -> None:
    problem = cast("ProblemConfig", type("Problem", (), {"name": "problem"})())

    def checkpoint(name: str) -> tuple[Path, Path]:
        target = tmp_path / name / "problem" / "one"
        _write_live_oracle_artifacts(target)
        return target, capture_live_checkpoint_oracle(target, "problem", "one")

    required = {
        "evaluation.json",
        "quality_analysis/overall_quality.json",
        "quality_analysis/files.jsonl",
        "quality_analysis/symbols.jsonl",
    }
    complete, _ = checkpoint("complete")
    assert set(_committed_artifacts(complete, "one", problem)) == required

    historical = tmp_path / "historical" / "problem" / "one"
    _write_live_oracle_artifacts(historical)
    historical_rows = []
    for relative in sorted(required):
        content = (historical / relative).read_bytes()
        historical_rows.append(
            {
                "path": relative,
                "presence": True,
                "bytes": len(content),
                "sha256": hashlib.sha256(content).hexdigest(),
            }
        )
    historical_bundle = {
        "kind": "historical_provenance_bundle",
        "source_type": "historical",
        "problems": [
            {
                "problem_id": "problem",
                "checkpoints": [
                    {"checkpoint_id": "one", "artifacts": historical_rows}
                ],
            }
        ],
    }
    content = json.dumps(
        historical_bundle, sort_keys=True, separators=(",", ":")
    ).encode()
    bundle_dir = (
        tmp_path
        / "historical"
        / "measurement_analysis"
        / ("historical_provenance")
    )
    bundle_dir.mkdir(parents=True)
    (bundle_dir / f"{hashlib.sha256(content).hexdigest()}.json").write_bytes(
        content
    )
    assert set(_committed_artifacts(historical, "one", problem)) == required

    omitted, oracle = checkpoint("omitted")
    payload = json.loads(oracle.read_bytes())
    payload["artifacts"].pop()
    oracle.unlink()
    content = json.dumps(
        payload, sort_keys=True, separators=(",", ":")
    ).encode()
    (oracle.parent / f"{hashlib.sha256(content).hexdigest()}.json").write_bytes(
        content
    )
    with pytest.raises(ValueError, match="canonical_provenance_unavailable"):
        _committed_artifacts(omitted, "one", problem)

    missing, _ = checkpoint("missing")
    (missing / "quality_analysis" / "files.jsonl").unlink()
    with pytest.raises(ValueError, match="canonical_provenance_unavailable"):
        _committed_artifacts(missing, "one", problem)

    modified, _ = checkpoint("modified")
    (modified / "quality_analysis" / "symbols.jsonl").write_text(
        '{"symbol":"changed"}\n'
    )
    with pytest.raises(ValueError, match="canonical_artifact_invalid"):
        _committed_artifacts(modified, "one", problem)
