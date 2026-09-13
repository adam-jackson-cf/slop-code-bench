"""OpenHands trajectory parser."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from slop_code.agent_runner.trajectory import AgentStep
from slop_code.agent_runner.trajectory import ToolUseStep
from slop_code.agent_runner.trajectory import Trajectory
from slop_code.agent_runner.trajectory import TrajectoryStep
from slop_code.agent_runner.trajectory import UserStep
from slop_code.agent_runner.trajectory_parsing import ParseError
from slop_code.agent_runner.trajectory_parsing import TrajectoryParser


class OpenHandsParser(TrajectoryParser):
    """Parser for OpenHands trajectory format.

    OpenHands uses trajectory.json (array) or events.jsonl formats.
    """

    def can_parse(self, artifact_dir: Path) -> bool:
        """Check if directory contains OpenHands trajectory."""
        # Check if artifact_dir is a JSON file
        if artifact_dir.is_file():
            if artifact_dir.suffix == ".json":
                return self._is_openhands_json(artifact_dir)
            return False

        if not artifact_dir.is_dir():
            return False

        # Check for trajectory.json
        trajectory_path = artifact_dir / "trajectory.json"
        if trajectory_path.exists():
            return self._is_openhands_json(trajectory_path)

        # Check for events.jsonl
        events_path = artifact_dir / "events.jsonl"
        if events_path.exists():
            return self._is_openhands_jsonl(events_path)

        return False

    def _is_openhands_json(self, path: Path) -> bool:
        """Check if JSON file is OpenHands format."""
        try:
            with path.open() as f:
                data = json.load(f)
        except (json.JSONDecodeError, OSError):
            return False
        if not isinstance(data, list):
            return False
        # Check for OpenHands-specific fields
        for entry in data[:10]:  # Check first 10 entries
            if isinstance(entry, dict):
                if "llm_metrics" in entry:
                    return True
                if "source" in entry and entry.get("source") in (
                    "agent",
                    "user",
                    "environment",
                ):
                    return True
        return False

    def _is_openhands_jsonl(self, path: Path) -> bool:
        """Check if JSONL file contains a supported OpenHands action."""
        try:
            with path.open() as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    event = json.loads(line)
                    if not isinstance(event, dict):
                        return False
                    if event.get("is_step") or self._has_supported_action(
                        event
                    ):
                        return True
        except (json.JSONDecodeError, OSError):
            return False
        return False

    @staticmethod
    def _has_supported_action(event: dict[str, Any]) -> bool:
        """Return whether an event declares an actionable OpenHands action."""
        action = event.get("action")
        return isinstance(action, str) and bool(action) and action != "system"

    def parse(self, artifact_dir: Path) -> Trajectory:
        """Parse OpenHands trajectory."""
        steps: list[TrajectoryStep] = []
        metadata: dict[str, Any] = {}

        # Determine path
        if artifact_dir.is_file() and artifact_dir.suffix == ".json":
            self._parse_trajectory_json(artifact_dir, steps, metadata)
        elif artifact_dir.is_dir():
            trajectory_path = artifact_dir / "trajectory.json"
            events_path = artifact_dir / "events.jsonl"

            if trajectory_path.exists():
                self._parse_trajectory_json(trajectory_path, steps, metadata)
            elif events_path.exists():
                self._parse_events_jsonl(events_path, steps, metadata)
            else:
                raise ParseError(f"No trajectory file found in {artifact_dir}")
        else:
            raise ParseError(f"Invalid artifact path: {artifact_dir}")

        return Trajectory(
            agent_type="openhands",
            steps=steps,
            metadata=metadata,
        )

    def _parse_trajectory_json(
        self,
        path: Path,
        steps: list[TrajectoryStep],
        metadata: dict[str, Any],
    ) -> None:
        """Parse trajectory.json format."""
        try:
            with path.open() as f:
                data = json.load(f)
        except (json.JSONDecodeError, OSError) as e:
            raise ParseError(f"Failed to parse trajectory.json: {e}")

        if not isinstance(data, list):
            raise ParseError("trajectory.json must be a list")

        for entry in data:
            if not isinstance(entry, dict):
                continue

            # Use the last metrics record because values are cumulative.
            llm_metrics = entry.get("llm_metrics")
            if isinstance(llm_metrics, dict):
                metadata["accumulated_cost"] = llm_metrics.get(
                    "accumulated_cost", 0.0
                )
                accumulated_tokens = llm_metrics.get(
                    "accumulated_token_usage", {}
                )
                if not isinstance(accumulated_tokens, dict):
                    accumulated_tokens = {}
                metadata["total_tokens"] = {
                    "input": accumulated_tokens.get("prompt_tokens", 0),
                    "output": accumulated_tokens.get("completion_tokens", 0),
                }

            # Process based on source
            source = entry.get("source", "")
            action = entry.get("action", "")
            message = entry.get("message", "")
            args = entry.get("args", {})

            if source == "agent":
                if action == "message":
                    # Agent text output
                    content = args.get("content", "") or message
                    if content:
                        steps.append(AgentStep(content=content))
                elif action in ("run", "execute_bash"):
                    # Bash command
                    command = args.get("command", "")
                    steps.append(
                        ToolUseStep(
                            type="bash",
                            arguments={"command": command},
                            result=None,
                        )
                    )
                elif action in ("write", "edit", "str_replace_editor"):
                    # File edit
                    steps.append(
                        ToolUseStep(
                            type="edit",
                            arguments=args,
                            result=None,
                        )
                    )
                elif action == "read":
                    # File read
                    steps.append(
                        ToolUseStep(
                            type="read",
                            arguments=args,
                            result=None,
                        )
                    )
                elif action == "browse":
                    # Web browse
                    steps.append(
                        ToolUseStep(
                            type="browse",
                            arguments=args,
                            result=None,
                        )
                    )
                elif action and action != "system":
                    # Other tool use
                    steps.append(
                        ToolUseStep(
                            type=action,
                            arguments=args,
                            result=None,
                        )
                    )

            elif source == "user":
                content = args.get("content", "") or message
                if content and len(content) < 10000:
                    steps.append(UserStep(content=content))

            elif source == "environment":
                # Tool results - match with previous tool use
                content = args.get("content", "") or message
                if content:
                    for step in reversed(steps):
                        if (
                            isinstance(step, ToolUseStep)
                            and step.result is None
                        ):
                            step.result = content
                            break

    def _parse_events_jsonl(
        self,
        path: Path,
        steps: list[TrajectoryStep],
        metadata: dict[str, Any],
    ) -> None:
        """Parse events.jsonl format."""
        try:
            with path.open() as f:
                for line_num, line in enumerate(f, 1):
                    line = line.strip()
                    if not line:
                        continue

                    try:
                        event = json.loads(line)
                    except json.JSONDecodeError as e:
                        raise ParseError(
                            f"Invalid JSON at line {line_num}: {e}"
                        )

                    self._process_event(event, steps)
        except OSError as e:
            raise ParseError(f"Failed to read events.jsonl: {e}")

    def _process_event(
        self,
        event: dict[str, Any],
        steps: list[TrajectoryStep],
    ) -> None:
        """Process a single event from events.jsonl."""
        if not event.get("is_step") and not self._has_supported_action(event):
            return

        line = event.get("line", "")
        action = event.get("action", "")
        args = event.get("args", {})
        if not isinstance(args, dict):
            args = {}

        # Detect command execution
        if "**CmdRunAction**" in line or action in ("run", "execute_bash"):
            command = args.get("command", line)
            steps.append(
                ToolUseStep(
                    type="bash",
                    arguments={"command": command},
                    result=None,
                )
            )

        # Detect file edit
        elif "**FileEditAction**" in line or action in (
            "write",
            "edit",
            "str_replace_editor",
        ):
            steps.append(
                ToolUseStep(
                    type="edit",
                    arguments=args,
                    result=None,
                )
            )

        elif action == "read":
            steps.append(
                ToolUseStep(
                    type="read",
                    arguments=args,
                    result=None,
                )
            )

        elif action == "browse":
            steps.append(
                ToolUseStep(
                    type="browse",
                    arguments=args,
                    result=None,
                )
            )

        elif action == "message":
            content = args.get("content", "") or event.get("message", "")
            if content:
                steps.append(AgentStep(content=content))

        elif self._has_supported_action(event):
            steps.append(
                ToolUseStep(
                    type=action,
                    arguments=args,
                    result=None,
                )
            )
