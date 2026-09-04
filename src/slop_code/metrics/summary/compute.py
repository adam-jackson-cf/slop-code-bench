"""Main entry point for run summary computation.

This module provides the orchestrating function that combines all aggregators
to produce a complete RunSummary.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from slop_code.metrics.models import RunSummary
from slop_code.metrics.summary import aggregators
from slop_code.metrics.summary.stats import group_by_problem


def compute_run_summary(
    config: dict,
    checkpoints: list[dict[str, Any]],
    expected_checkpoints: int,
) -> RunSummary:
    """Compute complete summary statistics from checkpoint data.

    Args:
        config: Run configuration dictionary.
        checkpoints: List of checkpoint data dictionaries.
        expected_checkpoints: Total checkpoints the run was configured
            to attempt (sum across the problem list). Used as the
            pct_checkpoints_* denominator; if the agent crashed, the
            produced count is less than this and missing checkpoints
            count as unsolved.

    Returns:
        RunSummary with all computed statistics.
    """
    problems = group_by_problem(checkpoints)

    solve_rates = aggregators.compute_solve_rates(
        checkpoints, problems, expected_checkpoints
    )
    solve_rate_counts = {
        name: value
        for name, value in solve_rates.items()
        if isinstance(value, int)
    }
    solve_rate_percentages = {
        name: float(value)
        for name, value in solve_rates.items()
        if isinstance(value, int | float)
    }

    return RunSummary(
        model=config["model"]["name"],
        thinking=config["thinking"],
        prompt=Path(config["prompt_path"]).stem,
        agent_type=config["agent"]["type"],
        agent_version=config["agent"].get("version"),
        num_problems=len(problems),
        num_checkpoints=len(checkpoints),
        expected_checkpoints=expected_checkpoints,
        costs=aggregators.compute_costs_stats(checkpoints, problems),
        time=aggregators.compute_time_stats(checkpoints, problems),
        tokens=aggregators.compute_tokens_stats(checkpoints, problems),
        steps=aggregators.compute_steps_stats(checkpoints, problems),
        checkpoints_solved=solve_rate_counts.get("checkpoints_solved", 0),
        checkpoints_iso_solved=solve_rate_counts.get(
            "checkpoints_iso_solved", 0
        ),
        checkpoints_core_solved=solve_rate_counts.get(
            "checkpoints_core_solved", 0
        ),
        problem_solved=solve_rate_percentages.get("problem_solved", 0.0),
        problem_partial=solve_rate_percentages.get("problem_partial", 0.0),
        pct_checkpoints_solved=solve_rate_percentages.get(
            "pct_checkpoints_solved", 0.0
        ),
        pct_checkpoints_iso_solved=solve_rate_percentages.get(
            "pct_checkpoints_iso_solved", 0.0
        ),
        pct_checkpoints_core_solved=solve_rate_percentages.get(
            "pct_checkpoints_core_solved", 0.0
        ),
        pct_problems_solved=solve_rate_percentages.get(
            "pct_problems_solved", 0.0
        ),
        pct_problems_partial=solve_rate_percentages.get(
            "pct_problems_partial", 0.0
        ),
        pass_rates=aggregators.compute_pass_rates_stats(checkpoints, problems),
        cc=aggregators.compute_cc_stats(checkpoints),
        ratios=aggregators.compute_ratios_stats(checkpoints),
        **aggregators.compute_composite_scores(checkpoints),
    )
