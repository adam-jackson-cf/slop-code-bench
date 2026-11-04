"""Resume invalidation must not leave stale scoring evidence behind."""

from __future__ import annotations

import json
from pathlib import Path

from slop_code.agent_runner.models import UsageTracker
from slop_code.agent_runner.resume import ResumeInfo
from slop_code.common.llms import TokenUsage
from slop_code.entrypoints.problem_runner.worker import (
    _delete_invalidated_checkpoints,
)
from slop_code.metrics.scoring.oracle import capture_live_checkpoint_oracle


def _write_checkpoint_artifacts(checkpoint_dir: Path, quality: int) -> None:
    quality_dir = checkpoint_dir / "quality_analysis"
    quality_dir.mkdir(parents=True)
    (checkpoint_dir / "evaluation.json").write_text(
        json.dumps(
            {
                "checkpoint_name": checkpoint_dir.name,
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
                "invocation": {"command": "pytest", "cwd": "snapshot"},
                "test_corpus": {"files": [], "manifest_sha256": "d" * 64},
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
    (quality_dir / "overall_quality.json").write_text(
        json.dumps({"quality": quality}) + "\n"
    )
    (quality_dir / "files.jsonl").write_text('{"path":"a.py"}\n')
    (quality_dir / "symbols.jsonl").write_text('{"symbol":"f"}\n')


def _resume_info(invalidated: list[str], completed: list[str]) -> ResumeInfo:
    return ResumeInfo(
        completed_checkpoints=completed,
        last_snapshot_dir=None,
        resume_from_checkpoint=invalidated[0],
        prior_usage=UsageTracker(
            cost=0.0,
            steps=0,
            net_tokens=TokenUsage(),
            current_tokens=TokenUsage(),
        ),
        invalidated_checkpoints=invalidated,
    )


def test_rerun_of_invalidated_checkpoint_commits_fresh_oracle(
    tmp_path: Path,
) -> None:
    problem_dir = tmp_path / "run" / "problem"
    for checkpoint in ("checkpoint_1", "checkpoint_2"):
        _write_checkpoint_artifacts(problem_dir / checkpoint, quality=1)
        capture_live_checkpoint_oracle(
            problem_dir / checkpoint, "problem", checkpoint
        )
    kept_oracle = next(
        (tmp_path / "run" / "measurement_analysis" / "pending").glob(
            "*/checkpoint_1/oracles/*.json"
        )
    )

    _delete_invalidated_checkpoints(
        problem_dir, "problem", _resume_info(["checkpoint_2"], ["checkpoint_1"])
    )

    assert not (problem_dir / "checkpoint_2").exists()
    _write_checkpoint_artifacts(problem_dir / "checkpoint_2", quality=2)
    rerun_oracle = capture_live_checkpoint_oracle(
        problem_dir / "checkpoint_2", "problem", "checkpoint_2"
    )
    assert [p.name for p in rerun_oracle.parent.glob("*.json")] == [
        rerun_oracle.name
    ]
    assert kept_oracle.is_file()
