from __future__ import annotations

import json
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

from slop_code.entrypoints.commands import (
    backfill_reports as backfill_reports_module,
)
from slop_code.metrics.scoring.models import Eligibility


def test_problem_configs_preserve_declared_order(
    tmp_path: Path,
    monkeypatch,
) -> None:
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    (run_dir / "config.yaml").write_text(
        json.dumps({"problems": ["second", "first"]})
    )
    loaded: list[Path] = []

    def load(path: Path) -> object:
        loaded.append(path)
        return SimpleNamespace(name=path.name)

    monkeypatch.setattr(
        backfill_reports_module.common,
        "load_problem_config",
        load,
    )

    problems = backfill_reports_module._problem_configs(
        tmp_path / "catalog", run_dir
    )

    assert [problem.name for problem in problems] == [
        "second",
        "first",
    ]
    assert loaded == [
        tmp_path / "catalog" / "second",
        tmp_path / "catalog" / "first",
    ]


def test_historical_run_captures_and_finalizes_under_one_lock(
    tmp_path: Path,
    monkeypatch,
) -> None:
    run_dir = tmp_path / "run"
    problems = (cast("Any", SimpleNamespace(name="problem")),)
    events: list[str] = []
    expected = Eligibility(
        eligible=False,
        reasons=("canonical_provenance_unavailable",),
    )

    @contextmanager
    def locked(_run_dir: Path):
        events.append("lock-enter")
        yield
        events.append("lock-exit")

    monkeypatch.setattr(
        backfill_reports_module,
        "_problem_configs",
        lambda problem_root, selected_run: problems,
    )
    monkeypatch.setattr(
        backfill_reports_module,
        "finalize_lock",
        locked,
    )
    monkeypatch.setattr(
        backfill_reports_module,
        "capture_historical_provenance",
        lambda selected_run, selected_problems: events.append("capture"),
    )
    monkeypatch.setattr(
        backfill_reports_module,
        "finalize_benchmark_score",
        lambda selected_run, selected_problems, lock_held: (
            events.append(f"finalize:{lock_held}")
        ),
    )
    monkeypatch.setattr(
        backfill_reports_module,
        "_current_eligibility",
        lambda selected_run: (events.append("eligibility") or expected),
    )

    actual = backfill_reports_module._process_historical_run(
        tmp_path / "catalog", run_dir
    )

    assert actual == expected
    assert events == [
        "lock-enter",
        "capture",
        "finalize:True",
        "lock-exit",
        "eligibility",
    ]
