"""Tests for runtime stream processing helpers."""

from __future__ import annotations

import threading
import time
from collections.abc import Generator

import pytest

from slop_code.execution.runtime import RuntimeEvent
from slop_code.execution.runtime import RuntimeResult
from slop_code.execution.stream_processor import ensure_string
from slop_code.execution.stream_processor import process_stream


def test_ensure_string_preserves_text_around_invalid_utf8_bytes() -> None:
    decoded = ensure_string(b'{"type":"message_update","data":"ok"}\xff\n')

    assert '{"type":"message_update","data":"ok"}' in decoded
    assert decoded.endswith("\n")


class BlockingIterator:
    """Iterator whose blocked read is interrupted by close."""

    def __init__(self, *, emit_first: bool = False) -> None:
        self.closed = threading.Event()
        self.finished = threading.Event()
        self.emit_first = emit_first
        self._emitted = False

    def __iter__(self) -> BlockingIterator:
        return self

    def __next__(self) -> tuple[bytes, bytes]:
        if self.emit_first and not self._emitted:
            self._emitted = True
            return b"first", b""
        self.closed.wait()
        self.finished.set()
        raise StopIteration

    def close(self) -> None:
        self.closed.set()


class FailingIterator:
    """Iterator that can fail before or after producing output."""

    def __init__(self, *, emit_first: bool) -> None:
        self.emit_first = emit_first
        self._emitted = False
        self.closed = False

    def __iter__(self) -> FailingIterator:
        return self

    def __next__(self) -> tuple[bytes, bytes]:
        if self.emit_first and not self._emitted:
            self._emitted = True
            return b"partial", b""
        raise RuntimeError("iterator failed")

    def close(self) -> None:
        self.closed = True


def consume(
    stream: Generator[RuntimeEvent, None, RuntimeResult],
) -> tuple[list[RuntimeEvent], RuntimeResult]:
    """Exhaust a generator while preserving its return value."""
    events = []
    while True:
        try:
            events.append(next(stream))
        except StopIteration as result:
            return events, result.value


@pytest.mark.parametrize("emit_first", [False, True])
def test_timeout_interrupts_blocked_iterator_within_bound(emit_first) -> None:
    iterator = BlockingIterator(emit_first=emit_first)
    started = time.monotonic()

    events, result = consume(process_stream(iterator, 0.02, lambda: None))

    assert time.monotonic() - started < 0.5
    assert iterator.closed.is_set()
    assert iterator.finished.wait(0.1)
    assert result.timed_out
    assert [event.text for event in events] == (["first"] if emit_first else [])


def test_iterator_error_before_output_is_propagated_after_cleanup() -> None:
    iterator = FailingIterator(emit_first=False)

    with pytest.raises(RuntimeError, match="iterator failed"):
        consume(process_stream(iterator, 1, lambda: None))

    assert iterator.closed


def test_iterator_error_after_partial_output_is_prompt_and_preserves_output() -> (
    None
):
    iterator = FailingIterator(emit_first=True)
    stream = process_stream(iterator, 1, lambda: None)

    event = next(stream)

    assert event.text == "partial"
    with pytest.raises(RuntimeError, match="iterator failed"):
        next(stream)
    assert iterator.closed
