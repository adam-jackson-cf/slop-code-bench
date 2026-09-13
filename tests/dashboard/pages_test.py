from __future__ import annotations

import math
from unittest.mock import patch

import dash
import pandas as pd
import plotly.graph_objects as go

from slop_code.dashboard.data import ChartContext

with patch.object(dash, "register_page"):
    from slop_code.dashboard.pages import head_to_head_efficiency
    from slop_code.dashboard.pages import head_to_head_evolution
    from slop_code.dashboard.pages import head_to_head_quality
    from slop_code.dashboard.pages import problem_comparison
    from slop_code.dashboard.pages import run_analysis_quality
    from slop_code.dashboard.pages import run_analysis_tests


def make_context(checkpoints: pd.DataFrame) -> ChartContext:
    return ChartContext(checkpoints, pd.DataFrame(), {}, {})


def test_test_rates_exclude_empty_category_checkpoints(
    monkeypatch,
) -> None:
    checkpoints = pd.DataFrame(
        [
            {
                "problem": "problem-a",
                "idx": 1,
                "tests.core.passed": 10,
                "tests.core.total": 10,
            },
            {
                "problem": "problem-a",
                "idx": 2,
                "tests.core.passed": 0,
                "tests.core.total": 0,
            },
        ]
    )
    monkeypatch.setattr(
        run_analysis_tests, "build_context", lambda _: make_context(checkpoints)
    )

    bar, evolution = run_analysis_tests.update_tests("run")

    assert bar.data[0].y[0] == 100
    core_rates = dict(zip(evolution.data[0].x, evolution.data[0].y))
    assert core_rates[50] == 100
    assert math.isnan(core_rates[100])


def test_quality_histograms_only_include_measured_values(
    monkeypatch,
) -> None:
    checkpoints = pd.DataFrame({"cc_high_count": [2, None]})
    monkeypatch.setattr(
        run_analysis_quality,
        "build_context",
        lambda _: make_context(checkpoints),
    )

    _, complexity, _, cc_mass, cc_concentration, _ = (
        run_analysis_quality.update_quality("run")
    )

    assert list(complexity.data[0].x) == [2]
    assert not cc_mass.data
    assert not cc_concentration.data


def test_problem_selector_uses_chart_filters_and_clears_excluded_value(
    monkeypatch,
) -> None:
    checkpoints = pd.DataFrame({"problem": ["shared"]})
    received_settings = []

    def build_context(_selected_paths, **settings):
        received_settings.append(settings)
        return make_context(checkpoints)

    chart = go.Figure()
    monkeypatch.setattr(problem_comparison, "build_context", build_context)
    monkeypatch.setattr(
        problem_comparison, "build_problem_comparison_chart", lambda *_: chart
    )

    options, value = problem_comparison.update_problem_options(
        ["run-a", "run-b"], {"common_problems_only": True}, "excluded"
    )
    rendered = problem_comparison.update_graph(
        ["run-a", "run-b"], "shared", {"common_problems_only": True}
    )

    assert options == [{"label": "shared", "value": "shared"}]
    assert value is None
    assert rendered is chart
    assert all(
        settings["common_problems_only"] for settings in received_settings
    )


def test_missing_lint_does_not_hide_complexity_comparison(
    monkeypatch,
) -> None:
    checkpoints = pd.DataFrame(
        [
            {
                "run_path": "run-a",
                "problem": "problem-a",
                "idx": 1,
                "cc_high_count": 2,
                "model_name": "A",
            },
            {
                "run_path": "run-b",
                "problem": "problem-a",
                "idx": 1,
                "cc_high_count": 3,
                "model_name": "B",
            },
        ]
    )
    monkeypatch.setattr(
        head_to_head_quality,
        "build_context",
        lambda _: make_context(checkpoints),
    )

    lint, complexity = head_to_head_quality.update_quality("run-a", "run-b")

    assert not lint.data
    assert len(complexity.data) == 1
    assert list(complexity.data[0].x) == [2]
    assert list(complexity.data[0].y) == [3]


def test_trends_use_latest_checkpoint_state_and_terminal_cost(
    monkeypatch,
) -> None:
    checkpoints = pd.DataFrame(
        [
            {
                "run_path": run_path,
                "problem": "problem-a",
                "idx": idx,
                "cost": cost,
                "loc": loc,
                "cc_high_count": 1,
                "model_name": run_path,
            }
            for run_path in ("run-a", "run-b")
            for idx, cost, loc in ((2, 3, 2), (1, 2, 1), (100, 4, 100))
        ]
    )
    context = make_context(checkpoints)
    monkeypatch.setattr(
        head_to_head_efficiency, "build_context", lambda _: context
    )
    monkeypatch.setattr(
        head_to_head_evolution, "build_context", lambda _: context
    )

    _, cumulative_cost, _, _ = head_to_head_efficiency.update_efficiency(
        "run-a", "run-b"
    )
    loc, _, _ = head_to_head_evolution.update_evolution("run-a", "run-b")

    assert cumulative_cost.data[2].x[-1] == 100
    assert cumulative_cost.data[2].y[-1] == 9
    assert loc.data[2].x[0] == 0
    assert loc.data[2].y[0] == 2
