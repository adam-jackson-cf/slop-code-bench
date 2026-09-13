from pathlib import Path

import pytest
from rich.console import Console

from slop_code.common import CHECKPOINT_RESULTS_FILENAME
from slop_code.entrypoints.commands.variance import ConfidenceIntervalEntry
from slop_code.entrypoints.commands.variance import RunGroupKey
from slop_code.entrypoints.commands.variance import _collect_ci_entries
from slop_code.entrypoints.commands.variance import _discover_run_dirs
from slop_code.entrypoints.commands.variance import _metric_value
from slop_code.entrypoints.commands.variance import (
    _render_confidence_interval_table,
)
from slop_code.entrypoints.commands.variance import _render_problem_cv_summary


def _write_checkpoint_results_file(run_dir: Path) -> None:
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / CHECKPOINT_RESULTS_FILENAME).write_text("{}\n")


def test_discovers_runs_nested_under_model_dirs(tmp_path: Path) -> None:
    experiments_dir = tmp_path / "experiments"
    experiments_dir.mkdir()

    model_a = experiments_dir / "model_a"
    model_b = experiments_dir / "model_b"
    model_a.mkdir()
    model_b.mkdir()

    run_a = model_a / "run_a"
    run_b = model_b / "run_b"
    _write_checkpoint_results_file(run_a)
    _write_checkpoint_results_file(run_b)

    unrelated_dir = experiments_dir / "not_a_run"
    unrelated_dir.mkdir()

    discovered = _discover_run_dirs(experiments_dir)

    assert discovered == sorted([run_a, run_b])


def test_metric_value_reads_strict_and_isolated_pass_rates() -> None:
    row = {
        "strict_pass_rate": 0.7,
        "isolated_pass_rate": 0.8,
    }

    assert _metric_value(row, "strict_pass_rate") == 0.7
    assert _metric_value(row, "isolated_pass_rate") == 0.8


def test_render_problem_cv_summary_interleaves_first_final_values() -> None:
    console = Console(record=True, width=200)
    problem_cv_summary = {
        "sample": {
            "Pass rate": [0.3],
            "Lint": [0.1],
            "LOC": [0.5],
            "High CC count": [0.4],
        }
    }
    problem_first_cv_summary = {
        "sample": {
            "Pass rate": [0.11],
            "Lint": [0.22],
            "LOC": [0.33],
            "High CC count": [0.77],
        }
    }
    problem_final_cv_summary = {
        "sample": {
            "Pass rate": [0.44],
            "Lint": [0.55],
            "LOC": [0.66],
            "High CC count": [0.88],
        }
    }

    _render_problem_cv_summary(
        console,
        problem_cv_summary,
        problem_first_cv_summary,
        problem_final_cv_summary,
    )

    output = console.export_text()
    headers = [
        "Pass rate first CV",
        "Pass rate final CV",
        "Lint first CV",
        "Lint final CV",
        "LOC first CV",
        "LOC final CV",
        "High CC count first CV",
        "High CC count final CV",
    ]
    assert [output.index(header) for header in headers] == sorted(
        output.index(header) for header in headers
    )
    values_line = next(
        line
        for line in output.splitlines()
        if "sample" in line and "0.11" in line
    )
    values = [
        "0.11",
        "0.44",
        "0.22",
        "0.55",
        "0.33",
        "0.66",
        "0.77",
        "0.88",
    ]
    assert [values_line.index(value) for value in values] == sorted(
        values_line.index(value) for value in values
    )


def test_collect_ci_entries_filters_by_width() -> None:
    record = {
        "problem": "prob",
        "run_count": 3,
        "final.delta.loc.mean": 1.0,
        "final.delta.loc.ci95_low": 0.0,
        "final.delta.loc.ci95_high": 0.4,
        "final.delta.verbosity.mean": 1.0,
        "final.delta.verbosity.ci95_low": 0.0,
        "final.delta.verbosity.ci95_high": 0.5,
        "final.delta.churn_ratio.mean": 1.0,
        "final.delta.churn_ratio.ci95_low": 0.0,
        "final.delta.churn_ratio.ci95_high": 0.6,
    }
    key = RunGroupKey(
        model="m",
        prompt_path="p",
        thinking="t",
        agent_type="a",
        agent_version="v",
    )

    entries = _collect_ci_entries(record, key, min_width=0.5)

    assert [(entry.metric, entry.width) for entry in entries] == [
        ("Verbosity delta (final)", pytest.approx(0.5)),
        ("Churn ratio (final)", pytest.approx(0.6)),
    ]


