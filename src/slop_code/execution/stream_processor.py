"""Utilities for processing runtime output streams with threading.

This module provides utilities for handling streaming output from runtime processes
with proper threading and timeout management:

- **ensure_string**: Convert bytes to string with error handling
- **start_stream_pump**: Start threaded stream processing
- **make_timeout_fn**: Create timeout calculation functions
- **process_stream**: Main stream processing with timeout and filtering

The utilities support both Docker and local runtime streams, providing
consistent behavior across different execution environments with proper cleanup
and timeout handling.
"""

from __future__ import annotations

import queue
import threading
import time
from collections.abc import Callable
from collections.abc import Generator
from collections.abc import Iterator
from dataclasses import dataclass
from types import GeneratorType
from typing import Literal

import structlog

from slop_code.execution.runtime import RuntimeEvent
from slop_code.execution.runtime import RuntimeResult

logger = structlog.get_logger(__name__)

DEFAULT_WAIT_TIMEOUT = 7200.0  # 2 hours


def ensure_string(data: bytes | str) -> str:
    if isinstance(data, bytes):
        return data.decode("utf-8", errors="replace")
    return data


@dataclass(frozen=True)
class PumpEvent:
    """An event emitted by the background stream pump."""

    kind: Literal["stdout", "stderr", "finished", "error"]
    payload: str | None = None
    error: Exception | None = None


def start_stream_pump(
    stream: Iterator[tuple[bytes | str, bytes | str]],
    event_queue: queue.Queue[PumpEvent],
    stop_event: threading.Event,
) -> threading.Thread:
    """Start a daemon thread that pumps a demuxed stream into an event queue."""

    def pump() -> None:
        """Pump demuxed stream data, errors, and completion into the queue."""
        try:
            for stdout, stderr in stream:
                if stdout:
                    event_queue.put(PumpEvent("stdout", ensure_string(stdout)))
                if stderr:
                    event_queue.put(PumpEvent("stderr", ensure_string(stderr)))
                if stop_event.is_set():
                    break
        except Exception as error:  # noqa: BLE001 - iterator boundary
            logger.exception("Stream pump failed")
            event_queue.put(PumpEvent("error", error=error))
        finally:
            event_queue.put(PumpEvent("finished"))

    thread = threading.Thread(target=pump, daemon=True)
    thread.start()
    return thread


def make_timeout_fn(
    timeout: float | None, start_time: float
) -> Callable[[], float]:
    deadline = start_time + (timeout or DEFAULT_WAIT_TIMEOUT)

    def timeout_fn() -> float:
        return deadline - time.monotonic()

    return timeout_fn


def process_stream(
    stream: Iterator[tuple[str | bytes, str | bytes]],
    timeout: float | None,
    poll_fn: Callable[[], int | None],
    yield_only_after: str | None = None,
    cancel_fn: Callable[[], None] | None = None,
) -> Generator[RuntimeEvent, None, RuntimeResult]:
    """Consume a runtime stream while bounding timeout cleanup."""
    logger.debug("Starting to consume events with timeout", timeout=timeout)
    start_time = time.monotonic()
    timeout_fn = make_timeout_fn(timeout, start_time)
    stop_event = threading.Event()
    event_queue: queue.Queue[PumpEvent] = queue.Queue()
    thread = start_stream_pump(stream, event_queue, stop_event)
    stdout = ""
    stderr = ""
    setup_stdout = ""
    setup_stderr = ""
    yielding_stdout = yield_only_after is None
    yielding_stderr = yield_only_after is None
    timed_out = False
    pump_error: Exception | None = None
    cleanup_error: Exception | None = None
    exit_code: int | None = None

    def handle_event(event: PumpEvent) -> Iterator[RuntimeEvent]:
        nonlocal stdout, stderr, setup_stdout, setup_stderr
        nonlocal yielding_stdout, yielding_stderr
        if event.payload is None:
            return
        payload = event.payload
        if event.kind == "stdout":
            stdout += payload
            if (
                not yielding_stdout
                and yield_only_after
                and yield_only_after in stdout
            ):
                yielding_stdout = True
                setup_stdout, stdout = stdout.split(yield_only_after, 1)
                payload = stdout
            if yielding_stdout and payload.strip():
                yield RuntimeEvent(kind="stdout", text=payload)
        elif event.kind == "stderr":
            stderr += payload
            if (
                not yielding_stderr
                and yield_only_after
                and yield_only_after in stderr
            ):
                yielding_stderr = True
                setup_stderr, stderr = stderr.split(yield_only_after, 1)
                payload = stderr
            if yielding_stderr and payload.strip():
                yield RuntimeEvent(kind="stderr", text=payload)

    def consume_event(event: PumpEvent) -> Iterator[RuntimeEvent]:
        nonlocal pump_error
        if event.kind == "error":
            pump_error = event.error or RuntimeError("Stream pump failed")
        elif event.kind not in {"finished"}:
            yield from handle_event(event)

    def interrupt_stream() -> None:
        nonlocal cleanup_error
        stop_event.set()
        # A generator cannot be closed while its pump is blocked in next();
        # runtime-specific cancellation must be supplied through cancel_fn.
        cancel = cancel_fn
        if cancel is None and not isinstance(stream, GeneratorType):
            cancel = getattr(stream, "close", None)
        if callable(cancel):
            try:
                cancel()
            except Exception as error:  # noqa: BLE001 - cancellation boundary
                logger.exception("Stream cancellation failed")
                cleanup_error = error

    try:
        while (exit_code := poll_fn()) is None and pump_error is None:
            if (remaining := timeout_fn()) <= 0:
                timed_out = True
                break
            try:
                event = event_queue.get(timeout=remaining)
            except queue.Empty:
                continue
            yield from consume_event(event)
            if event.kind == "finished":
                break

        if not timed_out and exit_code is not None and pump_error is None:
            thread.join(timeout=max(0.0, timeout_fn()))

        while True:
            try:
                event = event_queue.get_nowait()
            except queue.Empty:
                break
            yield from consume_event(event)
    finally:
        interrupt_stream()
        # Closing an iterator cannot guarantee that a third-party blocking read
        # returns, so the daemon pump is joined only for this bounded interval.
        thread.join(timeout=0.1)
        if thread.is_alive():
            logger.warning(
                "Stream pump did not exit after bounded cancellation"
            )

    if pump_error is not None:
        if cleanup_error is not None:
            raise pump_error from cleanup_error
        raise pump_error
    if cleanup_error is not None:
        raise cleanup_error

    elapsed = time.monotonic() - start_time
    exit_code = exit_code if exit_code is not None else poll_fn()
    if exit_code is None:
        exit_code = -1
    logger.debug(
        "Setup stdout", setup_stdout=setup_stdout, setup_stderr=setup_stderr
    )
    return RuntimeResult(
        exit_code=exit_code,
        stdout=stdout,
        stderr=stderr,
        setup_stdout=setup_stdout,
        setup_stderr=setup_stderr,
        elapsed=elapsed,
        timed_out=timed_out,
    )
