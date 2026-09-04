from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any, cast

import pytest

from slop_code.entrypoints.commands import combine_results as command


class _Score:
    def model_dump(self, *, mode: str) -> dict[str, object]:
        assert mode == "json"
        return {
            "benchmark_score": "88.500000",
            "correctness": "0.9",
            "inertia": "0.3",
            "cost_per_configured_checkpoint": "1.25",
            "run_identity": "run-a",
            "problems": [
                {
                    "problem_id": "problem-a",
                    "score": "88.5",
                    "components": {
                        "correctness": "0.9",
                        "verbosity": "0.8",
                    },
                }
            ],
        }


def _make_run(tmp_path):
    run_dir = tmp_path / "run-a"
    run_dir.mkdir()
    (run_dir / "config.yaml").write_text("agent: {}\n")
    (run_dir / "checkpoint_results.jsonl").write_text(
        json.dumps({"problem": "problem-a", "checkpoint": "checkpoint-1"})
        + "\n"
    )
    return run_dir


def test_combine_results_serializes_canonical_score_metadata(
    tmp_path, monkeypatch
):
    _make_run(tmp_path)
    monkeypatch.setattr(
        command,
        "load_verified_current_generation",
        lambda _: (_Score(), object()),
    )

    command.combine_results(
        cast(Any, SimpleNamespace(obj=SimpleNamespace(verbosity=0))),
        tmp_path,
    )

    record = json.loads(
        (tmp_path / "combined_checkpoint_results.jsonl").read_text()
    )
    assert record["benchmark_score"] == "88.500000"
    assert record["scoring.correctness"] == "0.9"
    assert record["scoring.problems.problem-a.score"] == "88.5"
    assert record["scoring.problems.problem-a.verbosity"] == "0.8"


def test_combine_results_keeps_existing_output_when_metadata_cannot_serialize(
    tmp_path, monkeypatch
):
    _make_run(tmp_path)
    output_path = tmp_path / "combined_checkpoint_results.jsonl"
    output_path.write_text("previous output\n")
    monkeypatch.setattr(command, "_load_run_metadata", lambda *_: {"bad": {1}})

    with pytest.raises(TypeError):
        command.combine_results(
            cast(Any, SimpleNamespace(obj=SimpleNamespace(verbosity=0))),
            tmp_path,
            overwrite=True,
        )

    assert output_path.read_text() == "previous output\n"
    assert not list(tmp_path.glob(f".{output_path.name}.*"))
