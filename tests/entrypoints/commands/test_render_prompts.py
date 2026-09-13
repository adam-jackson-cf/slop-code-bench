from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import cast

from slop_code.entrypoints.commands import render_prompts
from slop_code.evaluation import ProblemConfig
from slop_code.execution.models import EnvironmentSpec


def _problem_config(name: str, specs: list[str]) -> ProblemConfig:
    checkpoint_names = [
        f"checkpoint_{index}" for index in range(1, len(specs) + 1)
    ]
    specs_by_checkpoint = dict(zip(checkpoint_names, specs, strict=True))
    return cast(
        "ProblemConfig",
        SimpleNamespace(
            name=name,
            entry_file="main.py",
            iterate_checkpoints=lambda: [
                SimpleNamespace(name=checkpoint_name)
                for checkpoint_name in checkpoint_names
            ],
            get_checkpoint_spec=specs_by_checkpoint.__getitem__,
        ),
    )


def test_process_problem_isolates_unequal_checkpoint_prompts(
    tmp_path: Path,
) -> None:
    environment = EnvironmentSpec(type="local", name="test")
    first_problem = _problem_config("first", ["first prompt"])
    second_problem = _problem_config(
        "second", ["second prompt one", "second prompt two"]
    )

    assert (
        render_prompts._process_problem(
            first_problem, "{{ spec }}", environment, tmp_path
        )
        == 1
    )
    assert (
        render_prompts._process_problem(
            second_problem, "{{ spec }}", environment, tmp_path
        )
        == 2
    )

    assert (tmp_path / "first" / "part_1.md").read_text() == "first prompt"
    assert not (tmp_path / "first" / "part_2.md").exists()
    assert (tmp_path / "second" / "part_1.md").read_text() == (
        "second prompt one"
    )
    assert (tmp_path / "second" / "part_2.md").read_text() == (
        "second prompt two"
    )
