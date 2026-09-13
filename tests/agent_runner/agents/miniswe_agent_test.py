"""Behavioral coverage for MiniSWE agent setup."""

from __future__ import annotations

from dataclasses import dataclass
from functools import cache
from pathlib import Path
from typing import Any, cast

import pytest

from slop_code.agent_runner.agent import Agent
from slop_code.agent_runner.models import AgentCostLimits
from slop_code.agent_runner.models import AgentSetupError
from slop_code.execution import LocalEnvironmentSpec
from slop_code.execution import Session
from slop_code.execution.models import SetupConfig
from slop_code.protocol_loader import load_protocol_entrypoint


@dataclass
class FakeSession:
    """Minimal session required by MiniSWE setup."""

    spec: LocalEnvironmentSpec
    working_dir: Path


class FakeEnvironment:
    """Capture setup commands and return configured exit statuses."""

    def __init__(self, returncodes: list[int]) -> None:
        self.returncodes = returncodes
        self.commands: list[str] = []

    def execute(self, command: str) -> dict[str, int | str]:
        self.commands.append(command)
        return {
            "returncode": self.returncodes[len(self.commands) - 1],
            "output": "sensitive command output",
        }


@cache
def _load_agent_class() -> type[Any]:
    source_path = (
        Path(__file__).parents[3]
        / "src/slop_code/agent_runner/agents/miniswe.py"
    )
    return load_protocol_entrypoint(Agent, source_path, "MiniSWEAgent")


def _agent(agent_class: type[Any]) -> Any:
    return agent_class(
        problem_name="test-problem",
        verbose=False,
        cost_limits=AgentCostLimits(
            step_limit=10,
            cost_limit=100.0,
            net_cost_limit=200.0,
        ),
        pricing=None,
        model=cast(Any, object()),
        resolved_model_config={},
        system_template="",
        instance_template="",
        timeout_template="",
        format_error_template="",
        action_observation_template="",
    )


@pytest.mark.parametrize("failure_index", (0, 1, 2))
def test_setup_stops_after_the_first_failed_command(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, failure_index: int
) -> None:
    """A failed setup command prevents every later setup command from running."""
    commands = ["prepare", "install", "verify"]
    returncodes = [0, 0, 0]
    returncodes[failure_index] = 23
    environment = FakeEnvironment(returncodes)
    agent_class = _load_agent_class()
    monkeypatch.setattr(
        agent_class,
        "build_environment",
        staticmethod(lambda *_: environment),
    )
    session = FakeSession(
        spec=LocalEnvironmentSpec(
            name="test", setup=SetupConfig(commands=commands)
        ),
        working_dir=tmp_path,
    )

    with pytest.raises(AgentSetupError) as error:
        _agent(agent_class).setup(cast("Session", session))

    assert environment.commands == commands[: failure_index + 1]
    assert str(error.value) == (
        "MiniSWE setup command failed with exit code 23: "
        f"{commands[failure_index]}"
    )
    assert "sensitive command output" not in str(error.value)
