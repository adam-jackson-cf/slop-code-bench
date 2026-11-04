import os
import subprocess
from functools import cache

import docker


@cache
def _active_context_host() -> str | None:
    """Return the daemon endpoint of the docker CLI's active context."""
    try:
        proc = subprocess.run(  # noqa: S603 - fixed argv, no shell
            [  # noqa: S607 - docker must resolve from the active PATH.
                "docker",
                "context",
                "inspect",
                "--format",
                "{{.Endpoints.docker.Host}}",
            ],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    host = proc.stdout.strip()
    return host if proc.returncode == 0 and host else None


def docker_client() -> docker.DockerClient:
    """Create an SDK client for the same daemon the docker CLI targets.

    The SDK ignores docker contexts and defaults to ``/var/run/docker.sock``,
    while the CLI (used for ``docker run``/``exec``) follows the active
    context. When ``DOCKER_HOST`` is unset, use the active context's endpoint so
    both always reach one daemon.
    """
    environment = dict(os.environ)
    if not environment.get("DOCKER_HOST"):
        host = _active_context_host()
        if host is not None:
            environment["DOCKER_HOST"] = host
    return docker.from_env(environment=environment)


def network_mode_for_address(address: str) -> str:
    """Determine the appropriate Docker network mode for a given bind address.

    Args:
        address: The address the server will bind to (e.g., "127.0.0.1", "0.0.0.0")

    Returns:
        The appropriate Docker network mode ("host" or "bridge")

    Note:
        - "127.0.0.1" and "localhost" require "host" mode to be accessible from the host
        - "0.0.0.0" can use "bridge" mode with port mapping
        - Other addresses default to "host" mode for simplicity
    """
    if address in ("127.0.0.1", "localhost"):
        return "host"
    return "bridge"


__all__ = ["docker_client", "network_mode_for_address"]
