from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import cast

import pytest
from rich.console import Console

import slop_code.entrypoints.evaluation.driver as driver
from slop_code.entrypoints.evaluation.driver import maybe_progress_bar
from slop_code.evaluation import CheckpointConfig
from slop_code.evaluation import ProblemConfig
from slop_code.execution import EnvironmentSpec


def test_maybe_progress_bar_initializes_core_percent_field() -> None:
    console = Console(record=True)

    with maybe_progress_bar(
        description="Evaluating checkpoints",
        num_tasks=3,
        enabled=True,
        console=console,
    ) as bar:
        task = bar.progress.tasks[0]
        assert task.fields["core_pct"] == "0.0%"


def test_maybe_progress_bar_updates_core_percent_field() -> None:
    console = Console(record=True)

    with maybe_progress_bar(
        description="Evaluating checkpoints",
        num_tasks=3,
        enabled=True,
        console=console,
    ) as bar:
        bar.update(current=2, core_pct="66.7%")
        task = bar.progress.tasks[0]
        assert task.completed == 2
        assert task.fields["core_pct"] == "66.7%"


def test_disabled_progress_bar_accepts_core_percent_update() -> None:
    console = Console(record=True)

    with maybe_progress_bar(
        description="Evaluating checkpoints",
        num_tasks=1,
        enabled=False,
        console=console,
    ) as bar:
        bar.update(current=1, core_pct="100.0%")


def test_evaluate_checkpoint_derives_cache_parent_from_relative_save_dir(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    class StopEvaluationError(Exception):
        pass

    def stop_after_capture(**kwargs: object) -> None:
        captured.update(kwargs)
        raise StopEvaluationError

    monkeypatch.setattr(driver, "run_checkpoint_pytest", stop_after_capture)

    with pytest.raises(StopEvaluationError):
        driver.evaluate_checkpoint(
            snapshot=Path("snapshot"),
            save_dir=Path("results"),
            checkpoint=cast(
                CheckpointConfig, SimpleNamespace(name="checkpoint")
            ),
            problem=cast(ProblemConfig, SimpleNamespace(name="problem")),
            environment=cast(EnvironmentSpec, SimpleNamespace()),
        )

    assert captured["evaluator_environment_parent"] == (
        Path.cwd().parent / "measurement_analysis"
    )
    assert captured["measurement_coverage"] is True
