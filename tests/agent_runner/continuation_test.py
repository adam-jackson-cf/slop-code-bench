"""Behaviour tests for controlled continuation (seeded start)."""

from __future__ import annotations

import json
import queue
import shutil
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
import yaml

from slop_code.agent_runner import continuation
from slop_code.agent_runner.agent import Agent
from slop_code.agent_runner.agent import AgentConfigBase
from slop_code.agent_runner.credentials import ProviderCredential
from slop_code.agent_runner.models import AgentCostLimits
from slop_code.agent_runner.models import AgentRunSpec
from slop_code.agent_runner.models import UsageTracker
from slop_code.agent_runner.reporting import CheckpointState
from slop_code.agent_runner.reporting import save_results
from slop_code.agent_runner.state import AgentStateEnum
from slop_code.common.llms import ModelDefinition
from slop_code.common.llms import ThinkingPreset
from slop_code.common.llms import TokenUsage
from slop_code.entrypoints.problem_runner import worker
from slop_code.entrypoints.problem_runner.models import RunTaskConfig
from slop_code.evaluation import PassPolicy
from slop_code.evaluation import ProblemConfig
from slop_code.execution import LocalEnvironmentSpec
from slop_code.execution import Session
from slop_code.execution.models import CommandConfig
from slop_code.execution.models import EnvironmentConfig
from slop_code.execution.models import SetupConfig

RESOURCES = Path(__file__).parent / "resources"
PROBLEM_NAME = "inventory_cli_debug_problem"
TEMPLATE = (
    "{% if is_continuation %}CONTINUATION{% else %}FIRST{% endif %}:"
    " {{ spec[:20] }}"
)


class RecordingAgent(Agent):
    """Agent that records the workspace it starts from and each prompt."""

    def __init__(self, solution: dict[str, str]) -> None:
        super().__init__(
            "recording",
            PROBLEM_NAME,
            AgentCostLimits(step_limit=10, cost_limit=100, net_cost_limit=100),
            None,
            verbose=False,
        )
        self.solution = solution
        self.working_dir: Path | None = None
        self.tasks: list[str] = []
        self.workspace_at_start: list[dict[str, str]] = []

    def setup(self, session: Session) -> None:
        self.working_dir = session.working_dir

    def run(self, task: str) -> None:
        assert self.working_dir is not None
        self.tasks.append(task)
        self.workspace_at_start.append(
            {
                p.name: p.read_text()
                for p in self.working_dir.iterdir()
                if p.is_file()
            }
        )
        for name, content in self.solution.items():
            (self.working_dir / name).write_text(content)
        self.usage.step(cost=1.0, tokens=self.usage.current_tokens)
        self.context = [task]

    def supports_replay(self) -> bool:
        return False

    def reset(self) -> None:
        return

    def save_artifacts(self, path: Path) -> None:
        (path / "context.json").write_text(json.dumps(self.tasks))

    def cleanup(self) -> None:
        return

    @classmethod
    def _from_config(
        cls,
        config: AgentConfigBase,
        model: ModelDefinition,
        credential: ProviderCredential,
        problem_name: str,
        *,
        verbose: bool,
        image: str | None,
        thinking_preset: ThinkingPreset | None = None,
        thinking_max_tokens: int | None = None,
    ) -> Agent:
        raise NotImplementedError


@pytest.fixture
def env_spec() -> LocalEnvironmentSpec:
    return LocalEnvironmentSpec(
        name="local",
        type="local",
        setup=SetupConfig(eval_commands=[]),
        environment=EnvironmentConfig(include_os_env=True),
        commands=CommandConfig(command="uv run", entry_file="{entry_file}.py"),
    )


@pytest.fixture
def three_checkpoint_problem(tmp_path: Path) -> Path:
    """The inventory problem extended to checkpoint_1..3 (3 clones cp2)."""
    root = tmp_path / "problems" / PROBLEM_NAME
    shutil.copytree(
        RESOURCES / PROBLEM_NAME,
        root,
        ignore=shutil.ignore_patterns("__pycache__"),
    )
    shutil.copy(root / "checkpoint_2.md", root / "checkpoint_3.md")
    shutil.copy(
        root / "tests" / "test_checkpoint_2.py",
        root / "tests" / "test_checkpoint_3.py",
    )
    config = yaml.safe_load((root / "config.yaml").read_text())
    config["checkpoints"]["checkpoint_3"] = {"order": 3, "version": 1}
    (root / "config.yaml").write_text(yaml.safe_dump(config))
    return root


@pytest.fixture
def seed_snapshot(tmp_path: Path) -> Path:
    snapshot = tmp_path / "seed_snapshot"
    snapshot.mkdir()
    (snapshot / "seed_marker.txt").write_text("from-seed")
    return snapshot


