"""Validation of the controlled-continuation flags of ``slop-code run``."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest
import typer

from slop_code.entrypoints.commands.run_agent import _build_continuation_seed
from slop_code.entrypoints.commands.run_agent import _validate_start_flags
from slop_code.entrypoints.config.loader import load_run_config

PROBLEM_FIXTURE = (
    Path(__file__).parents[2] / "evaluation" / "fixtures" / "word_stats"
)


@pytest.fixture
def problem_root(tmp_path: Path) -> Path:
    root = tmp_path / "problems"
    shutil.copytree(PROBLEM_FIXTURE / "problem", root / "word_stats")
    return root


@pytest.fixture
def snapshot(tmp_path: Path) -> Path:
    path = tmp_path / "snapshot"
    path.mkdir()
    (path / "main.py").write_text("print('x')\n")
    return path


def test_flags_must_be_given_together(snapshot: Path) -> None:
    with pytest.raises(typer.Exit):
        _validate_start_flags(
            start_snapshot=snapshot, start_checkpoint=None, resume=None
        )
    with pytest.raises(typer.Exit):
        _validate_start_flags(
            start_snapshot=None, start_checkpoint="checkpoint_2", resume=None
        )


def test_flags_conflict_with_resume(snapshot: Path, tmp_path: Path) -> None:
    with pytest.raises(typer.Exit):
        _validate_start_flags(
            start_snapshot=snapshot,
            start_checkpoint="checkpoint_2",
            resume=tmp_path,
        )


def test_missing_snapshot_directory_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(typer.Exit):
        _validate_start_flags(
            start_snapshot=tmp_path / "missing",
            start_checkpoint="checkpoint_2",
            resume=None,
        )


def test_valid_flags_pass(snapshot: Path) -> None:
    _validate_start_flags(
        start_snapshot=snapshot, start_checkpoint="checkpoint_2", resume=None
    )
    _validate_start_flags(
        start_snapshot=None, start_checkpoint=None, resume=None
    )


def test_seed_requires_exactly_one_problem(
    problem_root: Path, snapshot: Path
) -> None:
    run_cfg = load_run_config(None, {}, None)
    with pytest.raises(typer.Exit):
        _build_continuation_seed(
            run_cfg,
            ["word_stats", "other"],
            problem_root,
            snapshot,
            "checkpoint_2",
        )


@pytest.mark.parametrize("start", ["checkpoint_1", "checkpoint_9"])
def test_seed_rejects_first_and_unknown_checkpoints(
    problem_root: Path, snapshot: Path, start: str
) -> None:
    run_cfg = load_run_config(None, {}, None)
    with pytest.raises(typer.Exit):
        _build_continuation_seed(
            run_cfg, ["word_stats"], problem_root, snapshot, start
        )


def test_seed_is_recorded_for_valid_start(
    problem_root: Path, snapshot: Path
) -> None:
    run_cfg = load_run_config(None, {}, None)

    seed = _build_continuation_seed(
        run_cfg, ["word_stats"], problem_root, snapshot, "checkpoint_2"
    )

    assert seed.start_checkpoint == "checkpoint_2"
    assert seed.source_path == str(snapshot.resolve())
    assert seed.digest.startswith("sha256:")
