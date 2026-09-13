"""Ruff-based lint metrics."""

from __future__ import annotations

import json
import locale
import os
import select
import shutil
from collections import Counter
from pathlib import Path

from slop_code.logging import get_logger
from slop_code.metrics.languages.python.constants import RUFF_SELECT_FLAGS
from slop_code.metrics.models import LintMetrics

logger = get_logger(__name__)


def _resolve_uv_executable() -> Path | None:
    """Return the trusted resolved uv executable when it is available."""
    executable = shutil.which("uv")
    if executable is None:
        return None
    path = Path(executable).resolve()
    return path if path.is_file() and os.access(path, os.X_OK) else None


def _run_with_captured_output(command: list[str]) -> tuple[int, str, str]:
    """Run a trusted executable directly and return its exit status and output."""
    stdout_read, stdout_write = os.pipe()
    stderr_read, stderr_write = os.pipe()
    try:
        process_id = os.posix_spawn(
            command[0],
            command,
            os.environ,
            file_actions=[
                (os.POSIX_SPAWN_CLOSE, stdout_read),
                (os.POSIX_SPAWN_CLOSE, stderr_read),
                (os.POSIX_SPAWN_DUP2, stdout_write, 1),
                (os.POSIX_SPAWN_DUP2, stderr_write, 2),
                (os.POSIX_SPAWN_CLOSE, stdout_write),
                (os.POSIX_SPAWN_CLOSE, stderr_write),
            ],
        )
    except OSError:
        os.close(stdout_read)
        os.close(stderr_read)
        raise
    finally:
        os.close(stdout_write)
        os.close(stderr_write)
    output_by_fd = {stdout_read: bytearray(), stderr_read: bytearray()}
    open_fds = set(output_by_fd)
    while open_fds:
        readable, _, _ = select.select(list(open_fds), [], [])
        for fd in readable:
            chunk = os.read(fd, 65536)
            if chunk:
                output_by_fd[fd].extend(chunk)
            else:
                os.close(fd)
                open_fds.remove(fd)

    _, status = os.waitpid(process_id, 0)
    encoding = locale.getpreferredencoding(do_setlocale=False)
    return (
        os.waitstatus_to_exitcode(status),
        output_by_fd[stdout_read].decode(encoding),
        output_by_fd[stderr_read].decode(encoding),
    )


def _unavailable_lint_metrics(reason: str) -> LintMetrics:
    """Build an explicit unavailable lint metric result."""
    return LintMetrics(
        errors=None,
        fixable=None,
        counts={},
        available=False,
        unavailable_reason=reason,
    )


def calculate_lint_metrics(source: Path) -> LintMetrics:
    """Calculate lint metrics for a Python file using ruff."""
    uv_executable = _resolve_uv_executable()
    if uv_executable is None:
        logger.error("uv executable is unavailable", source=str(source))
        return _unavailable_lint_metrics("checker_unavailable")

    command = [
        str(uv_executable),
        "run",
        "ruff",
        "check",
        "--statistics",
        "--output-format",
        "json",
        "--isolated",
        "--preview",
        *RUFF_SELECT_FLAGS,
        str(source.resolve()),
    ]
    try:
        exit_status, stdout, _ = _run_with_captured_output(command)
    except OSError as exc:
        logger.error(
            "Failed to calculate lint metrics",
            source=str(source),
            error=str(exc),
        )
        return _unavailable_lint_metrics("checker_launch_failed")

    # Ruff uses exit status one for checker-defined findings. Other nonzero
    # statuses indicate an execution or configuration failure, not clean code.
    if exit_status not in {0, 1}:
        logger.warning(
            "Ruff failed without a findings result",
            source=str(source),
            exit_status=exit_status,
        )
        return _unavailable_lint_metrics("checker_operational_failure")

    stdout = stdout.strip()
    if not stdout:
        if exit_status == 0:
            return LintMetrics(errors=0, fixable=0, counts={})
        return _unavailable_lint_metrics("checker_malformed_output")

    stats = None
    while stats is None and stdout:
        try:
            stats = json.loads(stdout)
            break
        except json.JSONDecodeError:
            parts = stdout.split("\n", 1)
            if len(parts) < 2:
                break
            stdout = parts[1]

    if not isinstance(stats, list):
        logger.warning(
            "Failed to parse lint statistics",
            source=str(source),
            stdout=stdout,
        )
        return _unavailable_lint_metrics("checker_malformed_output")

    counts = Counter()
    fixable_count = total = 0

    for item in stats:
        try:
            code = item["code"]
            count = item["count"]
            is_fixable = item["fixable"]
        except (KeyError, TypeError):
            return _unavailable_lint_metrics("checker_malformed_output")
        if (
            not isinstance(code, str)
            or not isinstance(count, int)
            or isinstance(count, bool)
        ):
            return _unavailable_lint_metrics("checker_malformed_output")
        if not isinstance(is_fixable, bool):
            return _unavailable_lint_metrics("checker_malformed_output")
        counts[code] += count
        total += count
        if is_fixable:
            fixable_count += count

    return LintMetrics(errors=total, fixable=fixable_count, counts=dict(counts))