def _solution() -> dict[str, str]:
    path = RESOURCES / "solutions" / PROBLEM_NAME / "checkpoint_2.py"
    return {"inventory_cli.sh.py": path.read_text()}


def _task_config(
    tmp_path: Path,
    env_spec: LocalEnvironmentSpec,
    seed: continuation.ContinuationSeed,
    *,
    resume: bool = False,
) -> RunTaskConfig:
    return RunTaskConfig(
        problem_base_path=tmp_path / "problems",
        run_dir=tmp_path / "run",
        image="unused",
        env_spec=env_spec,
        agent_config=SimpleNamespace(type="recording", version=None),  # type: ignore[arg-type]
        model_def=SimpleNamespace(name="model"),  # type: ignore[arg-type]
        credential=None,  # type: ignore[arg-type]
        prompt_template=TEMPLATE,
        assessment_policy=PassPolicy.ALL_CASES,
        continue_after_test_failure=True,
        seed=1,
        verbosity=0,
        resume=resume,
        continuation_seed=seed,
    )


def _patch_agent(monkeypatch: pytest.MonkeyPatch, agent: Agent) -> None:
    monkeypatch.setattr(
        worker,
        "Agent",
        SimpleNamespace(from_config=lambda *_a, **_k: agent),
    )


def test_seeded_run_starts_at_start_checkpoint_from_seed_snapshot(
    tmp_path: Path,
    env_spec: LocalEnvironmentSpec,
    three_checkpoint_problem: Path,
    seed_snapshot: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    problem = ProblemConfig.from_yaml(three_checkpoint_problem)
    seed = continuation.build_seed(problem, seed_snapshot, "checkpoint_3")
    agent = RecordingAgent(_solution())
    _patch_agent(monkeypatch, agent)
    config = _task_config(tmp_path, env_spec, seed)
    output_path = config.run_dir / PROBLEM_NAME

    result = worker.run_agent_on_problem(
        problem, PROBLEM_NAME, config, queue.Queue(), output_path
    )

    # Seed (checkpoint_2) is a normal checkpoint directory, evaluated.
    seed_dir = output_path / "checkpoint_2"
    assert (seed_dir / "snapshot" / "seed_marker.txt").read_text() == "from-seed"
    assert (seed_dir / "evaluation.json").is_file()
    assert (seed_dir / "quality_analysis").is_dir()
    seed_result = json.loads((seed_dir / "inference_result.json").read_text())
    assert seed_result["is_seed"] is True
    assert seed_result["usage"]["cost"] == 0
    assert seed_result["usage"]["steps"] == 0
    assert seed_result["seed_digest"] == seed.digest

    # Checkpoints before the seed are absent, not errors.
    assert not (output_path / "checkpoint_1").exists()

    # The agent's only task is checkpoint_3, a continuation, from the seed.
    assert len(agent.tasks) == 1
    assert agent.tasks[0].startswith("CONTINUATION:")
    assert agent.workspace_at_start[0]["seed_marker.txt"] == "from-seed"
    assert (output_path / "checkpoint_3" / "evaluation.json").is_file()

    run_info = yaml.safe_load((output_path / "run_info.yaml").read_text())
    assert run_info["continuation_seed"] == seed.model_dump()
    assert run_info["summary"]["checkpoints"] == {
        "checkpoint_2": CheckpointState.SEED,
        "checkpoint_3": CheckpointState.RAN,
    }
    # Seed cost never counts: only checkpoint_3's agent step is billed.
    assert result["summary"]["total_cost"] == pytest.approx(1.0)


def test_resume_of_seeded_run_does_not_reseed_or_rerun(
    tmp_path: Path,
    env_spec: LocalEnvironmentSpec,
    three_checkpoint_problem: Path,
    seed_snapshot: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    problem = ProblemConfig.from_yaml(three_checkpoint_problem)
    seed = continuation.build_seed(problem, seed_snapshot, "checkpoint_3")
    _patch_agent(monkeypatch, RecordingAgent(_solution()))
    config = _task_config(tmp_path, env_spec, seed)
    output_path = config.run_dir / PROBLEM_NAME
    worker.run_agent_on_problem(
        problem, PROBLEM_NAME, config, queue.Queue(), output_path
    )
    # The seed source disappearing must not matter once materialised.
    shutil.rmtree(seed_snapshot)
    second_agent = RecordingAgent(_solution())
    _patch_agent(monkeypatch, second_agent)

    resumed = worker.run_agent_on_problem(
        problem,
        PROBLEM_NAME,
        _task_config(tmp_path, env_spec, seed, resume=True),
        queue.Queue(),
        output_path,
    )

    assert second_agent.tasks == []
    assert resumed["summary"]["state"] == "completed"
    assert (output_path / "checkpoint_2" / "snapshot" / "seed_marker.txt").exists()


def test_seed_failing_its_own_checkpoint_does_not_fail_the_run(
    tmp_path: Path,
    env_spec: LocalEnvironmentSpec,
    three_checkpoint_problem: Path,
    seed_snapshot: Path,
) -> None:
    problem = ProblemConfig.from_yaml(three_checkpoint_problem)
    seed = continuation.build_seed(problem, seed_snapshot, "checkpoint_3")
    run_spec = AgentRunSpec(
        seed=1,
        template=TEMPLATE,
        problem=problem,
        environment=env_spec,
        image="unused",
        continuation_seed=seed,
    )
    metrics = Mock()
    metrics.state = AgentStateEnum.COMPLETED
    metrics.usage = UsageTracker(
        cost=1.0,
        steps=1,
        net_tokens=TokenUsage(),
        current_tokens=TokenUsage(),
    )
    metrics.started = datetime.now()
    metrics.error_type = None
    metrics.error_message = None
    metrics.error_traceback = None
    failing_seed = SimpleNamespace(
        checkpoint_name="checkpoint_2", passed_policy=False, had_error=False
    )
    passing_agent = SimpleNamespace(
        checkpoint_name="checkpoint_3", passed_policy=True, had_error=False
    )

    run_info = save_results(
        [failing_seed, passing_agent],  # type: ignore[list-item]
        metrics,
        run_spec,
        tmp_path,
    )

    assert run_info["summary"]["passed_policy"] is True
    assert run_info["summary"]["checkpoints"] == {
        "checkpoint_2": CheckpointState.SEED,
        "checkpoint_3": CheckpointState.RAN,
    }


def test_build_seed_records_source_and_content_digest(
    three_checkpoint_problem: Path, seed_snapshot: Path
) -> None:
    problem = ProblemConfig.from_yaml(three_checkpoint_problem)

    seed = continuation.build_seed(problem, seed_snapshot, "checkpoint_3")
    assert seed.source_path == str(seed_snapshot.resolve())
    assert seed.start_checkpoint == "checkpoint_3"
    assert seed.digest == continuation.directory_digest(seed_snapshot)

    (seed_snapshot / "seed_marker.txt").write_text("changed")
    assert continuation.directory_digest(seed_snapshot) != seed.digest


@pytest.mark.parametrize(
    ("start", "message"),
    [
        ("checkpoint_9", "Unknown start checkpoint"),
        ("checkpoint_1", "first checkpoint"),
    ],
)
def test_build_seed_rejects_invalid_start_checkpoint(
    three_checkpoint_problem: Path,
    seed_snapshot: Path,
    start: str,
    message: str,
) -> None:
    problem = ProblemConfig.from_yaml(three_checkpoint_problem)
    with pytest.raises(continuation.ContinuationSeedError, match=message):
        continuation.build_seed(problem, seed_snapshot, start)


def test_build_seed_rejects_missing_snapshot(
    three_checkpoint_problem: Path, tmp_path: Path
) -> None:
    problem = ProblemConfig.from_yaml(three_checkpoint_problem)
    with pytest.raises(continuation.ContinuationSeedError, match="directory"):
        continuation.build_seed(problem, tmp_path / "nope", "checkpoint_2")


def test_create_problem_reports_treat_absent_leading_checkpoints_as_absent(
    tmp_path: Path,
    env_spec: LocalEnvironmentSpec,
    three_checkpoint_problem: Path,
    seed_snapshot: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from slop_code.entrypoints.evaluation import metrics as report_metrics

    problem = ProblemConfig.from_yaml(three_checkpoint_problem)
    seed = continuation.build_seed(problem, seed_snapshot, "checkpoint_3")
    _patch_agent(monkeypatch, RecordingAgent(_solution()))
    config = _task_config(tmp_path, env_spec, seed)
    output_path = config.run_dir / PROBLEM_NAME
    worker.run_agent_on_problem(
        problem, PROBLEM_NAME, config, queue.Queue(), output_path
    )

    reports, errors = report_metrics.create_problem_reports(
        output_path, problem
    )

    assert errors == []
    assert [r["checkpoint"] for r in reports] == ["checkpoint_2", "checkpoint_3"]
    assert reports[0]["is_first"] is True
    assert reports[0]["state"] == CheckpointState.SEED
    ledger = [
        reports[1][key]
        for key in (
            "regression_retained",
            "regression_broken",
            "regression_repaired",
            "regression_still_failing",
        )
    ]
    assert None not in ledger
    assert sum(ledger) == 12

