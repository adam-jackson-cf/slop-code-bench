"""Tests for mass helpers and the reduced CC mass metric."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

import numpy as np
import pandas as pd
import pytest

from slop_code.metrics.checkpoint.mass import _compute_gini_coefficient
from slop_code.metrics.checkpoint.mass import compute_mass_metrics
from slop_code.metrics.checkpoint.mass import compute_top20_share


def _load_script(name: str) -> ModuleType:
    path = Path(__file__).parents[2] / "scripts" / f"{name}.py"
    spec = importlib.util.spec_from_file_location(f"{name}_under_test", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


mass_delta_analysis = _load_script("mass_delta_analysis")
analyze_transition = mass_delta_analysis.analyze_transition
calc_mass = mass_delta_analysis.calc_mass
compute_distribution = mass_delta_analysis.compute_distribution
match_symbols = mass_delta_analysis.match_symbols


class TestComputeGiniCoefficient:
    def test_uniform_distribution_returns_zero(self):
        assert _compute_gini_coefficient([10.0] * 100) == 0.0

    def test_empty_list_returns_zero(self):
        assert _compute_gini_coefficient([]) == 0.0

    def test_known_distribution(self):
        gini = _compute_gini_coefficient([1.0, 2.0, 3.0, 4.0, 5.0])
        assert 0.26 < gini < 0.28


class TestComputeTop20Share:
    def test_empty_list_returns_zero(self):
        assert compute_top20_share([]) == 0.0

    def test_uniform_distribution(self):
        values = [10.0] * 100
        assert compute_top20_share(values) == pytest.approx(0.20, abs=0.01)

    def test_concentrated_distribution(self):
        values = [100.0] + [0.001] * 99
        assert compute_top20_share(values) > 0.95


class TestComputeMassMetrics:
    def test_returns_cc_mass_and_high_cc_pct(self):
        result = compute_mass_metrics(
            iter(
                [
                    {
                        "type": "function",
                        "complexity": 5,
                        "sloc": 9,
                    },
                    {
                        "type": "method",
                        "complexity": 16,
                        "sloc": 25,
                    },
                    {
                        "type": "class",
                        "complexity": 99,
                        "sloc": 100,
                    },
                ]
            )
        )

        assert result["mass.cc"] == pytest.approx(95.0)
        assert result["mass.high_cc_pct"] == pytest.approx(0.8421, abs=0.0001)

    def test_uses_true_sloc_not_lines_or_statements(self):
        result = compute_mass_metrics(
            iter(
                [
                    {
                        "type": "function",
                        "complexity": 2,
                        "sloc": 100,
                        "lines": 1,
                        "statements": 1,
                    },
                    {
                        "type": "function",
                        "complexity": 20,
                        "sloc": 1,
                        "lines": 1000,
                        "statements": 100,
                    },
                ]
            )
        )

        assert result["mass.cc"] == pytest.approx(40.0)
        assert result["mass.high_cc_pct"] == pytest.approx(0.5)

    def test_zero_or_missing_sloc_contributes_no_mass(self):
        result = compute_mass_metrics(
            iter(
                [
                    {"type": "function", "complexity": 7, "sloc": 0},
                    {"type": "method", "complexity": 4},
                ]
            )
        )

        assert result == {"mass.cc": 0.0, "mass.high_cc_pct": 0.0}

    def test_empty_symbols_returns_zero_mass(self):
        assert compute_mass_metrics(iter([])) == {
            "mass.cc": 0.0,
            "mass.high_cc_pct": 0.0,
        }


class TestMassDeltaDistribution:
    @pytest.mark.parametrize(
        ("masses", "expected"),
        [
            (np.array([50.0, 30.0, 20.0]), (1, 2, 3)),
            (np.array([60.0, 25.0, 15.0]), (1, 2, 3)),
            (np.array([25.0, 25.0, 25.0, 25.0]), (2, 3, 4)),
            (np.array([100.0, 0.0, 0.0]), (1, 1, 1)),
        ],
    )
    def test_prefixes_are_minimal_and_reach_each_threshold(
        self, masses, expected
    ):
        result = compute_distribution(masses)
        sorted_masses = np.sort(masses)[::-1]
        for percentage, count in zip((0.5, 0.75, 0.9), expected):
            threshold = masses.sum() * percentage
            assert (
                result[f"top_{int(percentage * 100)}_pct_symbol_count"] == count
            )
            assert sorted_masses[:count].sum() >= threshold
            assert count == 1 or sorted_masses[: count - 1].sum() < threshold

    def test_empty_masses_have_no_prefix(self):
        assert compute_distribution(np.array([])) == {
            "top_50_pct_symbol_count": 0,
            "top_75_pct_symbol_count": 0,
            "top_90_pct_symbol_count": 0,
            "total_symbol_count": 0,
        }


class TestMassDeltaMatching:
    def test_scoped_symbols_match_once_and_ambiguous_symbols_do_not_merge(self):
        def symbol(parent_class, name, complexity):
            return {
                "file_path": "a.py",
                "parent_class": parent_class,
                "name": name,
                "complexity": complexity,
                "branches": 0,
                "comparisons": 0,
                "variables_used": 0,
                "variables_defined": 0,
                "exception_scaffold": 0,
                "statements": 4,
                "lines": 4,
            }

        before = pd.DataFrame(
            [
                symbol("One", "run", 2),
                symbol("Two", "run", 3),
                symbol("", "duplicate", 4),
                symbol("", "duplicate", 5),
            ]
        )
        after = before.copy()
        after.loc[0, "complexity"] = 6

        matched, added, removed = match_symbols(before, after)
        metrics = analyze_transition(before, after, alpha=0.5)["metrics"][
            "complexity"
        ]["by_statements"]

        assert len(matched) == 2
        assert set(matched["parent_class_before"]) == {"One", "Two"}
        assert len(added) == len(removed) == 2
        assert (
            metrics["total_mass_before"]
            == calc_mass(
                before["complexity"].to_numpy(),
                before["statements"].to_numpy(),
                baseline=1,
                alpha=0.5,
            ).sum()
        )
        assert (
            metrics["total_mass_after"]
            == calc_mass(
                after["complexity"].to_numpy(),
                after["statements"].to_numpy(),
                baseline=1,
                alpha=0.5,
            ).sum()
        )
