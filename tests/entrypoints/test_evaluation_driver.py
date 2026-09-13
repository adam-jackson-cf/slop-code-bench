from __future__ import annotations

from concurrent.futures import Future
from pathlib import Path
from types import SimpleNamespace
from typing import cast

import pytest
import yaml
from rich.console import Console

import slop_code.entrypoints.evaluation.driver as driver
import slop_code.entrypoints.evaluation.metrics as metrics
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


@pytest.mark.parametrize(
    ("scheduled", "successful_counts", "expected_pass_rate"),
    [
        (
            ("first", "second"),
            {"first": (1, 1), "second": (1, 1)},
            1.0,
        ),
        (
            ("first", "second"),
            {"first": (1, 2)},
            0.5,
        ),
        (("first", "second"), {}, None),
        ((), {}, None),
    ],
    ids=("complete", "partial", "all-failed", "missing-snapshot"),
)
def test_evaluate_replaces_prior_summary_for_every_requested_problem(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    scheduled: tuple[str, ...],
    successful_counts: dict[str, tuple[int, int]],
    expected_pass_rate: float | None,
) -> None:
    submission_dir = tmp_path / "problem"
    submission_dir.mkdir()
    (submission_dir / "run_info.yaml").write_text(
        """
assessment_policy: all-cases
summary:
  checkpoints:
    first: complete
    second: complete
  passed: true
  passed_policy: true
  overall_pass_rate: 1.0
"""
    )
    problem = SimpleNamespace(
        name="problem",
        checkpoints={
            "first": SimpleNamespace(order=1),
            "second": SimpleNamespace(order=2),
        },
        load_checkpoint=lambda checkpoint_name: SimpleNamespace(
            name=checkpoint_name
        ),
    )

    class ImmediateExecutor:
        def __init__(self, **_: object) -> None:
            pass

        def __enter__(self):
            return self

        def __exit__(self, *_: object) -> None:
            pass

        def submit(self, callback, *args: object) -> Future:
            future: Future = Future()
            future.set_result(callback(*args))
            return future

    def fake_gather(**_: object):
        return [
            (
                checkpoint_name,
                submission_dir / checkpoint_name,
                tmp_path / checkpoint_name / "snapshot",
            )
            for checkpoint_name in scheduled
        ]

    def fake_worker(
        _snapshot: Path,
        _save_dir: Path,
        checkpoint: SimpleNamespace,
        current_problem: SimpleNamespace,
        *_: object,
    ) -> object:
        counts = successful_counts.get(checkpoint.name)
        if counts is None:
            return driver.EvaluationResult(
                problem_name=current_problem.name,
                checkpoint_name=checkpoint.name,
                success=False,
                error_type="EvaluationError",
                error_message="failed",
            )
        passed, total = counts
        return SimpleNamespace(
            success=True,
            result=SimpleNamespace(
                problem_name=current_problem.name,
                checkpoint_name=checkpoint.name,
                report=SimpleNamespace(
                    pass_counts={driver.GroupType.CORE: passed},
                    total_counts={driver.GroupType.CORE: total},
                ),
                quality=SimpleNamespace(),
            ),
        )

    monkeypatch.setattr(driver, "ProcessPoolExecutor", ImmediateExecutor)
    monkeypatch.setattr(driver, "gather_checkpoint_directories", fake_gather)
    monkeypatch.setattr(driver, "_evaluate_checkpoint_worker", fake_worker)

    _, batch_summary = driver.evaluate(
        [(cast(ProblemConfig, problem), submission_dir)],
        environment=cast(EnvironmentSpec, SimpleNamespace()),
        num_workers=1,
    )

    persisted = yaml.safe_load((submission_dir / "run_info.yaml").read_text())[
        "summary"
    ]
    assert batch_summary.successful == len(successful_counts)
    assert persisted["passed"] is (expected_pass_rate == 1.0)
    assert persisted["passed_policy"] is (expected_pass_rate == 1.0)
    if expected_pass_rate is None:
        assert "overall_pass_rate" not in persisted
    else:
        assert persisted["overall_pass_rate"] == expected_pass_rate


def test_create_problem_reports_continues_after_checkpoint_metrics_errors(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    submission_dir = tmp_path / "submission"
    submission_dir.mkdir()
    (submission_dir / "problem.yaml").write_text("version: 3\n")
    for checkpoint_name in ("first", "broken", "final"):
        (submission_dir / checkpoint_name).mkdir()
    problem = SimpleNamespace(
        name="problem",
        checkpoints={
            "first": SimpleNamespace(order=1),
            "missing": SimpleNamespace(order=2),
            "broken": SimpleNamespace(order=3),
            "final": SimpleNamespace(order=4),
        },
    )
    calls: list[tuple[str, object, Path | None]] = []

    def fake_metrics(
        checkpoint_dir: Path,
        *,
        prior_metrics: object,
        prior_checkpoint_dir: Path | None,
        **_: object,
    ) -> dict[str, str]:
        calls.append((checkpoint_dir.name, prior_metrics, prior_checkpoint_dir))
        if checkpoint_dir.name == "broken":
            raise metrics.MetricsError("metric collection failed")
        return {"metric": checkpoint_dir.name}

    monkeypatch.setattr(metrics, "get_checkpoint_metrics", fake_metrics)

    reports, errors = metrics.create_problem_reports(
        submission_dir, cast(ProblemConfig, problem)
    )

    assert [report["checkpoint"] for report in reports] == ["first", "final"]
    assert errors == [
        ("missing", f"File not found: {submission_dir / 'missing'}"),
        ("broken", "metric collection failed"),
    ]
    assert calls == [
        ("first", None, None),
        ("broken", {"metric": "first"}, submission_dir / "first"),
        ("final", {"metric": "first"}, submission_dir / "first"),
    ]


@pytest.mark.parametrize(
    ("contents", "expected_state"),
    [
        (None, None),
        ("summary: [unterminated", None),
        ("- not-a-mapping", None),
        ("summary:\n  - not-a-mapping", None),
        ("summary:\n  checkpoints:\n    - not-a-mapping", None),
        (
            """
seed: 7
assessment_policy: all-cases
skip_evaluation: false
summary:
  state: complete
  total_cost: 1.5
  checkpoints:
    first: complete
""",
            "complete",
        ),
    ],
    ids=(
        "missing",
        "syntactically-invalid",
        "invalid-root",
        "invalid-summary",
        "invalid-checkpoints",
        "valid",
    ),
)
def test_get_run_summary_rejects_invalid_yaml_metadata(
    tmp_path: Path,
    contents: str | None,
    expected_state: str | None,
) -> None:
    submission_dir = tmp_path / "submission"
    submission_dir.mkdir()
    if contents is not None:
        (submission_dir / "run_info.yaml").write_text(contents)

    summary = metrics.get_run_summary(submission_dir)

    if expected_state is None:
        assert summary is None
    else:
        assert summary is not None
        assert summary["seed"] == 7
        assert summary["assessment_policy"] == "all-cases"
        assert summary["state"] == expected_state
        assert summary["total_cost"] == 1.5
        assert summary["checkpoints"] == {"first": "complete"}
