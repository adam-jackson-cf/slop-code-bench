"""Fixtures for Docker runtime tests."""

from __future__ import annotations

import os
import shutil
import signal
import time
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from slop_code.execution.docker_runtime.models import DockerConfig
from slop_code.execution.docker_runtime.models import DockerEnvironmentSpec
from slop_code.execution.models import CommandConfig
from slop_code.execution.models import SetupConfig


def _run_docker_command(arguments: tuple[str, ...], timeout: float) -> bool:
    """Run a trusted Docker CLI command and report whether it succeeds."""
    docker_executable = shutil.which("docker")
    if docker_executable is None:
        return False

    process_id = os.posix_spawn(
        docker_executable,
        (docker_executable, *arguments),
        os.environ,
        file_actions=[
            (os.POSIX_SPAWN_OPEN, 1, os.devnull, os.O_WRONLY, 0),
            (os.POSIX_SPAWN_OPEN, 2, os.devnull, os.O_WRONLY, 0),
        ],
    )
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        completed_process_id, status = os.waitpid(process_id, os.WNOHANG)
        if completed_process_id:
            return os.waitstatus_to_exitcode(status) == 0
        time.sleep(0.01)

    completed_process_id, status = os.waitpid(process_id, os.WNOHANG)
    if completed_process_id:
        return os.waitstatus_to_exitcode(status) == 0

    os.kill(process_id, signal.SIGKILL)
    os.waitpid(process_id, 0)
    return False


def _docker_available() -> bool:
    """Check if Docker is available on the system."""
    try:
        return _run_docker_command(("info",), timeout=5)
    except OSError:
        return False


def _test_image_available() -> bool:
    """Check if the test Docker image is available."""
    try:
        return _run_docker_command(
            ("image", "inspect", "slop-code:python3.12"), timeout=10
        )
    except OSError:
        return False


# Skip markers
docker_available = pytest.mark.skipif(
    not _docker_available(),
    reason="Docker is not available",
)

test_image_available = pytest.mark.skipif(
    not _test_image_available(),
    reason="Test Docker image (slop-code:python3.12) not available",
)


@pytest.fixture
def docker_spec() -> DockerEnvironmentSpec:
    """Create a DockerEnvironmentSpec for testing."""
    return DockerEnvironmentSpec(
        type="docker",
        name="test-docker",
        commands=CommandConfig(command="python"),
        docker=DockerConfig(
            image="python:3.12-slim",
            workdir="/workspace",
        ),
    )


@pytest.fixture
def docker_spec_with_setup() -> DockerEnvironmentSpec:
    """Create a DockerEnvironmentSpec with setup commands."""
    return DockerEnvironmentSpec(
        type="docker",
        name="test-docker-setup",
        commands=CommandConfig(command="python"),
        setup=SetupConfig(
            commands=["echo 'setup command 1'"],
            eval_commands=["echo 'eval setup'"],
        ),
        docker=DockerConfig(
            image="python:3.12-slim",
            workdir="/workspace",
        ),
    )


@pytest.fixture
def docker_spec_with_mounts(tmp_path: Path) -> DockerEnvironmentSpec:
    """Create a DockerEnvironmentSpec with extra mounts."""
    mount_dir = tmp_path / "extra_mount"
    mount_dir.mkdir()
    (mount_dir / "mounted_file.txt").write_text("mounted content")

    return DockerEnvironmentSpec(
        type="docker",
        name="test-docker-mounts",
        commands=CommandConfig(command="python"),
        docker=DockerConfig(
            image="python:3.12-slim",
            workdir="/workspace",
            extra_mounts={str(mount_dir): "/extra"},
        ),
    )


@pytest.fixture
def docker_spec_host_network() -> DockerEnvironmentSpec:
    """Create a DockerEnvironmentSpec with host networking."""
    return DockerEnvironmentSpec(
        type="docker",
        name="test-docker-host",
        commands=CommandConfig(command="python"),
        docker=DockerConfig(
            image="python:3.12-slim",
            workdir="/workspace",
            network="host",
        ),
    )


@pytest.fixture
def mock_docker_client() -> MagicMock:
    """Create a mock Docker client."""
    client = MagicMock(spec=["containers", "close"])
    client.containers = MagicMock()
    return client


@pytest.fixture
def mock_container() -> MagicMock:
    """Create a mock Docker container."""
    container = MagicMock()
    container.id = "abc123def456"
    container.attrs = {"State": {"Status": "running"}}
    container.reload = MagicMock()
    container.start = MagicMock()
    container.stop = MagicMock()
    container.kill = MagicMock()
    container.remove = MagicMock()
    return container


@pytest.fixture
def mock_docker_client_with_container(
    mock_docker_client: MagicMock,
    mock_container: MagicMock,
) -> MagicMock:
    """Create a mock Docker client that returns a container."""
    mock_docker_client.containers.create.return_value = mock_container
    return mock_docker_client
