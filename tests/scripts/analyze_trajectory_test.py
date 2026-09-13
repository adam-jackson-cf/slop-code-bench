"""Regression tests for trajectory failure classification."""

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
ToolEvent = analyze_trajectory.ToolEvent
detect_bug_fix_cycles = analyze_trajectory.detect_bug_fix_cycles
is_failure = analyze_trajectory.is_failure


@pytest.mark.parametrize(
    ("exit_code", "has_error_output", "expected"),
    [
        (0, False, False),
        (1, False, True),
        (None, False, False),
        (None, True, True),
    ],
)
def test_failure_requires_conclusive_evidence(
    exit_code, has_error_output, expected
) -> None:
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


def test_unknown_test_run_is_not_counted_as_a_failure() -> None:
    metrics = detect_bug_fix_cycles(
        [
            ToolEvent(
                name="Bash",
                index=0,
                command="pytest",
                is_test_command=True,
            )
        ]
    )

    assert metrics.total_test_runs == 1
    assert metrics.failed_test_runs == 0
    assert metrics.unknown_test_runs == 1
