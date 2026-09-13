from __future__ import annotations

import tarfile
from pathlib import Path
from types import SimpleNamespace
from typing import cast

import pytest
import typer

from slop_code.common import AGENT_TAR_FILENAME
from slop_code.entrypoints.commands import compress_artifacts as command


def test_compress_agent_dir_preserves_source_when_archive_creation_fails(
    tmp_path, monkeypatch
):
    agent_dir = tmp_path / "agent"
    agent_dir.mkdir()
    artifact = agent_dir / "artifact.txt"
    artifact.write_bytes(b"original artifact")

    def fail_open(*_args: object, **_kwargs: object) -> None:
        raise tarfile.TarError("archive failure")

    monkeypatch.setattr(command.tarfile, "open", fail_open)

    success, error = command._compress_agent_dir(agent_dir)

    assert not success
    assert error is not None
    assert "archive failure" in error
    assert artifact.read_bytes() == b"original artifact"
    assert not (tmp_path / AGENT_TAR_FILENAME).exists()


def test_compress_agent_dir_retains_completed_archive_when_source_removal_fails(
    tmp_path, monkeypatch
):
    agent_dir = tmp_path / "agent"
    agent_dir.mkdir()
    first = agent_dir / "first.txt"
    second = agent_dir / "second.txt"
    first.write_bytes(b"first")
    second.write_bytes(b"second")

    def remove_partially(_path: Path) -> None:
        first.unlink()
        raise OSError("source cleanup failed")

    monkeypatch.setattr(command.shutil, "rmtree", remove_partially)

    success, error = command._compress_agent_dir(agent_dir)

    assert not success
    assert error is not None
    assert "source cleanup failed" in error
    tar_path = tmp_path / AGENT_TAR_FILENAME
    assert tar_path.exists()
    with tarfile.open(tar_path) as archive:
        first_file = archive.extractfile("first.txt")
        second_file = archive.extractfile("second.txt")
        assert first_file is not None
        assert second_file is not None
        assert first_file.read() == b"first"
        assert second_file.read() == b"second"
    assert second.read_bytes() == b"second"


@pytest.mark.parametrize(
    ("compressed", "skipped", "failures", "should_fail"),
    [
        (1, 0, 0, False),
        (0, 1, 0, False),
        (1, 0, 1, True),
        (0, 0, 1, True),
    ],
)
def test_compress_artifacts_exits_nonzero_only_for_operation_failures(
    tmp_path, monkeypatch, compressed, skipped, failures, should_fail
):
    monkeypatch.setattr(command, "setup_logging", lambda **_: None)
    monkeypatch.setattr(command, "_find_agent_dirs", lambda _: [])
    errors = [(tmp_path / "agent", "failure")] * failures
    monkeypatch.setattr(
        command,
        "_process_single_run",
        lambda _: (compressed, skipped, errors),
    )
    ctx = cast(typer.Context, SimpleNamespace(obj=SimpleNamespace(verbosity=0)))

    if should_fail:
        with pytest.raises(typer.Exit) as exit_info:
            command.compress_artifacts(ctx, tmp_path)
        assert exit_info.value.exit_code == 1
    else:
        command.compress_artifacts(ctx, tmp_path)
