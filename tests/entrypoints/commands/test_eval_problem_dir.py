from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import TYPE_CHECKING, cast
from unittest.mock import MagicMock

if TYPE_CHECKING:
    import typer

from slop_code.entrypoints.commands import eval_problem_dir
from slop_code.entrypoints.evaluation import utils as evaluation_utils
from slop_code.evaluation import ProblemConfig
from slop_code.metrics import RubricProvider


def _context(tmp_path: Path) -> typer.Context:
    return cast(
        "typer.Context",
        SimpleNamespace(
            obj=SimpleNamespace(
                verbosity=0,
                seed=1,
                scbench_home=tmp_path / "scbench-home",
            )
        ),
    )


def test_resolve_problem_prefers_explicit_catalog_name(
    tmp_path: Path,
    monkeypatch,
) -> None:
    catalog_root = tmp_path / "catalog"
    explicit_dir = catalog_root / "catalog-problem"
    inferred_dir = catalog_root / "submission"
    explicit_dir.mkdir(parents=True)
    inferred_dir.mkdir()
    submission_dir = tmp_path / "submission"
    submission_dir.mkdir()
    (submission_dir / "problem.yaml").write_text("name: stale-problem\n")

    loaded_paths: list[Path] = []
    source_problem = MagicMock(spec=ProblemConfig)

    def load_problem(path: Path) -> MagicMock:
        loaded_paths.append(path)
        return source_problem

    monkeypatch.setattr(
        evaluation_utils.ProblemConfig,
        "from_yaml",
        load_problem,
    )

    assert (
        evaluation_utils.resolve_problem(
            submission_dir, catalog_root, "catalog-problem"
        )
        is source_problem
    )
    assert (
        evaluation_utils.resolve_problem(submission_dir, catalog_root)
        is source_problem
    )
    assert loaded_paths == [explicit_dir, inferred_dir]


def test_problem_command_uses_explicit_catalog_problem_for_evaluation(
    tmp_path: Path,
    monkeypatch,
) -> None:
    submission_dir = tmp_path / "submission"
    checkpoint_dir = submission_dir / "checkpoint_1"
    snapshot_dir = checkpoint_dir / "snapshot"
    snapshot_dir.mkdir(parents=True)
    environment_path = tmp_path / "environment.yaml"

    checkpoint = MagicMock()
    source_problem = MagicMock(spec=ProblemConfig)
    source_problem.name = "catalog-problem"
    source_problem.checkpoints = {"checkpoint_1": checkpoint}
    resolved_problem = MagicMock(return_value=source_problem)
    evaluate_mock = MagicMock(
        return_value=SimpleNamespace(report=MagicMock(), quality=MagicMock())
    )

    monkeypatch.setattr(
        eval_problem_dir.config_loader,
        "resolve_environment",
        lambda _path: object(),
    )
    monkeypatch.setattr(
        eval_problem_dir.common,
        "setup_command_logging",
        lambda **_kwargs: MagicMock(),
    )
    monkeypatch.setattr(
        eval_problem_dir.common,
        "ensure_docker_ready",
        lambda _environment: None,
    )
    monkeypatch.setattr(
        eval_problem_dir.common,
        "resolve_problem_catalog_root",
        lambda _ctx: tmp_path / "catalog",
    )
    monkeypatch.setattr(eval_problem_dir, "resolve_problem", resolved_problem)
    monkeypatch.setattr(
        eval_problem_dir,
        "gather_checkpoint_directories",
        lambda **_kwargs: [("checkpoint_1", checkpoint_dir, snapshot_dir)],
    )
    monkeypatch.setattr(eval_problem_dir, "evaluate_checkpoint", evaluate_mock)
    monkeypatch.setattr(
        eval_problem_dir,
        "render_pytest_results",
        lambda _console, _report, _verbosity: None,
    )
    monkeypatch.setattr(
        eval_problem_dir,
        "maybe_update_problem_report",
        lambda **_kwargs: None,
    )

    eval_problem_dir.evaluate_problem_dir(
        ctx=_context(tmp_path),
        submission_path=submission_dir,
        problem_name="catalog-problem",
        env_config=environment_path,
        snapshot_dir="snapshot",
        rubric_path=None,
        rubric_model=None,
        rubric_temperature=0.0,
        rubric_provider=RubricProvider.OPENROUTER,
    )

    assert resolved_problem.call_args.kwargs == {
        "submission_dir": submission_dir,
        "problem_path": tmp_path / "catalog",
        "problem_name": "catalog-problem",
    }
    assert evaluate_mock.call_args.kwargs["problem"] is source_problem
    assert evaluate_mock.call_args.kwargs["checkpoint"] is checkpoint