def test_collect_ci_entries_filters_to_allowed_delta_metrics() -> None:
    record = {
        "problem": "prob",
        "run_count": 2,
        "unrelated.mean": 0.1,
        "unrelated.ci95_low": 0.0,
        "unrelated.ci95_high": 1.0,
    }
    key = RunGroupKey(
        model="m",
        prompt_path="p",
        thinking="t",
        agent_type="a",
        agent_version="v",
    )

    entries = _collect_ci_entries(record, key, min_width=0.0)

    assert entries == []


def test_collect_ci_entries_canonicalizes_metric_names() -> None:
    record = {
        "problem": "prob",
        "run_count": 2,
        "final.delta.verbosity.ci95_low": 0.4,
        "final.delta.verbosity.ci95_high": 0.6,
        "delta.verbosity.final.ci95_low": 0.5,
        "delta.verbosity.final.ci95_high": 0.7,
    }
    key = RunGroupKey(
        model="m",
        prompt_path="p",
        thinking="t",
        agent_type="a",
        agent_version="v",
    )

    entries = _collect_ci_entries(record, key, min_width=0.0)

    assert len(entries) == 1


def test_collect_ci_entries_allows_checkpoint_deltas() -> None:
    record = {
        "problem": "prob",
        "run_count": 2,
        "delta.loc.ci95_low": 0.4,
        "delta.loc.ci95_high": 0.6,
    }
    key = RunGroupKey(
        model="m",
        prompt_path="p",
        thinking="t",
        agent_type="a",
        agent_version="v",
    )

    entries = _collect_ci_entries(
        record,
        key,
        min_width=0.0,
        allowed_metrics={"delta.loc"},
    )

    assert len(entries) == 1
    assert entries[0].metric == "LOC delta"


def test_render_confidence_interval_table_outputs_ci_block() -> None:
    console = Console(record=True, width=120)
    entries = [
        ConfidenceIntervalEntry(
            problem="prob",
            metric="metric",
            mean=1.0,
            ci95_low=0.4,
            ci95_high=1.6,
            width=1.2,
            runs=3,
            group=RunGroupKey(
                model="m",
                prompt_path="p",
                thinking="t",
                agent_type="a",
                agent_version="v",
            ),
        )
    ]

    _render_confidence_interval_table(
        console=console, entries=entries, min_width=0.1, top_n=5
    )

    output = console.export_text()
    assert "Confidence intervals (95%) averaged across problems" in output
    assert "[0.40, 1.60]" in output
    assert "Width (avg)" in output
    assert "Problems" in output


def test_render_confidence_interval_table_aggregates_multiple_problems() -> (
    None
):
    console = Console(record=True, width=120)
    entries = [
        ConfidenceIntervalEntry(
            problem="prob1",
            metric="metric",
            mean=1.0,
            ci95_low=0.0,
            ci95_high=1.0,
            width=1.0,
            runs=2,
            group=RunGroupKey(
                model="m",
                prompt_path="p",
                thinking="t",
                agent_type="a",
                agent_version="v",
            ),
        ),
        ConfidenceIntervalEntry(
            problem="prob2",
            metric="metric",
            mean=3.0,
            ci95_low=2.0,
            ci95_high=4.0,
            width=2.0,
            runs=4,
            group=RunGroupKey(
                model="m",
                prompt_path="p",
                thinking="t",
                agent_type="a",
                agent_version="v",
            ),
        ),
    ]

    _render_confidence_interval_table(
        console=console, entries=entries, min_width=0.1, top_n=5
    )

    output = console.export_text()
    assert "metric" in output
    # Mean should be averaged: (1 + 3) / 2 = 2
    assert "2.00" in output
    # Width averaged: (1 + 2) / 2 = 1.50
    assert "1.50" in output


def test_render_confidence_interval_table_no_threshold_filtering() -> None:
    console = Console(record=True, width=120)
    entries = [
        ConfidenceIntervalEntry(
            problem="prob",
            metric="metric",
            mean=1.0,
            ci95_low=0.9,
            ci95_high=1.1,
            width=0.2,
            runs=3,
            group=RunGroupKey(
                model="m",
                prompt_path="p",
                thinking="t",
                agent_type="a",
                agent_version="v",
            ),
        )
    ]

    _render_confidence_interval_table(
        console=console, entries=entries, min_width=0.1, top_n=5
    )

    output = console.export_text()
    assert "metric" in output
