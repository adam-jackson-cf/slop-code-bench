"""Tests for Docker SDK client host resolution."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from slop_code.execution.docker_runtime import utils


@pytest.fixture(autouse=True)
def _clear_context_cache():
    utils._active_context_host.cache_clear()
    yield
    utils._active_context_host.cache_clear()


@pytest.mark.parametrize(
    ("docker_host", "context_host", "expected"),
    [
        # Explicit DOCKER_HOST wins over the CLI context.
        ("tcp://explicit:2375", "unix:///ctx.sock", "tcp://explicit:2375"),
        # Unset (or empty) DOCKER_HOST follows the CLI's active context.
        (None, "unix:///ctx.sock", "unix:///ctx.sock"),
        ("", "unix:///ctx.sock", "unix:///ctx.sock"),
        # No resolvable context leaves the SDK default untouched.
        (None, None, None),
    ],
)
def test_docker_client_targets_cli_daemon(
    monkeypatch, docker_host, context_host, expected
):
    if docker_host is None:
        monkeypatch.delenv("DOCKER_HOST", raising=False)
    else:
        monkeypatch.setenv("DOCKER_HOST", docker_host)
    with (
        patch.object(utils, "_active_context_host", return_value=context_host),
        patch.object(utils.docker, "from_env") as from_env,
    ):
        utils.docker_client()

    environment = from_env.call_args.kwargs["environment"]
    assert (environment.get("DOCKER_HOST") or None) == expected


def test_active_context_host_absent_when_cli_missing():
    with patch.object(utils.subprocess, "run", side_effect=FileNotFoundError):
        assert utils._active_context_host() is None
