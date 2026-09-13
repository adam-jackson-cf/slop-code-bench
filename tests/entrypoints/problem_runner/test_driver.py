from __future__ import annotations

import json
import queue
from collections.abc import Sequence
from concurrent.futures import Future
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from typing import TYPE_CHECKING, cast

import pytest

from slop_code.agent_runner import AgentStateEnum
from slop_code.agent_runner.models import UsageTracker
from slop_code.agent_runner.reporting import CheckpointEvalResult
from slop_code.agent_runner.reporting import MetricsTracker
from slop_code.common import EVALUATION_FILENAME
from slop_code.common import INFERENCE_RESULT_FILENAME
from slop_code.common.llms import TokenUsage
from slop_code.entrypoints.problem_runner import driver
from slop_code.entrypoints.problem_runner.driver import (
    _prepopulate_completed_states,
)
from slop_code.entrypoints.problem_runner.driver import _run_problems
from slop_code.entrypoints.problem_runner.models import TaskResult
from slop_code.entrypoints.problem_runner.state import ProblemStateTracker
from slop_code.evaluation import GroupType

if TYPE_CHECKING:
    from slop_code.entrypoints.problem_runner.models import RunTaskConfig


@dataclass(frozen=True)
class _Config:
    run_dir: Path


def _write_checkpoint_artifacts(
    checkpoint_dir: Path,
    *,
    cost: float,
    steps: int,
    core_pass: int,
    core_total: int,
    functionality_pass: int = 0,
    functionality_total: int = 0,
    regression_pass: int = 0,
    regression_total: int = 0,
) -> None:
    checkpoint_dir.mkdir(parents=True, exist_ok=True)
    inference = {
        "usage": {
            "cost": cost,
            "steps": steps,
            "net_tokens": {"input": 100, "output": 50},
        }
    }
    with (checkpoint_dir / INFERENCE_RESULT_FILENAME).open("w") as f:
        json.dump(inference, f)

    evaluation = {
        "schema_version": 1,
        "problem_name": "p",
        "problem_version": 1,
        "checkpoint_name": checkpoint_dir.name,
        "checkpoint_version": 1,
        "duration": 1.0,
        "entrypoint": "python main.py",
        "tests": [],
        "pass_counts": {
            GroupType.CORE.value: core_pass,
            GroupType.FUNCTIONALITY.value: functionality_pass,
            GroupType.REGRESSION.value: regression_pass,
            GroupType.ERROR.value: 0,
        },
        "total_counts": {
            GroupType.CORE.value: core_total,
            GroupType.FUNCTIONALITY.value: functionality_total,
            GroupType.REGRESSION.value: regression_total,
            GroupType.ERROR.value: 0,
        },
        "pytest_exit_code": 0,
        "pytest_collected": core_total + functionality_total + regression_total,
        "infrastructure_failure": False,
    }
    with (checkpoint_dir / EVALUATION_FILENAME).open("w") as f:
        json.dump(evaluation, f)


def _make_config(run_dir: Path) -> RunTaskConfig:
    return cast("RunTaskConfig", _Config(run_dir=run_dir))


def test_prepopulate_loads_cost_and_passed_counts(tmp_path: Path) -> None:
    problem = "p"
    problem_dir = tmp_path / problem
    _write_checkpoint_artifacts(
        problem_dir / "checkpoint_1",
        cost=1.5,
        steps=10,
        core_pass=3,
        core_total=3,
    )
    _write_checkpoint_artifacts(
        problem_dir / "checkpoint_2",
        cost=2.25,
        steps=20,
        core_pass=2,
        core_total=2,
        functionality_pass=1,
        functionality_total=1,
    )

    checkpoint_map: dict[str, Sequence[str]] = {
        problem: ["checkpoint_1", "checkpoint_2"]
    }
    states = ProblemStateTracker([problem], checkpoint_map)

    _prepopulate_completed_states(
        states, [problem], _make_config(tmp_path), checkpoint_map
    )

    state = states[problem]
    assert state.state == AgentStateEnum.COMPLETED
    assert state.overall_usage is not None
    assert state.overall_usage.cost == 3.75
    assert state.overall_usage.steps == 30
    assert state.total_checkpoints_evaluated == 2
    # Both checkpoints are fully-passed including functionality / regression
    assert state.checkpoints_passed == 2
    assert state.checkpoints_iso_passed == 2
    assert state.checkpoints_core_solved == 2


