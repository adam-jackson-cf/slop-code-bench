from __future__ import annotations

from typing import TYPE_CHECKING

import pandas as pd

if TYPE_CHECKING:
    import plotly.graph_objects as go

from slop_code.dashboard.data import ChartContext
from slop_code.dashboard.graphs.boxplot import build_checkpoint_delta_boxplot
from slop_code.dashboard.graphs.comparison import build_problem_comparison_chart
from slop_code.dashboard.graphs.test_pass import build_test_pass_rate_bars


def _titles(figure: go.Figure) -> set[str]:
    return {
        annotation.text
        for annotation in figure.layout.annotations
        if annotation.text
    }


def _chart_row(
    *,
    display_name: str = "Run A",
    model_name: str = "model-a",
    run_date: str = "2026-07-28",
    run_path: str = "run-a",
    idx: int = 1,
    **overrides: object,
) -> dict[str, object]:
    row: dict[str, object] = {
        "display_name": display_name,
        "model_name": model_name,
        "_thinking_sort_key": 0,
        "thinking": "none",
        "prompt_template": "default",
        "agent_type": "codex",
        "agent_version": "1",
        "run_date": run_date,
        "run_path": run_path,
        "problem": "prob1",
        "idx": idx,
        "loc": 10 * idx,
        "lint_errors": idx,
        "cc_high_count": idx,
        "cc_max": idx + 1,
        "rubric_total_flags": idx,
        "rubric_carried_over": 0,
        "output": 100 * idx,
        "cost": 0.1 * idx,
        "passed_tests": 10,
        "total_tests": 10,
        "core_passed": 10,
        "core_total": 10,
        "functionality_passed": 10,
        "functionality_total": 10,
        "regression_passed": 10,
        "regression_total": 10,
        "error_passed": 10,
        "error_total": 10,
        "mass.cc": float(idx),
        "delta.loc": float(idx),
        "delta.churn_ratio": 0.1 * idx,
        "cc_concentration": 0.1 * idx,
    }
    row.update(overrides)
    return row


def test_quality_charts_need_no_scb_metrics() -> None:
    metadata = {
        "display_name": "Run A",
        "model_name": "model-a",
        "_thinking_sort_key": 0,
        "thinking": "none",
        "prompt_template": "default",
        "agent_type": "codex",
        "agent_version": "1",
        "run_date": "2026-07-28",
    }
    checkpoints = pd.DataFrame(
        [
            {
                **metadata,
                "problem": "prob1",
                "idx": idx,
                "loc": 10 * idx,
                "lint_errors": 3 - idx,
                "cc_high_count": idx,
                "cc_max": idx + 2,
                "rubric_total_flags": idx,
                "rubric_carried_over": idx - 1,
                "output": 100 * idx,
                "cost": 0.1 * idx,
                "passed_tests": idx,
                "total_tests": 2,
                "core_passed": idx,
                "core_total": 2,
                "functionality_passed": idx,
                "functionality_total": 2,
                "regression_passed": idx,
                "regression_total": 2,
                "error_passed": idx,
                "error_total": 2,
                "mass.cc": 0.1 * idx,
                "delta.loc": 0.2 * idx,
                "delta.churn_ratio": 0.3 * idx,
                "cc_concentration": 0.4 * idx,
            }
            for idx in (1, 2)
        ]
    )
    context = ChartContext(
        checkpoints=checkpoints,
        run_summaries=pd.DataFrame([metadata]),
        color_map={"Run A": "#123456"},
        base_color_map={"Run A": "#123456"},
    )

    comparison = build_problem_comparison_chart(context, "prob1")
    deltas = build_checkpoint_delta_boxplot(context)

    assert comparison.data
    assert deltas.data
    assert "Verbosity" not in _titles(comparison)
    assert "Verbosity" not in _titles(deltas)


def test_missing_rubric_columns_preserve_checkpoint_alignment() -> None:
    frame = pd.DataFrame(
        [
            _chart_row(idx=1, rubric_total_flags=4, rubric_carried_over=1),
            _chart_row(idx=2, rubric_total_flags=7, rubric_carried_over=3),
        ],
        index=pd.Index([4, 19]),
    )

    for columns, expected in [
        (["rubric_total_flags"], [-1.0, -3.0]),
        (["rubric_carried_over"], [4.0, 7.0]),
        (["rubric_total_flags", "rubric_carried_over"], [0.0, 0.0]),
    ]:
        figure = build_problem_comparison_chart(
            ChartContext(
                checkpoints=frame.drop(columns=columns),
                run_summaries=frame.iloc[:1],
                color_map={"Run A": "#123456"},
                base_color_map={"Run A": "#123456"},
            ),
            "prob1",
        )

        assert list(figure.data[4].y) == expected


def test_grouped_chart_traces_render_each_display_name_once() -> None:
    rows = [
        _chart_row(
            display_name="Group A",
            run_path="a-early",
            run_date="2026-07-01",
            idx=1,
            loc=10,
            passed_tests=10,
        ),
        _chart_row(
            display_name="Group A",
            run_path="a-early",
            run_date="2026-07-01",
            idx=2,
            loc=20,
            passed_tests=10,
        ),
        _chart_row(
            display_name="Group A",
            run_path="a-late",
            run_date="2026-07-02",
            idx=1,
            loc=30,
            passed_tests=5,
        ),
        _chart_row(
            display_name="Group A",
            run_path="a-late",
            run_date="2026-07-02",
            idx=2,
            loc=40,
            passed_tests=5,
        ),
        _chart_row(
            display_name="Group B",
            model_name="model-b",
            run_path="b-early",
            run_date="2026-07-01",
            idx=1,
            loc=15,
            passed_tests=8,
        ),
        _chart_row(
            display_name="Group B",
            model_name="model-b",
            run_path="b-early",
            run_date="2026-07-01",
            idx=2,
            loc=25,
            passed_tests=8,
        ),
        _chart_row(
            display_name="Group B",
            model_name="model-b",
            run_path="b-late",
            run_date="2026-07-02",
            idx=1,
            loc=35,
            passed_tests=6,
        ),
        _chart_row(
            display_name="Group B",
            model_name="model-b",
            run_path="b-late",
            run_date="2026-07-02",
            idx=2,
            loc=45,
            passed_tests=6,
        ),
    ]
    frame = pd.DataFrame(rows)
    context = ChartContext(
        checkpoints=frame,
        run_summaries=frame.drop_duplicates("run_path"),
        color_map={"Group A": "#123456", "Group B": "#654321"},
        base_color_map={"Group A": "#123456", "Group B": "#654321"},
        group_runs=True,
    )

    comparison = build_problem_comparison_chart(context, "prob1")
    deltas = build_checkpoint_delta_boxplot(context)
    test_pass = build_test_pass_rate_bars(context)

    assert len(comparison.data) == 32
    assert list(comparison.data[0].y) == [20.0, 30.0]
    assert len(deltas.data) == 10
    assert all(len(trace.y) == 3 for trace in deltas.data)
    assert len(test_pass.data) == 10
    assert list(test_pass.data[0].y) == [75.0]
    assert list(test_pass.data[5].y) == [70.0]
    assert test_pass.layout.yaxis5.title.text == "Avg Pass %"
    assert all(
        0 <= value <= 100 for trace in test_pass.data for value in trace.y
    )
