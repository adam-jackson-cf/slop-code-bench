"""Shared test fixtures and utilities."""

from __future__ import annotations

from pathlib import Path

import pytest
from docker.errors import DockerException
from requests.exceptions import RequestException

from slop_code.execution.docker_runtime import docker_client

FIXTURE_EVALUATOR_LOCKS = Path(__file__).parent / "evaluator_locks"


@pytest.fixture(autouse=True)
def fixture_evaluator_locks(monkeypatch: pytest.MonkeyPatch) -> None:
    """Resolve evaluator locks for fixture problems from the test lock root."""
    monkeypatch.setattr(
        "slop_code.evaluation.locked_environment.EVALUATOR_LOCKS_ROOT",
        FIXTURE_EVALUATOR_LOCKS,
    )


def pytest_terminal_summary(terminalreporter) -> None:
    """Make Docker-unavailable skips loud; ``-q`` otherwise hides them."""
    skipped = [
        report
        for report in terminalreporter.stats.get("skipped", [])
        if "docker" in str(report.longrepr).lower()
    ]
    if skipped:
        terminalreporter.write_sep(
            "!",
            f"{len(skipped)} Docker tests SKIPPED: Docker daemon unreachable",
            red=True,
            bold=True,
        )


def is_docker_available() -> bool:
    """Check if Docker is available and running.

    Returns:
        True if Docker is available, False otherwise
    """
    try:
        client = docker_client()
        client.ping()
        client.close()
        return True
    except (DockerException, RequestException):
        return False


@pytest.fixture(scope="session")
def docker_available() -> bool:
    """Session-scoped fixture that checks if Docker is available."""
    return is_docker_available()


@pytest.fixture(scope="session")
def skip_if_no_docker():
    """Skip test if Docker is not available."""
    if not is_docker_available():
        pytest.skip("Docker is not available")
