from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import cast
from unittest.mock import MagicMock

import pytest
import typer

from slop_code.entrypoints.commands import infer_problem as command
from slop_code.evaluation import PassPolicy


def _catalog_root(tmp_path):
    catalog_root = tmp_path / "catalog"
    problem_dir = catalog_root / "safe-problem"
    problem_dir.mkdir(parents=True)
    (problem_dir / "config.yaml").write_text("name: safe-problem\n")
    return catalog_root


def _context() -> typer.Context:
    return cast(typer.Context, SimpleNamespace(obj=SimpleNamespace()))


@pytest.mark.parametrize("problem_name", ["/absolute", "../outside"])
def test_resolve_problem_destination_rejects_path_components_before_output_mutation(
    tmp_path, monkeypatch, problem_name
):
    catalog_root = _catalog_root(tmp_path)
    output_root = tmp_path / "output"
    monkeypatch.setattr(
        command.common,
        "resolve_problem_catalog_root",
        lambda _: catalog_root,
    )

    with pytest.raises(typer.Exit):
        command._resolve_problem_destination(
            _context(), problem_name, output_root
        )

    assert not output_root.exists()


def test_resolve_problem_destination_rejects_symlink_escape_before_mutation(
    tmp_path, monkeypatch
):
    catalog_root = _catalog_root(tmp_path)
    output_root = tmp_path / "output"
    output_root.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    (output_root / "safe-problem").symlink_to(outside, target_is_directory=True)
    monkeypatch.setattr(
        command.common,
        "resolve_problem_catalog_root",
        lambda _: catalog_root,
    )

    with pytest.raises(typer.Exit):
        command._resolve_problem_destination(
            _context(), "safe-problem", output_root
        )

    assert list(outside.iterdir()) == []


def test_resolve_problem_destination_rejects_symlink_to_output_root(
    tmp_path, monkeypatch
):
    catalog_root = _catalog_root(tmp_path)
    output_root = tmp_path / "output"
    output_root.mkdir()
    sentinel = output_root / "existing.txt"
    sentinel.write_text("preserve")
    (output_root / "safe-problem").symlink_to(
        output_root, target_is_directory=True
    )
    monkeypatch.setattr(
        command.common,
        "resolve_problem_catalog_root",
        lambda _: catalog_root,
    )

    with pytest.raises(typer.Exit):
        command._resolve_problem_destination(
            _context(), "safe-problem", output_root
        )

    assert sentinel.read_text() == "preserve"


def test_resolve_problem_destination_allows_only_catalog_problem_under_output(
    tmp_path, monkeypatch
):
    catalog_root = _catalog_root(tmp_path)
    output_root = tmp_path / "output"
    monkeypatch.setattr(
        command.common,
        "resolve_problem_catalog_root",
        lambda _: catalog_root,
    )

    problem_path, save_dir = command._resolve_problem_destination(
        _context(), "safe-problem", output_root
    )

    assert problem_path == (catalog_root / "safe-problem").resolve()
    assert save_dir == (output_root / "safe-problem").resolve()
    assert not output_root.exists()


def test_infer_problem_rejects_non_strict_policy_before_creating_output(
    tmp_path: Path,
) -> None:
    output_path = tmp_path / "output"

    with pytest.raises(typer.Exit):
        command.infer_problem(
            ctx=_context(),
            problem_name="safe-problem",
            agent_config_path=tmp_path / "agent.yaml",
            environment_config_path=tmp_path / "environment.yaml",
            output_path=output_path,
            prompt_template_path=tmp_path / "prompt.md",
            model_override="provider/model",
            provider_api_key_env=None,
            thinking=None,
            max_thinking_tokens=None,
            assessment_policy="any-case",
            continue_after_test_failure=False,
            evaluate=True,
        )

    assert not output_path.exists()


@pytest.mark.parametrize("continue_after_test_failure", [False, True])
def test_infer_problem_keeps_policy_strict_when_continuing(
    tmp_path: Path,
    monkeypatch,
    continue_after_test_failure: bool,  # noqa: FBT001
) -> None:
    output_path = tmp_path / "output"
    save_dir = output_path / "safe-problem"
    prompt_template_path = tmp_path / "prompt.md"
    prompt_template_path.write_text("prompt")
    captured_run_spec: dict[str, object] = {}
    run_spec = SimpleNamespace(verbose=False, image=None)

    def create_run_spec(**kwargs: object) -> SimpleNamespace:
        captured_run_spec.update(kwargs)
        return run_spec

    monkeypatch.setattr(
        command,
        "_resolve_problem_destination",
        lambda _ctx, _name, _output: (tmp_path / "catalog-problem", save_dir),
    )
    monkeypatch.setattr(
        command.utils,
        "parse_model_override",
        lambda _model: SimpleNamespace(name="model", provider="provider"),
    )
    monkeypatch.setattr(command.ModelCatalog, "get", lambda _name: object())
    monkeypatch.setattr(
        command,
        "API_KEY_STORE",
        SimpleNamespace(resolve=lambda _provider, env_var_override: object()),
    )
    monkeypatch.setattr(
        command.config_loader,
        "load_agent_config",
        lambda _path: (None, {}),
    )
    monkeypatch.setattr(
        command,
        "build_agent_config",
        lambda _data: SimpleNamespace(type="test", docker_template=None),
    )
    monkeypatch.setattr(
        command.config_loader,
        "resolve_environment",
        lambda _path: command.LocalEnvironmentSpec(name="local"),
    )
    monkeypatch.setattr(
        command.ProblemConfig,
        "from_yaml",
        lambda _path: MagicMock(),
    )
    monkeypatch.setattr(command, "AgentRunSpec", create_run_spec)
    monkeypatch.setattr(
        command.Agent,
        "from_config",
        lambda *_args, **_kwargs: MagicMock(),
    )
    monkeypatch.setattr(command.runner, "run_agent", lambda **_kwargs: None)
    monkeypatch.setattr(command, "setup_logging", lambda *_args: None)

    command.infer_problem(
        ctx=cast(
            typer.Context,
            SimpleNamespace(
                obj=SimpleNamespace(seed=1, verbosity=0, overwrite=False)
            ),
        ),
        problem_name="safe-problem",
        agent_config_path=tmp_path / "agent.yaml",
        environment_config_path=tmp_path / "environment.yaml",
        output_path=output_path,
        prompt_template_path=prompt_template_path,
        model_override="provider/model",
        provider_api_key_env=None,
        thinking=None,
        max_thinking_tokens=None,
        assessment_policy="all-cases",
        continue_after_test_failure=continue_after_test_failure,
        evaluate=True,
    )

    assert captured_run_spec["assessment_policy"] is PassPolicy.ALL_CASES
    assert (
        captured_run_spec["continue_after_test_failure"]
        is continue_after_test_failure
    )
