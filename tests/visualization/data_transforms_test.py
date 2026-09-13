"""Regression tests for visualization data transforms."""

from __future__ import annotations

import pandas as pd

from slop_code.visualization.data_transforms import (
    select_best_version_per_model,
)


def test_select_best_version_uses_numeric_version_components() -> None:
    rows: list[tuple[str, str]] = [
        ("patch", "2.0.9"),
        ("patch", "2.0.51"),
        ("minor", "2.9.0"),
        ("minor", "2.10.0"),
        ("major", "9.0.0"),
        ("major", "10.0.0"),
        ("opus-4.5", "2.0.51"),
        ("opus-4.5", "9.0.0"),
    ]
    versions = pd.DataFrame(
        {
            "model": [model for model, _ in rows],
            "agent_version": [version for _, version in rows],
        }
    )

    selected = select_best_version_per_model(versions).set_index("model")

    assert selected.loc["patch", "agent_version"] == "2.0.51"
    assert selected.loc["minor", "agent_version"] == "2.10.0"
    assert selected.loc["major", "agent_version"] == "10.0.0"
    assert selected.loc["opus-4.5", "agent_version"] == "2.0.51"
