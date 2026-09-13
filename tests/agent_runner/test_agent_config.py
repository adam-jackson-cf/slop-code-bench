"""Tests for shared agent configuration behavior."""

from __future__ import annotations

from pathlib import Path

import pytest

from slop_code.agent_runner.agent import AgentConfigBase
from slop_code.agent_runner.models import AgentCostLimits


def _config(template: Path) -> AgentConfigBase:
    return AgentConfigBase(
        type="test_agent",
        version="1.2.3",
        cost_limits=AgentCostLimits(
            step_limit=1,
            cost_limit=1.0,
            net_cost_limit=1.0,
        ),
        docker_template=template,
    )


def test_docker_template_receives_version(tmp_path: Path) -> None:
    template = tmp_path / "Dockerfile.jinja"
    template.write_text("FROM {{ base_image }}\nRUN install {{ version }}\n")

    rendered = _config(template).get_docker_file("python:3.12")

    assert rendered == "FROM python:3.12\nRUN install 1.2.3"


def test_docker_template_rejects_unknown_variables(tmp_path: Path) -> None:
    template = tmp_path / "Dockerfile.jinja"
    template.write_text(
        "FROM {{ base_image }}\nRUN install {{ unknown_field }}\n"
    )

    with pytest.raises(
        ValueError, match="Invalid Docker template.*unknown_field"
    ):
        _config(template).get_docker_file("python:3.12")
