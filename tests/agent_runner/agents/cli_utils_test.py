"""Tests for CLI stream completion handling."""

from __future__ import annotations

from collections.abc import Iterator
from typing import cast

import pytest

from slop_code.agent_runner.agents.cli_utils import IncompleteStreamError
from slop_code.agent_runner.agents.cli_utils import stream_cli_command
from slop_code.execution.protocols import StreamingRuntime
from slop_code.execution.runtime import RuntimeEvent
from slop_code.execution.runtime import RuntimeResult


class FakeStreamingRuntime:
    def __init__(self, events: list[RuntimeEvent]) -> None:
        self.events = events

    def stream(self, **_: object) -> Iterator[RuntimeEvent]:
        yield from self.events


def _result(exit_code: int = 0) -> RuntimeResult:
    return RuntimeResult(
        exit_code=exit_code,
        stdout="",
        stderr="failed" if exit_code else "",
        setup_stdout="",
        setup_stderr="",
        elapsed=1.0,
        timed_out=False,
    )


def _parse(line: str) -> tuple[None, None, dict[str, str]]:
    return None, None, {"line": line}


def test_stream_cli_command_preserves_terminal_result() -> None:
    terminal = _result(exit_code=1)
    runtime = FakeStreamingRuntime(
        [
            RuntimeEvent(kind="stdout", text="event\n"),
            RuntimeEvent(kind="finished", result=terminal),
        ]
    )

    events = list(
        stream_cli_command(cast("StreamingRuntime", runtime), "agent", _parse)
    )

    assert events == [(None, None, {"line": "event"}), terminal]


@pytest.mark.parametrize(
    "events",
    [
        [],
        [RuntimeEvent(kind="stdout", text="partial output")],
        [RuntimeEvent(kind="finished")],
    ],
)
def test_stream_cli_command_rejects_missing_terminal_result(
    events: list[RuntimeEvent],
) -> None:
    runtime = FakeStreamingRuntime(events)

    with pytest.raises(
        IncompleteStreamError, match="terminal 'finished' result"
    ):
        list(
            stream_cli_command(
                cast("StreamingRuntime", runtime), "agent", _parse
            )
        )
