"""Tests for synchronous grading's async bridge."""

import asyncio
import json
from collections import Counter
from pathlib import Path

import pytest

from slop_code.metrics.grade import _carry_forward_batch
from slop_code.metrics.grade import _run_async


def test_run_async_without_active_loop_returns_result():
    """The synchronous caller receives the coroutine result."""

    async def result() -> str:
        return "graded"

    assert _run_async(result()) == "graded"


def test_run_async_from_active_loop_returns_result():
    """The bridge uses an independent worker loop when required."""

    async def outer() -> str:
        async def result() -> str:
            return "graded"

        return _run_async(result())

    assert asyncio.run(outer()) == "graded"


def test_run_async_from_active_loop_propagates_exception():
    """Worker coroutine failures remain visible to the synchronous caller."""

    async def outer() -> None:
        async def fail() -> None:
            raise ValueError("grading failed")

        with pytest.raises(ValueError, match="grading failed"):
            _run_async(fail())

    asyncio.run(outer())


def test_carry_forward_batch_removes_stale_grades_from_disk_and_results(
    tmp_path: Path,
) -> None:
    """Repeated eligibility loss clears persisted and returned grades."""
    problem_dir = tmp_path / "problem"
    checkpoint_1 = problem_dir / "checkpoint_1"
    checkpoint_2 = problem_dir / "checkpoint_2"
    checkpoint_3 = problem_dir / "checkpoint_3"
    for checkpoint in (checkpoint_1, checkpoint_2, checkpoint_3):
        checkpoint.mkdir(parents=True)

    original = {
        "criteria": "overdoc",
        "start": 1,
        "file_name": "main.py",
    }
    stale_carried = {**original, "carried_over": "checkpoint_1"}
    (checkpoint_1 / "rubric.jsonl").write_text(json.dumps(original) + "\n")
    (checkpoint_2 / "rubric.jsonl").write_text(json.dumps(stale_carried) + "\n")
    (checkpoint_3 / "rubric.jsonl").write_text(json.dumps(stale_carried) + "\n")
    (checkpoint_2 / "diff.json").write_text(
        json.dumps(
            {
                "file_diffs": {
                    "main.py": {"diff_text": "@@ -1 +1 @@\n-change\n+change"}
                }
            }
        )
    )
    results = {
        "problem": {
            "checkpoint_1": ([original], {}),
            "checkpoint_2": ([], {}),
            "checkpoint_3": ([], {}),
        }
    }

    carried = _carry_forward_batch(tmp_path, results)

    assert carried == 0
    assert results["problem"]["checkpoint_2"][0] == []
    assert results["problem"]["checkpoint_3"][0] == []
    assert (checkpoint_2 / "rubric.jsonl").read_text() == ""
    assert (checkpoint_3 / "rubric.jsonl").read_text() == ""


def test_carry_forward_batch_preserves_merged_grade_multiset(
    tmp_path: Path,
) -> None:
    """Returned and persisted batches retain fresh and carried grades."""
    problem_dir = tmp_path / "problem"
    checkpoint_1 = problem_dir / "checkpoint_1"
    checkpoint_2 = problem_dir / "checkpoint_2"
    checkpoint_1.mkdir(parents=True)
    checkpoint_2.mkdir(parents=True)

    carried_grade = {
        "criteria": "overdoc",
        "start": 1,
        "file_name": "main.py",
    }
    fresh_grade = {
        "criteria": "duplication",
        "start": 3,
        "file_name": "main.py",
    }
    (checkpoint_1 / "rubric.jsonl").write_text(json.dumps(carried_grade) + "\n")
    (checkpoint_2 / "rubric.jsonl").write_text(json.dumps(fresh_grade) + "\n")
    results = {
        "problem": {
            "checkpoint_1": ([carried_grade], {}),
            "checkpoint_2": ([fresh_grade], {}),
        }
    }

    carried = _carry_forward_batch(tmp_path, results)

    expected = Counter(
        json.dumps(grade, sort_keys=True)
        for grade in [
            fresh_grade,
            {
                **carried_grade,
                "confidence": None,
                "carried_over": "checkpoint_1",
            },
        ]
    )
    persisted = [
        json.loads(line)
        for line in (checkpoint_2 / "rubric.jsonl").read_text().splitlines()
    ]
    returned = results["problem"]["checkpoint_2"][0]
    assert carried == 1
    assert (
        Counter(json.dumps(grade, sort_keys=True) for grade in persisted)
        == expected
    )
    assert (
        Counter(json.dumps(grade, sort_keys=True) for grade in returned)
        == expected
    )
