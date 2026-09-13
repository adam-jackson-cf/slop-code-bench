from __future__ import annotations

import json
from typing import Any

from slop_code.dashboard.settings_callbacks import _manage_run_selection_logic


class _CallbackContext:
    def __init__(self, component_id: str, *, value: bool) -> None:
        self.triggered = [
            {
                "prop_id": f"{component_id}.value",
                "value": value,
            }
        ]


def _run(
    component_id: str,
    *,
    value: bool,
    runs: list[dict[str, Any]],
    selection: list[str],
    appearance_options: list[str],
) -> tuple[list[str], dict[str, object]]:
    _, new_selection, saved_settings = _manage_run_selection_logic(
        None,
        None,
        0,
        ["disabled"],
        appearance_options,
        None,
        None,
        [],
        [],
        [],
        runs,
        selection,
        {},
        None,
        _CallbackContext(component_id, value=value),
    )
    return new_selection, saved_settings


def _runs() -> list[dict[str, Any]]:
    return [
        {
            "value": "/runs/dir-a-one",
            "model_name": "Model A",
            "prompt_template": "Prompt 1",
            "thinking_display": "disabled",
            "run_date": "",
            "num_problems": 1,
        },
        {
            "value": "/runs/dir-a-two",
            "model_name": "Model A",
            "prompt_template": "Prompt 2",
            "thinking_display": "disabled",
            "run_date": "",
            "num_problems": 1,
        },
        {
            "value": "/runs/dir-b-one",
            "model_name": "Model B",
            "prompt_template": "Prompt 1",
            "thinking_display": "disabled",
            "run_date": "",
            "num_problems": 1,
        },
    ]


def test_model_bulk_selection_uses_model_name_and_preserves_grouping() -> None:
    runs = _runs()
    group_id = json.dumps({"type": "group-select-switch", "index": "Model A"})

    selection, settings = _run(
        group_id,
        value=True,
        runs=runs,
        selection=["/runs/dir-b-one"],
        appearance_options=[],
    )

    assert set(selection) == {
        "/runs/dir-a-one",
        "/runs/dir-a-two",
        "/runs/dir-b-one",
    }
    assert settings["group_runs"] is False

    selection, settings = _run(
        group_id,
        value=False,
        runs=runs,
        selection=selection,
        appearance_options=["group_runs"],
    )

    assert selection == ["/runs/dir-b-one"]
    assert settings["group_runs"] is True


def test_prompt_bulk_selection_uses_prompt_template_and_exact_type() -> None:
    runs = _runs()
    prompt_id = json.dumps(
        {"type": "subgroup-select-switch", "index": "Model A|Prompt 1"}
    )

    selection, settings = _run(
        prompt_id,
        value=True,
        runs=runs,
        selection=["/runs/dir-a-two", "/runs/dir-b-one"],
        appearance_options=[],
    )

    assert set(selection) == {
        "/runs/dir-a-one",
        "/runs/dir-a-two",
        "/runs/dir-b-one",
    }
    assert settings["group_runs"] is False

    selection, settings = _run(
        prompt_id,
        value=False,
        runs=runs,
        selection=selection,
        appearance_options=["group_runs"],
    )

    assert set(selection) == {"/runs/dir-a-two", "/runs/dir-b-one"}
    assert settings["group_runs"] is True

    runs_with_model_named_dirs = [
        {
            **run,
            "value": f"/runs/{run['model_name']}/{index}",
        }
        for index, run in enumerate(runs)
    ]
    selection, _ = _run(
        json.dumps({"type": "not-group-select-switch", "index": "Model A"}),
        value=True,
        runs=runs_with_model_named_dirs,
        selection=["/runs/Model B/2"],
        appearance_options=[],
    )

    assert selection == ["/runs/Model B/2"]
