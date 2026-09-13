"""Unit tests for the OpenHands agent cutover behavior."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace
from typing import cast

import pytest

from slop_code.agent_runner.agents.cli_utils import AgentCommandResult
from slop_code.agent_runner.agents.openhands import OpenHandsAgent
from slop_code.agent_runner.agents.openhands import OpenHandsConfig
from slop_code.agent_runner.agents.openhands import OpenHandsParser
from slop_code.agent_runner.agents.utils import HOME_PATH
from slop_code.agent_runner.credentials import CredentialType
from slop_code.agent_runner.credentials import ProviderCredential
from slop_code.agent_runner.models import AgentCostLimits
from slop_code.agent_runner.models import AgentError
from slop_code.agent_runner.trajectory import AgentStep
from slop_code.agent_runner.trajectory import ToolUseStep
from slop_code.common.llms import APIPricing
from slop_code.common.llms import ModelDefinition
from slop_code.execution import Session
from slop_code.execution.runtime import RuntimeResult


class FakeRuntime:
    """Minimal runtime stub for setup/cleanup tests."""

    def __init__(self) -> None:
        self.cleaned = False

    def cleanup(self) -> None:
        self.cleaned = True


@dataclass
class FakeSession:
    """Fake session that captures spawn kwargs."""

    runtime: FakeRuntime
    working_dir: Path
    spec: object | None = None
    last_spawn_env_vars: dict[str, str] | None = None
    last_spawn_mounts: dict[str, dict[str, str] | str] | None = None

    def spawn(self, **kwargs: object) -> FakeRuntime:
        self.last_spawn_env_vars = cast(
            "dict[str, str] | None", kwargs.get("env_vars")
        )
        self.last_spawn_mounts = cast(
            "dict[str, dict[str, str] | str] | None", kwargs.get("mounts")
        )
        return self.runtime


def _make_credential(provider: str, key_name: str) -> ProviderCredential:
    return ProviderCredential(
        provider=provider,
        value="test-key",
        source=key_name,
        destination_key=key_name,
        credential_type=CredentialType.ENV_VAR,
    )


def test_from_config_uses_provider_slug_and_openrouter_base_url() -> None:
    config = OpenHandsConfig(
        type="openhands",
        version="1.1.0",
        cost_limits=AgentCostLimits(
            step_limit=0,
            cost_limit=10.0,
            net_cost_limit=0.0,
        ),
    )
    model = ModelDefinition(
        internal_name="gpt-5",
        provider="openai",
        pricing=APIPricing(input=1.0, output=2.0),
        provider_slugs={"openrouter": "openai/gpt-5"},
    )
    credential = _make_credential("openrouter", "OPENROUTER_API_KEY")

    agent = OpenHandsAgent._from_config(
        config=config,
        model=model,
        credential=credential,
        problem_name="p",
        verbose=False,
        image="img",
    )
    cast_agent = cast("OpenHandsAgent", agent)

    assert cast_agent.model == "openai/gpt-5"
    assert cast_agent.base_url == "https://openrouter.ai/api/v1"


def test_prepare_runtime_execution_uses_local_runtime_contract() -> None:
    agent = OpenHandsAgent(
        problem_name="p",
        verbose=False,
        image="img",
        cost_limits=AgentCostLimits(
            step_limit=12,
            cost_limit=3.5,
            net_cost_limit=0.0,
        ),
        pricing=APIPricing(input=1.0, output=1.0),
        credential=_make_credential("openai", "OPENAI_API_KEY"),
        model="gpt-5",
        base_url="https://api.openai.com/v1",
        timeout=None,
        env={},
    )

    command, env = agent._prepare_runtime_execution("solve this task")

    assert env["RUNTIME"] == "local"
    assert env["SU_TO_USER"] == "false"
    assert env["FILE_STORE"] == "local"
    assert env["SAVE_TRAJECTORY_PATH"] == "/openhands/output/trajectory.json"
    assert env["LLM_MODEL"] == "openai/gpt-5"
    assert env["LLM_BASE_URL"] == "https://api.openai.com/v1"
    assert env["MAX_ITERATIONS"] == "12"
    assert env["MAX_BUDGET_PER_TASK"] == "3.5"
    assert "SANDBOX_VOLUMES=${PWD}:/workspace:rw" in command
    assert "/opt/openhands-venv/bin/python -u -m openhands.core.main" in command
    assert "--task='solve this task'" in command


def test_reset_clears_output_dir_between_checkpoints(tmp_path: Path) -> None:
    runtime = FakeRuntime()
    session = FakeSession(runtime=runtime, working_dir=tmp_path)
    agent = OpenHandsAgent(
        problem_name="p",
        verbose=False,
        image="img",
        cost_limits=AgentCostLimits(
            step_limit=0,
            cost_limit=10.0,
            net_cost_limit=0.0,
        ),
        pricing=APIPricing(input=1.0, output=1.0),
        credential=_make_credential("openai", "OPENAI_API_KEY"),
        model="gpt-5",
        base_url=None,
        timeout=None,
        env={},
    )

    agent.setup(cast("Session", session))
    output_dir = agent._get_output_dir()
    (output_dir / "trajectory.json").write_text("[]")
    nested_dir = output_dir / "completions"
    nested_dir.mkdir()
    (nested_dir / "a.json").write_text("{}")
    agent._last_prompt = "stale"
    agent._events = [{"event": 1}]
    agent._stdout_lines = ["line"]

    agent.reset()

    assert list(output_dir.iterdir()) == []
    assert agent._last_prompt == ""
    assert agent._events == []
    assert agent._stdout_lines == []
    agent.cleanup()


def test_save_artifacts_copies_output_tree_and_trajectory_alias(
    tmp_path: Path,
) -> None:
    runtime = FakeRuntime()
    session = FakeSession(runtime=runtime, working_dir=tmp_path)
    agent = OpenHandsAgent(
        problem_name="p",
        verbose=False,
        image="img",
        cost_limits=AgentCostLimits(
            step_limit=0,
            cost_limit=10.0,
            net_cost_limit=0.0,
        ),
        pricing=APIPricing(input=1.0, output=1.0),
        credential=_make_credential("openai", "OPENAI_API_KEY"),
        model="gpt-5",
        base_url=None,
        timeout=None,
        env={},
    )
    agent.setup(cast("Session", session))
    output_dir = agent._get_output_dir()
    (output_dir / "openhands.trajectory.json").write_text('[{"ok": true}]')
    completion_dir = output_dir / "completions"
    completion_dir.mkdir()
    (completion_dir / "1.json").write_text('{"x": 1}')
    agent._last_prompt = "do it"
    agent._last_command = AgentCommandResult(
        result=None,
        steps=[],
        usage_totals={},
        stdout="stdout text",
        stderr="stderr text",
    )

    save_dir = tmp_path / "artifacts"
    agent.save_artifacts(save_dir)

    assert (save_dir / "completions" / "1.json").exists()
    assert (save_dir / "trajectory.json").read_text() == '[{"ok": true}]'
    assert (save_dir / "prompt.txt").read_text() == "do it"
    assert (save_dir / "stdout.log").read_text() == "stdout text"
    assert (save_dir / "stderr.log").read_text() == "stderr text"
    agent.cleanup()


def test_setup_passes_home_override_and_mounts(tmp_path: Path) -> None:
    runtime = FakeRuntime()
    session = FakeSession(runtime=runtime, working_dir=tmp_path)
    agent = OpenHandsAgent(
        problem_name="p",
        verbose=False,
        image="img",
        cost_limits=AgentCostLimits(
            step_limit=0,
            cost_limit=10.0,
            net_cost_limit=0.0,
        ),
        pricing=APIPricing(input=1.0, output=1.0),
        credential=_make_credential("openai", "OPENAI_API_KEY"),
        model="gpt-5",
        base_url=None,
        timeout=None,
        env={},
    )

    agent.setup(cast("Session", session))

    assert session.last_spawn_env_vars is not None
    assert session.last_spawn_env_vars["HOME"] == HOME_PATH
    assert session.last_spawn_mounts is not None
    assert any(
        isinstance(mapping, dict) and mapping.get("bind") == "/openhands/output"
        for mapping in session.last_spawn_mounts.values()
    )
    agent.cleanup()


def test_parser_uses_last_cumulative_metrics_entry(tmp_path: Path) -> None:
    trajectory_file = tmp_path / "trajectory.json"
    trajectory_file.write_text(
        json.dumps(
            [
                {
                    "llm_metrics": {
                        "accumulated_cost": 0.10,
                        "accumulated_token_usage": {
                            "prompt_tokens": 100,
                            "completion_tokens": 20,
                        },
                    },
                },
                {
                    "llm_metrics": {
                        "accumulated_cost": 0.25,
                        "accumulated_token_usage": {
                            "prompt_tokens": 250,
                            "completion_tokens": 50,
                        },
                    },
                },
            ]
        )
    )

    trajectory = OpenHandsParser().parse(tmp_path)

    assert trajectory.metadata["accumulated_cost"] == 0.25
    assert trajectory.metadata["total_tokens"] == {
        "input": 250,
        "output": 50,
    }


def test_parser_processes_action_events_without_is_step(
    tmp_path: Path,
) -> None:
    events_file = tmp_path / "events.jsonl"
    events = [
        {"action": "message", "args": {"content": "Working on it."}},
        {"action": "run", "args": {"command": "pwd"}},
        {"action": "execute_bash", "args": {"command": "ls"}},
        {"action": "write", "args": {"path": "a.py", "content": "x = 1"}},
        {"action": "str_replace_editor", "args": {"path": "a.py"}},
        {"action": "read", "args": {"path": "a.py"}},
        {"action": "browse", "args": {"url": "https://example.com"}},
        {"action": "custom_tool", "args": {"key": "value"}},
    ]
    events_file.write_text(
        "".join(f"{json.dumps(event)}\n" for event in events)
    )

    parser = OpenHandsParser()

    assert parser.can_parse(tmp_path)
    trajectory = parser.parse(tmp_path)
    assert len(trajectory.steps) == 8
    assert isinstance(trajectory.steps[0], AgentStep)
    assert trajectory.steps[0].content == "Working on it."
    tool_steps = [
        step for step in trajectory.steps[1:] if isinstance(step, ToolUseStep)
    ]
    assert len(tool_steps) == 7
    assert [step.type for step in tool_steps] == [
        "bash",
        "bash",
        "edit",
        "edit",
        "read",
        "browse",
        "custom_tool",
    ]


@pytest.mark.parametrize("outcome", ["completed", "timed_out"])
def test_run_records_final_trajectory_usage_before_timeout(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    outcome: str,
) -> None:
    timed_out = outcome == "timed_out"
    runtime = FakeRuntime()
    session = FakeSession(
        runtime=runtime,
        working_dir=tmp_path,
        spec=SimpleNamespace(type="docker"),
    )
    agent = OpenHandsAgent(
        problem_name="p",
        verbose=False,
        image="img",
        cost_limits=AgentCostLimits(
            step_limit=0,
            cost_limit=10.0,
            net_cost_limit=0.0,
        ),
        pricing=APIPricing(input=1.0, output=1.0),
        credential=_make_credential("openai", "OPENAI_API_KEY"),
        model="gpt-5",
        base_url=None,
        timeout=30,
        env={},
    )
    agent.setup(cast("Session", session))

    def fake_run_invocation(_: str) -> AgentCommandResult:
        trajectory = [
            {
                "llm_metrics": {
                    "accumulated_cost": 0.10,
                    "accumulated_token_usage": {
                        "prompt_tokens": 100,
                        "completion_tokens": 20,
                    },
                },
            },
            {
                "llm_metrics": {
                    "accumulated_cost": 0.25,
                    "accumulated_token_usage": {
                        "prompt_tokens": 250,
                        "completion_tokens": 50,
                    },
                },
            },
        ]
        (agent._get_output_dir() / "trajectory.json").write_text(
            json.dumps(trajectory)
        )
        return AgentCommandResult(
            result=RuntimeResult(
                exit_code=1 if timed_out else 0,
                stdout="",
                stderr="",
                setup_stdout="",
                setup_stderr="",
                elapsed=1.0,
                timed_out=timed_out,
            ),
            steps=[],
            usage_totals={},
            stdout="",
            stderr="",
        )

    monkeypatch.setattr(agent, "_run_invocation", fake_run_invocation)

    try:
        if timed_out:
            with pytest.raises(AgentError, match="timed out"):
                agent.run("solve this task")
        else:
            agent.run("solve this task")

        assert agent.usage.cost == 0.25
        assert agent.usage.net_tokens.input == 250
        assert agent.usage.net_tokens.output == 50
        assert agent.usage.current_tokens == agent.usage.net_tokens
    finally:
        agent.cleanup()
