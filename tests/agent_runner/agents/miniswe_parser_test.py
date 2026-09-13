"""Behavioral coverage for typed MiniSWE trajectory artifacts."""

import json
from datetime import UTC
from datetime import datetime
from pathlib import Path

import pytest

from slop_code.agent_runner.agents.miniswe.parser import MinisweParser
from slop_code.agent_runner.trajectory import AgentStep
from slop_code.agent_runner.trajectory import ThinkingStep
from slop_code.agent_runner.trajectory import ToolUseStep
from slop_code.agent_runner.trajectory import UserStep
from slop_code.agent_runner.trajectory_parsing import parse_trajectory


def test_typed_miniswe_artifact_round_trips(tmp_path: Path) -> None:
    """MiniSWE's saved step JSONL is auto-detected without legacy roles."""
    timestamp = datetime(2026, 8, 28, tzinfo=UTC)
    emitted_steps = [
        UserStep(content="System instructions", timestamp=timestamp),
        UserStep(content="Fix the parser", timestamp=timestamp),
        ThinkingStep(
            content="I should inspect the artifact format.", timestamp=timestamp
        ),
        AgentStep(content="I will update the parser.", timestamp=timestamp),
        ToolUseStep(
            type="environment",
            result="parser.py\n",
            timestamp=timestamp,
        ),
    ]
    artifact = tmp_path / "trajectory.jsonl"
    artifact.write_text(
        "".join(f"{step.model_dump_json()}\n" for step in emitted_steps),
        encoding="utf-8",
    )

    assert MinisweParser().can_parse(tmp_path)
    trajectory = parse_trajectory(tmp_path)

    assert trajectory.agent_type == "miniswe"
    assert trajectory.steps == emitted_steps
    assert trajectory.metadata == {}
    assert all("role" not in line for line in artifact.read_text().splitlines())


@pytest.mark.parametrize("step_type", ("user", "agent", "thinking", "tool_use"))
def test_can_parse_recognizes_supported_string_step_types(
    tmp_path: Path, step_type: str
) -> None:
    """Supported string step types identify MiniSWE artifacts."""
    (tmp_path / "trajectory.jsonl").write_text(
        json.dumps({"step_type": step_type}) + "\n",
        encoding="utf-8",
    )

    assert MinisweParser().can_parse(tmp_path)


@pytest.mark.parametrize("step_type", (None, 1, [], {}))
def test_can_parse_rejects_non_string_step_types(
    tmp_path: Path, step_type: object
) -> None:
    """Non-string step types cannot identify MiniSWE artifacts."""
    (tmp_path / "trajectory.jsonl").write_text(
        json.dumps({"step_type": step_type}) + "\n",
        encoding="utf-8",
    )

    assert not MinisweParser().can_parse(tmp_path)
