#!/usr/bin/env python3
"""Create or refresh the harness-owned evaluator lock for a problem.

Writes ``src/slop_code/evaluation/evaluator_locks/<problem name>/pyproject.toml``
from the base evaluator dependencies, the problem's ``test_dependencies`` and
any ``--with`` packages, then runs ``uv lock`` there. Problem directories are
only read, never written.

Usage:
    uv run python scripts/lock_evaluator.py <problem_dir> [--with PKG ...]
"""

import argparse
import subprocess
from pathlib import Path

import yaml

LOCKS_ROOT = (
    Path(__file__).resolve().parents[1]
    / "src"
    / "slop_code"
    / "evaluation"
    / "evaluator_locks"
)
BASE_DEPENDENCIES = (
    "coverage==7.15.4",
    "pytest==8.4.1",
    "pytest-json-ctrf==0.3.5",
    "pytest-json-report==1.5.0",
    "pytest-timeout==2.4.0",
    "ruff==0.8.6",
)


def render_pyproject(name: str, dependencies: list[str]) -> str:
    lines = "".join(f'    "{dependency}",\n' for dependency in dependencies)
    return (
        "[project]\n"
        f'name = "{name.replace("_", "-")}-evaluator"\n'
        'version = "0.0.0"\n'
        'requires-python = ">=3.12"\n'
        f"dependencies = [\n{lines}]\n"
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Create a harness evaluator lock"
    )
    parser.add_argument("problem_dir", type=Path)
    parser.add_argument(
        "--with",
        dest="extra",
        action="append",
        default=[],
        help="Extra evaluator dependency the tests import (repeatable)",
    )
    args = parser.parse_args()

    config = yaml.safe_load((args.problem_dir / "config.yaml").read_text())
    name = config["name"]
    dependencies: list[str] = list(BASE_DEPENDENCIES)
    for dependency in [*config.get("test_dependencies", []), *args.extra]:
        if dependency not in dependencies:
            dependencies.append(dependency)

    target = LOCKS_ROOT / name
    target.mkdir(parents=True, exist_ok=True)
    (target / "pyproject.toml").write_text(render_pyproject(name, dependencies))
    subprocess.run(["uv", "lock", "--directory", str(target)], check=True)  # noqa: S603,S607
    print(target)


if __name__ == "__main__":
    main()
