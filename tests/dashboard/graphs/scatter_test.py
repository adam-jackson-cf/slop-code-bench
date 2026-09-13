from __future__ import annotations

import pandas as pd

from slop_code.dashboard.data import ChartContext
from slop_code.dashboard.graphs.scatter import SCATTER_CHARTS
from slop_code.dashboard.graphs.scatter import aggregate_time_vs_solve
from slop_code.dashboard.graphs.scatter import build_multi_scatter_chart
from slop_code.dashboard.graphs.scatter import build_scatter_chart


def _build_context(run_summaries: pd.DataFrame) -> ChartContext:
    return ChartContext(
        checkpoints=pd.DataFrame(),
        run_summaries=run_summaries,
        color_map={},
        base_color_map={"Run A": "#123456"},
    )


def test_aggregate_time_vs_solve_skips_missing_time() -> None:
    context = _build_context(
        pd.DataFrame(
            [
                {
                    "display_name": "Run A",
                    "model_name": "model-a",
                    "thinking": "none",
                    "prompt_template": "default",
                    "agent_type": "codex",
                    "agent_version": "1",
                    "run_date": "2026-03-20",
                    "pct_checkpoints_solved": 80.0,
                }
            ]
        )
    )

    metrics = aggregate_time_vs_solve(context)

    assert metrics == []


def test_scatter_catalog_needs_no_scb_metrics() -> None:
    assert all(
        "verbosity" not in chart and "erosion" not in chart
        for chart in SCATTER_CHARTS
    )


def test_quality_scatters_render_zero_metrics_with_annotations() -> None:
    run_summaries = pd.DataFrame(
        [
            {
                "display_name": "Zero",
                "model_name": "model-a",
                "thinking": "none",
                "prompt_template": "default",
                "agent_type": "codex",
                "agent_version": "1",
                "run_date": "2026-03-20",
                "pct_checkpoints_solved": 20.0,
                "ratios.lint.mean": 0.0,
                "ratios.rubric.mean": 0.0,
            },
            {
                "display_name": "Positive",
                "model_name": "model-a",
                "thinking": "none",
                "prompt_template": "default",
                "agent_type": "codex",
                "agent_version": "1",
                "run_date": "2026-03-21",
                "pct_checkpoints_solved": 80.0,
                "ratios.lint.mean": 2.0,
                "ratios.rubric.mean": 3.0,
            },
        ]
    )
    context = ChartContext(
        checkpoints=pd.DataFrame(),
        run_summaries=run_summaries,
        color_map={},
        base_color_map={"Zero": "#123456", "Positive": "#654321"},
    )

    single = build_scatter_chart(context, "lint_vs_solve")
    multi = build_multi_scatter_chart(
        context, ["lint_vs_solve", "rubric_vs_solve"]
    )

    assert single.layout.xaxis.type == "linear"
    assert {trace.x[0] for trace in single.data} == {0.0, 2.0}
    assert {
        annotation.x
        for annotation in single.layout.annotations
        if annotation.xref == "x"
    } == {0.0, 2.0}
    assert multi.layout.xaxis.type == "linear"
    assert multi.layout.xaxis2.type == "linear"
    assert {
        annotation.x
        for annotation in multi.layout.annotations
        if annotation.xref in {"x", "x2"}
    } == {0.0, 2.0, 3.0}
