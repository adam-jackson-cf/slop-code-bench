"""Type checking metrics via ty."""

from __future__ import annotations

import json
import locale
import os
import select
import shutil
from collections import Counter
from pathlib import Path

from slop_code.logging import get_logger
from slop_code.metrics.models import TypeCheckMetrics

logger = get_logger(__name__)

_EMPTY = TypeCheckMetrics(errors=0, warnings=0, counts={})


def _unavailable_type_check_metrics(reason: str) -> TypeCheckMetrics:
    """Build an explicit unavailable type-check metric result."""
    return TypeCheckMetrics(
        errors=None,
        warnings=None,
        counts={},
        available=False,
        unavailable_reason=reason,
    )


# ty gitlab format maps severity to these strings
_ERROR_SEVERITIES = frozenset({"major", "critical", "blocker"})


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


def calculate_type_check_metrics(source: Path) -> TypeCheckMetrics:
    """Run ty type checker on a single file and return metrics."""
    uv_executable = _resolve_uv_executable()
    if uv_executable is None:
        logger.debug("uv executable is unavailable")
        return _unavailable_type_check_metrics("checker_unavailable")

    command = [
        str(uv_executable),
        "run",
        "ty",
        "check",
        "--output-format",
        "gitlab",
        str(source.resolve()),
    ]
    try:
        exit_status, stdout, _ = _run_with_captured_output(command)
    except OSError as exc:
        logger.warning(
            "Failed to run ty",
            source=str(source),
            error=str(exc),
        )
        return _unavailable_type_check_metrics("checker_launch_failed")

    # ty uses exit status one for reported diagnostics. Higher statuses are
    # checker execution or configuration failures rather than findings.
    if exit_status not in {0, 1}:
        return _unavailable_type_check_metrics("checker_operational_failure")

    stdout = stdout.strip()
    if not stdout:
        if exit_status == 0:
            return _EMPTY
        return _unavailable_type_check_metrics("checker_malformed_output")

    try:
        diagnostics = json.loads(stdout)
    except json.JSONDecodeError:
        logger.warning(
            "Failed to parse ty output",
            source=str(source),
            stdout=stdout[:200],
        )
        return _unavailable_type_check_metrics("checker_malformed_output")

    if not isinstance(diagnostics, list):
        return _unavailable_type_check_metrics("checker_malformed_output")

    errors = 0
    warnings = 0
    counts: Counter[str] = Counter()

    for diag in diagnostics:
        if not isinstance(diag, dict):
            return _unavailable_type_check_metrics("checker_malformed_output")
        severity = diag.get("severity", "")
        rule = diag.get("check_name", "unknown")
        if not isinstance(severity, str) or not isinstance(rule, str):
            return _unavailable_type_check_metrics("checker_malformed_output")
        counts[rule] += 1
        if severity.lower() in _ERROR_SEVERITIES:
            errors += 1
        else:
            warnings += 1

    return TypeCheckMetrics(
        errors=errors, warnings=warnings, counts=dict(counts)
    )
