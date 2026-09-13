"""Behavioral regressions for standalone analysis scripts."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

import pytest


def _load_script(name: str) -> ModuleType:
    path = Path(__file__).parents[2] / "scripts" / f"{name}.py"
    spec = importlib.util.spec_from_file_location(f"{name}_under_test", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


analyze_trajectory = _load_script("analyze_trajectory")
migrate_specs_solutions = _load_script("migrate_specs_solutions")
ToolEvent = analyze_trajectory.ToolEvent
detect_bug_fix_cycles = analyze_trajectory.detect_bug_fix_cycles
is_failure = analyze_trajectory.is_failure
migrate_problem = migrate_specs_solutions.migrate_problem


@pytest.mark.parametrize(
    ("exit_code", "has_error_output", "expected"),
    [
        (0, False, False),
        (1, False, True),
        (None, False, False),
        (None, True, True),
    ],
)
def test_failure_requires_a_nonzero_exit_code_or_error_evidence(
    exit_code, has_error_output, expected
):
    assert (
        is_failure(
            ToolEvent(
                name="Bash",
                index=0,
                exit_code=exit_code,
                has_error_output=has_error_output,
            )
        )
        is expected
    )


def test_bug_fix_metrics_leave_unknown_commands_unclassified():
    events = [
        ToolEvent(name="Bash", index=0, command="pytest", is_test_command=True),
        ToolEvent(name="Edit", index=1),
        ToolEvent(
            name="Bash",
            index=2,
            command="pytest",
            exit_code=0,
            is_test_command=True,
        ),
        ToolEvent(
            name="Bash",
            index=3,
            command="pytest",
            exit_code=1,
            is_test_command=True,
        ),
        ToolEvent(name="Edit", index=4),
        ToolEvent(
            name="Bash",
            index=5,
            command="pytest",
            exit_code=0,
            is_test_command=True,
        ),
        ToolEvent(name="Bash", index=6, command="python app.py"),
        ToolEvent(name="Edit", index=7),
        ToolEvent(name="Bash", index=8, command="python app.py", exit_code=0),
        ToolEvent(
            name="Bash",
            index=9,
            command="python app.py",
            exit_code=0,
            has_error_output=True,
        ),
        ToolEvent(name="Edit", index=10),
        ToolEvent(name="Bash", index=11, command="python app.py", exit_code=0),
        ToolEvent(
            name="Bash",
            index=12,
            command="ruff check .",
            is_lint_command=True,
            has_error_output=True,
        ),
        ToolEvent(name="Write", index=13),
        ToolEvent(
            name="Bash",
            index=14,
            command="ruff check .",
            exit_code=0,
            is_lint_command=True,
        ),
    ]

    metrics = detect_bug_fix_cycles(events)

    assert metrics.total_test_runs == 4
    assert metrics.failed_test_runs == 1
    assert metrics.unknown_test_runs == 1
    assert metrics.test_fix_retest == 1
    assert metrics.run_fix_rerun == 1
    assert metrics.lint_fix_relint == 1
    assert metrics.edits_after_failure == 3


def test_migration_skips_an_exact_existing_solution(tmp_path, monkeypatch):
    problem = tmp_path / "problem"
    source = problem / "checkpoint_1" / "solution"
    destination = problem / "solutions" / "checkpoint_1"
    source.mkdir(parents=True)
    destination.mkdir(parents=True)
    (source / "answer.py").write_bytes(b"answer = 42\n")
    (destination / "answer.py").write_bytes(b"answer = 42\n")

    def should_not_publish(*_args):
        raise AssertionError("exact destination was rewritten")

    monkeypatch.setattr(
        migrate_specs_solutions, "publish_solution", should_not_publish
    )

    result = migrate_problem(problem)

    assert result["solutions"] == []
    assert result["skipped"] == [f"{destination} already exists"]


@pytest.mark.parametrize("old_bytes", [b"answer", b"wrong = 0\n"])
def test_migration_replaces_mismatched_solution_without_temporary_files(
    tmp_path, old_bytes
):
    problem = tmp_path / "problem"
    source = problem / "checkpoint_1" / "solution"
    destination = problem / "solutions" / "checkpoint_1"
    source.mkdir(parents=True)
    destination.mkdir(parents=True)
    (source / "answer.py").write_bytes(b"answer = 42\n")
    (source / "nested").mkdir()
    (source / "nested" / "data.txt").write_bytes(b"complete")
    (destination / "answer.py").write_bytes(old_bytes)

    result = migrate_problem(problem)

    assert result["solutions"] == [f"{source} -> {destination}"]
    assert {
        path.relative_to(destination): path.read_bytes()
        for path in destination.rglob("*")
        if path.is_file()
    } == {
        path.relative_to(source): path.read_bytes()
        for path in source.rglob("*")
        if path.is_file()
    }
    assert not list((problem / "solutions").glob(".checkpoint_1.*"))