@pytest.mark.parametrize(
    ("functionality_total", "regression_total", "iso_passed"),
    [(1, 0, 0), (0, 1, 1)],
)
def test_prepopulate_distinguishes_core_from_strict_pass(
    tmp_path: Path,
    functionality_total: int,
    regression_total: int,
    iso_passed: int,
) -> None:
    problem = "p"
    problem_dir = tmp_path / problem
    _write_checkpoint_artifacts(
        problem_dir / "checkpoint_1",
        cost=1.0,
        steps=5,
        core_pass=3,
        core_total=3,
        functionality_total=functionality_total,
        regression_total=regression_total,
    )

    checkpoint_map: dict[str, Sequence[str]] = {problem: ["checkpoint_1"]}
    states = ProblemStateTracker([problem], checkpoint_map)

    _prepopulate_completed_states(
        states, [problem], _make_config(tmp_path), checkpoint_map
    )

    state = states[problem]
    assert state.total_checkpoints_evaluated == 1
    assert state.checkpoints_passed == 0
    assert state.checkpoints_iso_passed == iso_passed
    assert state.checkpoints_core_solved == 1


def test_prepopulate_handles_missing_evaluation(tmp_path: Path) -> None:
    problem = "p"
    problem_dir = tmp_path / problem
    (problem_dir / "checkpoint_1").mkdir(parents=True)
    with (problem_dir / "checkpoint_1" / INFERENCE_RESULT_FILENAME).open(
        "w"
    ) as f:
        json.dump({"usage": {"cost": 0.5, "steps": 1}}, f)

    checkpoint_map: dict[str, Sequence[str]] = {problem: ["checkpoint_1"]}
    states = ProblemStateTracker([problem], checkpoint_map)

    _prepopulate_completed_states(
        states, [problem], _make_config(tmp_path), checkpoint_map
    )

    state = states[problem]
    # Cost still aggregates from inference_result.json
    assert state.overall_usage is not None
    assert state.overall_usage.cost == 0.5
    # Missing evaluation.json -> record_checkpoint_result(None) counts as not-passed
    assert state.total_checkpoints_evaluated == 1
    assert state.checkpoints_passed == 0
    assert state.checkpoints_iso_passed == 0
    assert state.checkpoints_core_solved == 0


def test_prepopulate_empty_completed_list_is_noop(tmp_path: Path) -> None:
    checkpoint_map: dict[str, Sequence[str]] = {"p": ["checkpoint_1"]}
    states = ProblemStateTracker(["p"], checkpoint_map)

    _prepopulate_completed_states(
        states, [], _make_config(tmp_path), checkpoint_map
    )

    state = states["p"]
    assert state.state == AgentStateEnum.PENDING
    assert state.overall_usage is None
    assert state.total_checkpoints_evaluated == 0


def test_run_problems_recycles_workers_between_problems(
    monkeypatch,
) -> None:
    executor_kwargs: dict[str, int | None] = {}

    class FakeExecutor:
        def __init__(
            self,
            *,
            max_workers: int | None = None,
            max_tasks_per_child: int | None = None,
        ) -> None:
            executor_kwargs["max_workers"] = max_workers
            executor_kwargs["max_tasks_per_child"] = max_tasks_per_child

        def __enter__(self) -> FakeExecutor:
            return self

        def __exit__(self, *args: object) -> None:
            pass

        def submit(
            self,
            fn: object,
            problem_name: str,
            config: object,
            progress_queue: queue.Queue,
        ) -> Future[TaskResult]:
            future: Future[TaskResult] = Future()
            future.set_result(
                TaskResult(problem_name=problem_name, success=True)
            )
            return future

    monkeypatch.setattr(
        driver.concurrent.futures, "ProcessPoolExecutor", FakeExecutor
    )

    results = _run_problems(
        ["p1", "p2"],
        cast("RunTaskConfig", object()),
        num_workers=3,
        progress_queue=queue.Queue(),
        progress_display=None,
        problem_states=ProblemStateTracker(["p1", "p2"], {}),
    )

    assert [result.problem_name for result in results] == ["p1", "p2"]
    assert executor_kwargs["max_workers"] == 3
    assert executor_kwargs["max_tasks_per_child"] == 1


def _progress_update(
    state: AgentStateEnum,
    checkpoint: str,
    *,
    cost: float,
    evaluated: int,
) -> tuple[str, UsageTracker, MetricsTracker]:
    usage = UsageTracker(
        cost=cost,
        steps=evaluated,
        current_tokens=TokenUsage(),
        net_tokens=TokenUsage(),
    )
    metrics = MetricsTracker(
        state=state,
        current_checkpoint=checkpoint,
        usage=usage.model_copy(deep=True),
        started=datetime.now(),
        checkpoint_started=datetime.now(),
    )
    for index in range(evaluated):
        metrics.checkpoint_results.append(
            CheckpointEvalResult(
                name=f"checkpoint_{index}",
                passed=True,
                iso_passed=True,
                core_passed=True,
            )
        )
    return "p1", usage, metrics


