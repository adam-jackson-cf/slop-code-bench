"""Delta computation between consecutive checkpoints.

This module provides functions to compute percentage changes in metrics
between consecutive checkpoints.
"""

from __future__ import annotations

from typing import Any

# Metric keys for which to compute percentage deltas between checkpoints.
# Each key will be prefixed with "delta." in the output.
# Only keys that are actually consumed by dashboard/summary/variance.
DELTA_METRIC_KEYS: tuple[str, ...] = (
    "loc",
    "verbosity",
)


def safe_ratio(
    numerator: float | None, denominator: float | None
) -> float | None:
    """Compute numerator / denominator with zero handling.

    Returns ``None`` when either input is unavailable. Otherwise returns zero
    if both are zero, or infinity if only the denominator is zero.
    """
    if numerator is None or denominator is None:
        return None
    if denominator == 0:
        return 0.0 if numerator == 0 else float("inf")
    return numerator / denominator


def safe_delta_pct(
    prev_val: float | None, curr_val: float | None
) -> float | None:
    """Compute a percentage delta without treating missing values as zero."""
    if prev_val is None or curr_val is None:
        return None
    ratio = safe_ratio(curr_val - prev_val, prev_val)
    return ratio * 100 if ratio is not None else None


def compute_checkpoint_delta(
    prev_metrics: dict[str, Any] | None,
    curr_metrics: dict[str, Any],
) -> dict[str, float | None]:
    """Compute percentage delta metrics between two consecutive checkpoints.

    When either measurement is unavailable, returns ``None`` for that delta.
    When the previous measured value is zero, returns ``float('inf')`` if the
    current value is positive, else zero.

    Args:
        prev_metrics: Metrics from checkpoint N (from get_checkpoint_metrics).
                      Pass None for first checkpoint.
        curr_metrics: Metrics from checkpoint N+1.

    Returns:
        Dict with delta.* keys containing percentage changes.
        Returns empty dict if prev_metrics is None (first checkpoint).
    """
    if prev_metrics is None:
        return {}

    result: dict[str, float | None] = {}

    # Compute percentage deltas for all standard metrics
    for key in DELTA_METRIC_KEYS:
        result[f"delta.{key}"] = safe_delta_pct(
            prev_metrics.get(key), curr_metrics.get(key)
        )

    lines_added = curr_metrics.get("lines_added")
    lines_removed = curr_metrics.get("lines_removed")
    churn = (
        lines_added + lines_removed
        if isinstance(lines_added, int | float)
        and isinstance(lines_removed, int | float)
        else None
    )
    result["delta.churn_ratio"] = safe_ratio(
        churn, prev_metrics.get("total_lines")
    )

    return result
