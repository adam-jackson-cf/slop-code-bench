"""Regression tests for publishing migrated solutions."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType


def _load_script(name: str) -> ModuleType:
    path = Path(__file__).parents[2] / "scripts" / f"{name}.py"
    spec = importlib.util.spec_from_file_location(f"{name}_under_test", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


migrate_specs_solutions = _load_script("migrate_specs_solutions")
migrate_problem = migrate_specs_solutions.migrate_problem


def test_migration_skips_an_exact_existing_solution(
    tmp_path: Path, monkeypatch
) -> None:
    problem = tmp_path / "problem"
    source = problem / "checkpoint_1" / "solution"
    destination = problem / "solutions" / "checkpoint_1"
    source.mkdir(parents=True)
    destination.mkdir(parents=True)
    (source / "answer.py").write_bytes(b"answer = 42\n")
    (destination / "answer.py").write_bytes(b"answer = 42\n")

    def should_not_publish(*_args: object) -> None:
        raise AssertionError("exact destination was rewritten")

    monkeypatch.setattr(
        migrate_specs_solutions, "publish_solution", should_not_publish
    )

    result = migrate_problem(problem)

    assert result["solutions"] == []
    assert result["skipped"] == [f"{destination} already exists"]


def test_migration_replaces_a_mismatched_solution(tmp_path: Path) -> None:
    problem = tmp_path / "problem"
    source = problem / "checkpoint_1" / "solution"
    destination = problem / "solutions" / "checkpoint_1"
    source.mkdir(parents=True)
    destination.mkdir(parents=True)
    (source / "answer.py").write_bytes(b"answer = 42\n")
    (source / "nested").mkdir()
    (source / "nested" / "data.txt").write_bytes(b"complete")
    (destination / "answer.py").write_bytes(b"wrong = 0\n")

    result = migrate_problem(problem)

    assert result["solutions"] == [f"{source} -> {destination}"]
    assert {
        path.relative_to(destination): path.read_bytes()
        for path in destination.rglob("*")
        if path.is_file()
    } == {
        path.relative_to(source): path.read_bytes()
        for path in source.rglob("*")
        if path.is_file()
    }
    assert not list((problem / "solutions").glob(".checkpoint_1.*"))
