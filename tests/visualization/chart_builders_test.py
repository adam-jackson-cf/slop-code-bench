"""Regression tests for visualization chart builders."""

from __future__ import annotations

import pandas as pd
import pytest

from slop_code.visualization.chart_builders import ProgressLineChartBuilder
from slop_code.visualization.chart_builders import ProgressLineChartConfig


@pytest.mark.parametrize("num_bins", [2, 5, 10])
def test_progress_points_are_visible_for_configured_bin_counts(
    num_bins: int,
) -> None:
    checkpoints = pd.DataFrame(
        {
            "model": pd.Series(["gpt-5.1-codex-max"] * 10),
            "agent_version": pd.Series(["2.0.51"] * 10),
            "thinking": pd.Series(["high"] * 10),
            "checkpoint": pd.Series(
                [f"checkpoint_{number}" for number in range(1, 11)]
            ),
            "problem": pd.Series(["problem"] * 10),
            "score": pd.Series(range(10)),
        }
    )
    config = ProgressLineChartConfig(
        metric_col="score",
        y_title="Score",
        title="Progress",
        num_bins=num_bins,
    )

    figure = ProgressLineChartBuilder(config).build(checkpoints)
    lower, upper = figure.layout.xaxis.range

    assert all(lower <= point <= upper for point in figure.data[0].x)
