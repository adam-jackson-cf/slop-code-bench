"""Contracts for immutable evaluator environments."""

from __future__ import annotations

import stat
import threading
from pathlib import Path

import pytest

from slop_code.common.constants import EVALUATOR_ENVIRONMENTS_DIR
from slop_code.evaluation.config import ProblemConfig
from slop_code.evaluation.locked_environment import LockedEnvironmentError
from slop_code.evaluation.locked_environment import (
    ensure_locked_evaluator_environment,
)
from slop_code.evaluation.locked_environment import (
    verify_locked_evaluator_environment,
)


def _problem(
    tmp_path: Path,
    name: str = "project",
    test_dependencies: tuple[str, ...] = (),
) -> ProblemConfig:
    project = tmp_path / name
    project.mkdir()
    dependencies = (
        "\ndependencies = ["
        + ", ".join(f'"{dependency}"' for dependency in test_dependencies)
        + "]"
        if test_dependencies
        else ""
    )
    (project / "pyproject.toml").write_text(
        '[project]\nname = "fixture"\nversion = "0.1.0"\n'
        f'requires-python = ">=3.12"{dependencies}\n'
    )
    (project / "uv.lock").write_text(
        'version = 1\nrevision = 1\nrequires-python = ">=3.12"\n'
    )
    return ProblemConfig(
        name="fixture",
        path=project,
        version=1,
        description="fixture",
        tags=["fixture"],
        checkpoints={},
        entry_file="main.py",
        test_dependencies=list(test_dependencies),
    )


@pytest.fixture
def fake_sync(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> list[Path]:
    calls: list[Path] = []
    uv = tmp_path / "uv"
    uv.write_text("#!/bin/sh\nexit 0\n")
    uv.chmod(0o755)
    monkeypatch.setattr(
        "slop_code.evaluation.locked_environment.shutil.which",
        lambda _name: str(uv),
    )

    def spawn(
        _executable: str, command: list[str], _environment: dict[str, str]
    ) -> int:
        calls.append(Path(command[2]))
        python = calls[-1] / ".venv" / "bin" / "python"
        python.parent.mkdir(parents=True)
        python.write_text("#!/bin/sh\nexit 0\n")
        python.chmod(0o755)
        runner = python.parent / "pytest"
        runner.write_text(f"#!{python}\n")
        runner.chmod(0o755)
        return 1

    monkeypatch.setattr(
        "slop_code.evaluation.locked_environment.os.posix_spawn", spawn
    )
    monkeypatch.setattr(
        "slop_code.evaluation.locked_environment.os.waitpid",
        lambda process_id, _options: (process_id, 0),
    )
    return calls


def test_same_inputs_reuse_one_immutable_environment(
    tmp_path: Path, fake_sync: list[Path]
) -> None:
    problem = _problem(tmp_path)
    first = ensure_locked_evaluator_environment(
        tmp_path / "cache", problem, b"plugin", b"interpreter"
    )
    second = ensure_locked_evaluator_environment(
        tmp_path / "cache", problem, b"plugin", b"interpreter"
    )

    assert first == second
    assert len(fake_sync) == 1
    assert stat.S_IMODE(first.root.stat().st_mode) == 0o555
    assert stat.S_IMODE(first.python.stat().st_mode) == 0o555
    assert (first.root / ".venv" / "bin" / "pytest").read_text() == (
        f"#!{first.python}\n"
    )


def test_different_inputs_receive_different_environments(
    tmp_path: Path, fake_sync: list[Path]
) -> None:
    problem = _problem(tmp_path)
    first = ensure_locked_evaluator_environment(
        tmp_path / "cache", problem, b"plugin-a", b"interpreter"
    )
    second = ensure_locked_evaluator_environment(
        tmp_path / "cache", problem, b"plugin-b", b"interpreter"
    )

    assert first.environment_id != second.environment_id
    assert len(fake_sync) == 2


def test_declared_test_dependencies_are_identity_inputs(
    tmp_path: Path, fake_sync: list[Path]
) -> None:
    first_problem = _problem(tmp_path, "first", ("httpx==0.28.1",))
    second_problem = _problem(tmp_path, "second", ("anyio==4.10.0",))

    first = ensure_locked_evaluator_environment(
        tmp_path / "cache", first_problem, b"plugin", b"interpreter"
    )
    reused = ensure_locked_evaluator_environment(
        tmp_path / "cache", first_problem, b"plugin", b"interpreter"
    )
    second = ensure_locked_evaluator_environment(
        tmp_path / "cache", second_problem, b"plugin", b"interpreter"
    )

    assert first == reused
    assert first.environment_id != second.environment_id
    assert (first.root / "test_dependencies.json").read_text() == (
        '["httpx==0.28.1"]'
    )
    assert len(fake_sync) == 2


def test_same_id_concurrency_builds_once(
    tmp_path: Path, fake_sync: list[Path]
) -> None:
    problem = _problem(tmp_path)
    results = []

    def build() -> None:
        results.append(
            ensure_locked_evaluator_environment(
                tmp_path / "cache", problem, b"plugin", b"interpreter"
            )
        )

    threads = [threading.Thread(target=build) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert len({result.environment_id for result in results}) == 1
    assert len(fake_sync) == 1


def test_corruption_fails_without_mutating_published_environment(
    tmp_path: Path, fake_sync: list[Path]
) -> None:
    problem = _problem(tmp_path)
    environment = ensure_locked_evaluator_environment(
        tmp_path / "cache", problem, b"plugin", b"interpreter"
    )
    plugin = environment.root / "coverage_plugin.py"
    plugin.chmod(0o644)
    plugin.write_bytes(b"corrupt")

    with pytest.raises(
        LockedEnvironmentError,
        match="environment files do not match inventory",
    ):
        ensure_locked_evaluator_environment(
            tmp_path / "cache", problem, b"plugin", b"interpreter"
        )

    assert len(fake_sync) == 1
    assert plugin.read_bytes() == b"corrupt"


def test_incomplete_environment_recovers_after_failure(
    tmp_path: Path, fake_sync: list[Path]
) -> None:
    problem = _problem(tmp_path)

    def fail_after_sync(phase: str) -> None:
        if phase == "after_sync":
            raise RuntimeError("interrupted")

    with pytest.raises(RuntimeError, match="interrupted"):
        ensure_locked_evaluator_environment(
            tmp_path / "cache",
            problem,
            b"plugin",
            b"interpreter",
            failure_observer=fail_after_sync,
        )
    cache = tmp_path / "cache" / EVALUATOR_ENVIRONMENTS_DIR
    incomplete = next(path for path in cache.iterdir() if path.is_dir())
    assert not (incomplete / "READY").exists()

    rebuilt = ensure_locked_evaluator_environment(
        tmp_path / "cache", problem, b"plugin", b"interpreter"
    )
    assert (
        verify_locked_evaluator_environment(
            rebuilt.root, rebuilt.environment_id
        )
        == rebuilt
    )
    assert len(fake_sync) == 2
