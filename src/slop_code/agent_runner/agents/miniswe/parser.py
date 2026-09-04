"""MiniSWE trajectory parser."""

from __future__ import annotations

import json
from pathlib import Path

from pydantic import TypeAdapter
from pydantic import ValidationError

from slop_code.agent_runner.trajectory import Trajectory
from slop_code.agent_runner.trajectory import TrajectoryStep
from slop_code.agent_runner.trajectory_parsing import ParseError
from slop_code.agent_runner.trajectory_parsing import TrajectoryParser


class MinisweParser(TrajectoryParser):
    """Parser for MiniSWE's typed trajectory artifacts."""

    _step_adapter = TypeAdapter(TrajectoryStep)
    _step_types = frozenset(("user", "agent", "thinking", "tool_use"))

    def can_parse(self, artifact_dir: Path) -> bool:
        """Check whether an artifact contains a typed MiniSWE trajectory."""
        jsonl_file = self._find_jsonl_file(artifact_dir)
        if jsonl_file is None:
            return False

        try:
            with jsonl_file.open(encoding="utf-8") as file:
                for line in file:
                    if not line.strip():
                        continue
                    event = json.loads(line)
                    return (
                        isinstance(event, dict)
                        and event.get("step_type") in self._step_types
                    )
        except (json.JSONDecodeError, OSError):
            return False
        return False

    def parse(self, artifact_dir: Path) -> Trajectory:
        """Parse a typed MiniSWE trajectory artifact."""
        jsonl_file = self._find_jsonl_file(artifact_dir)
        if jsonl_file is None:
            raise ParseError(f"No JSONL file found in {artifact_dir}")

        steps: list[TrajectoryStep] = []
        with jsonl_file.open(encoding="utf-8") as file:
            for line_num, line in enumerate(file, 1):
                if not line.strip():
                    continue
                try:
                    event = json.loads(line)
                    steps.append(self._step_adapter.validate_python(event))
                except json.JSONDecodeError as error:
                    raise ParseError(
                        f"Invalid JSON at line {line_num}: {error}"
                    ) from error
                except ValidationError as error:
                    raise ParseError(
                        f"Invalid MiniSWE step at line {line_num}: {error}"
                    ) from error

        return Trajectory(agent_type="miniswe", steps=steps)

    def _find_jsonl_file(self, artifact_dir: Path) -> Path | None:
        """Find the JSONL trajectory file."""
        if artifact_dir.is_file() and artifact_dir.suffix == ".jsonl":
            return artifact_dir

        trajectory_file = artifact_dir / "trajectory.jsonl"
        if trajectory_file.exists():
            return trajectory_file

        stdout_file = artifact_dir / "stdout.jsonl"
        if stdout_file.exists():
            return stdout_file

        jsonl_files = list(artifact_dir.glob("*.jsonl"))
        if jsonl_files:
            return jsonl_files[0]

        return None
