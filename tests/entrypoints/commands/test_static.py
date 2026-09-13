from __future__ import annotations

from concurrent.futures import Future
from pathlib import Path
from types import SimpleNamespace
from typing import cast

import pytest
import typer

from slop_code.entrypoints.commands import common
from slop_code.entrypoints.commands import static


@pytest.mark.parametrize(
    ("outcomes", "expected_exit_code", "saved_runs"),
    [
        ((True, True), None, ["run_1", "run_2"]),
        ((False, True), 1, ["run_2"]),
        ((False, RuntimeError("executor failure")), 1, []),
    ],
)
def test_static_collection_processes_every_run_and_surfaces_failures(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    outcomes: tuple[bool | Exception, bool | Exception],
    expected_exit_code: int | None,
    saved_runs: list[str],
) -> None:
    collection_dir = tmp_path / "collection"
    collection_dir.mkdir()
    run_dirs = [collection_dir / "run_1", collection_dir / "run_2"]
    for run_dir in run_dirs:
        run_dir.mkdir()
    submitted: list[Path] = []
    saved: list[str] = []

    class FakeExecutor:
        def __init__(self, **_: object) -> None:
            pass

        def __enter__(self) -> FakeExecutor:
            return self

        def __exit__(self, *_: object) -> None:
            return None

        def submit(
            self,
            _worker: object,
            _problem_root: Path,
            selected_run_dir: Path,
            _problem_name: str | None,
        ) -> Future[static.RunProcessingResult]:
            submitted.append(selected_run_dir)
            future: Future[static.RunProcessingResult] = Future()
            outcome = outcomes[len(submitted) - 1]
            if isinstance(outcome, Exception):
                future.set_exception(outcome)
            else:
                future.set_result(
                    static.RunProcessingResult(
                        run_dir=selected_run_dir,
                        success=outcome,
                        error_message="worker failure" if not outcome else None,
                    )
                )
            return future

    monkeypatch.setattr(static, "ProcessPoolExecutor", FakeExecutor)
    monkeypatch.setattr(static, "discover_run_directories", lambda _: run_dirs)
    monkeypatch.setattr(
        static.common,
        "resolve_problem_catalog_root",
        lambda _: tmp_path / "catalog",
    )
    monkeypatch.setattr(
        static,
        "update_results_jsonl",
        lambda report_file, _reports: saved.append(report_file.parent.name),
    )
    ctx = cast("typer.Context", SimpleNamespace())

    if expected_exit_code is not None:
        with pytest.raises(typer.Exit) as exit_info:
            static.static_metrics(
                ctx,
                collection_dir,
                path_type=common.PathType.COLLECTION,
            )
        assert exit_info.value.exit_code == expected_exit_code
    else:
        static.static_metrics(
            ctx,
            collection_dir,
            path_type=common.PathType.COLLECTION,
        )

    assert submitted == run_dirs
    assert saved == saved_runs