def test_run_problems_drains_progress_after_futures_complete(
    monkeypatch,
) -> None:
    before_completion = _progress_update(
        AgentStateEnum.RUNNING, "checkpoint_1", cost=1.0, evaluated=1
    )
    final_update = _progress_update(
        AgentStateEnum.COMPLETED, "checkpoint_2", cost=2.0, evaluated=2
    )
    queued_updates = [before_completion]
    future: Future[TaskResult] = Future()

    class FakeQueue:
        def get(
            self, *, timeout: float
        ) -> tuple[str, UsageTracker, MetricsTracker]:
            update = queued_updates.pop(0)
            future.set_result(TaskResult(problem_name="p1", success=True))
            queued_updates.append(final_update)
            return update

        def get_nowait(self) -> tuple[str, UsageTracker, MetricsTracker]:
            if not queued_updates:
                raise queue.Empty
            return queued_updates.pop(0)

    class FakeExecutor:
        def __init__(self, **_: object) -> None:
            pass

        def __enter__(self) -> FakeExecutor:
            return self

        def __exit__(self, *args: object) -> None:
            pass

        def submit(self, *args: object) -> Future[TaskResult]:
            return future

    monkeypatch.setattr(
        driver.concurrent.futures, "ProcessPoolExecutor", FakeExecutor
    )
    states = ProblemStateTracker(
        ["p1"], {"p1": ["checkpoint_1", "checkpoint_2"]}
    )

    results = _run_problems(
        ["p1"],
        cast("RunTaskConfig", object()),
        num_workers=1,
        progress_queue=cast(queue.Queue, FakeQueue()),
        progress_display=None,
        problem_states=states,
    )

    assert results == [future.result()]
    assert states["p1"].state == AgentStateEnum.COMPLETED
    assert states["p1"].overall_usage is not None
    assert states["p1"].overall_usage.cost == 2.0
    assert states["p1"].total_checkpoints_evaluated == 2


@pytest.mark.parametrize("setup_failure", ["directory", "logging", "config"])
def test_run_problem_worker_returns_setup_failures(
    monkeypatch, tmp_path: Path, setup_failure: str
) -> None:
    config = SimpleNamespace(
        run_dir=tmp_path / "runs",
        problem_base_path=tmp_path / "problems",
        live_progress=False,
        debug=True,
    )
    monkeypatch.setattr(
        driver.evaluation.ProblemConfig, "from_yaml", lambda _: object()
    )
    monkeypatch.setattr(
        driver,
        "run_agent_on_problem",
        lambda **_: {"summary": {"state": "completed"}},
    )
    successful_result = driver._run_problem_worker(
        "sibling", cast("RunTaskConfig", config), queue.Queue()
    )
    if setup_failure == "directory":

        class FailingPath:
            def __truediv__(self, _: str) -> FailingPath:
                return self

            def mkdir(self, **_: object) -> None:
                raise OSError("directory setup failed")

        config.run_dir = FailingPath()
    elif setup_failure == "logging":
        monkeypatch.setattr(
            driver,
            "setup_problem_logging",
            lambda *args, **kwargs: (_ for _ in ()).throw(
                RuntimeError("logging setup failed")
            ),
        )
        config.debug = False
    else:
        monkeypatch.setattr(
            driver.evaluation.ProblemConfig,
            "from_yaml",
            lambda _: (_ for _ in ()).throw(ValueError("config setup failed")),
        )

    failed_result = driver._run_problem_worker(
        "broken", cast("RunTaskConfig", config), queue.Queue()
    )
    assert [
        result.success for result in (successful_result, failed_result)
    ] == [
        True,
        False,
    ]
    result = failed_result
    assert not result.success
    assert result.error_type is not None
    assert result.error_message is not None
    assert result.error_traceback is not None


def test_run_problem_worker_separates_execution_from_policy_success(
    monkeypatch, tmp_path: Path
) -> None:
    config = SimpleNamespace(
        run_dir=tmp_path / "runs",
        problem_base_path=tmp_path / "problems",
        live_progress=False,
        debug=True,
    )
    monkeypatch.setattr(
        driver.evaluation.ProblemConfig, "from_yaml", lambda _: object()
    )
    summaries = iter(
        [
            {"summary": {"state": "completed", "passed_policy": True}},
            {"summary": {"state": "completed", "passed_policy": False}},
            {
                "summary": {
                    "state": "failed",
                    "passed_policy": False,
                    "error_message": "execution failed",
                }
            },
        ]
    )
    monkeypatch.setattr(
        driver, "run_agent_on_problem", lambda **_: next(summaries)
    )

    results = [
        driver._run_problem_worker(
            name, cast("RunTaskConfig", config), queue.Queue()
        )
        for name in ("normal", "resume_skip", "failure")
    ]

    assert [result.success for result in results] == [True, True, False]
    assert results[2].error_message == "execution failed"
