"""Shared utilities for the test suite."""

from __future__ import annotations

import os
from functools import cache

import docker
from docker.errors import DockerException
from requests.exceptions import RequestException

DOCKER_TEST_IMAGE = os.environ.get(
    "SLOP_CODE_TEST_DOCKER_IMAGE",
    "python:3.12-slim",
)


def _docker_client() -> docker.DockerClient | None:
    """Return a Docker client when the daemon can be reached."""
    try:
        client = docker.from_env()
        client.ping()
    except (DockerException, RequestException):
        return None
    return client


@cache
def docker_tests_available(image: str = DOCKER_TEST_IMAGE) -> bool:
    """Check that Docker is usable and the provided image is present."""
    client = _docker_client()
    if client is None:
        return False

    try:
        client.images.get(image)
    except (DockerException, RequestException):
        return False
    finally:
        client.close()
    return True


__all__ = ["DOCKER_TEST_IMAGE", "docker_tests_available"]
