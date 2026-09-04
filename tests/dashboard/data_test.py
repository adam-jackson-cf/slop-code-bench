from __future__ import annotations

from decimal import Decimal
from pathlib import Path
from typing import TYPE_CHECKING

import pandas as pd

if TYPE_CHECKING:
    import pytest


from slop_code.dashboard.data import ChartContext
from slop_code.dashboard.data import build_chart_context
from slop_code.dashboard.data import compute_problem_deltas
from slop_code.dashboard.data import get_summary_table_data
from slop_code.dashboard.data import load_run
from slop_code.dashboard.data import process_checkpoint_row
from slop_code.metrics.scoring import ScoreEvidenceError


def test_process_checkpoint_row_uses_new_pass_rate_names() -> None:
    processed = process_checkpoint_row(
        {
            "strict_pass_rate": 1.0,
            "isolated_pass_rate": 0.0,
            "total_tests": 10,
            "passed_tests": 5,
        }
    )

    assert processed["passed_chkpt"] is True


def test_problem_deltas_need_no_scb_metrics() -> None:
    deltas = compute_problem_deltas(
        pd.DataFrame(
            [
                {
                    "display_name": "Run A",
                    "problem": "prob1",
                    "idx": 1,
                    "loc": 10,
                    "lint_errors": 2,
                    "cc_high_count": 1,
                    "cc_max": 3,
                },
                {
                    "display_name": "Run A",
                    "problem": "prob1",
                    "idx": 2,
                    "loc": 20,
                    "lint_errors": 1,
                    "cc_high_count": 2,
                    "cc_max": 4,
                },
            ]
        )
    )

    assert deltas["lines_delta_pct"].item() == 100
    assert "verbosity_delta_pct" not in deltas


def test_summary_table_uses_exact_canonical_ranking_key_order():
    rows = [
        {
            "run_path": "null-cost",
            "model_name": "Null",
            "thinking": "none",
            "agent_type": "agent",
            "agent_version": "",
            "prompt_template": "prompt",
            "benchmark_score": Decimal("90"),
            "scoring.ranking_key": (
                Decimal("-90"),
                Decimal("-1"),
                Decimal("-1"),
                True,
                Decimal("0"),
                "null-cost",
            ),
        },
        {
            "run_path": "costly",
            "model_name": "Costly",
            "thinking": "none",
            "agent_type": "agent",
            "agent_version": "",
            "prompt_template": "prompt",
            "benchmark_score": Decimal("90"),
            "scoring.ranking_key": (
                Decimal("-90"),
                Decimal("-1"),
                Decimal("-1"),
                False,
                Decimal("2"),
                "costly",
            ),
        },
        {
            "run_path": "cheap",
            "model_name": "Cheap",
            "thinking": "none",
            "agent_type": "agent",
            "agent_version": "",
            "prompt_template": "prompt",
            "benchmark_score": Decimal("90"),
            "scoring.ranking_key": (
                Decimal("-90"),
                Decimal("-1"),
                Decimal("-1"),
                False,
                Decimal("1"),
                "cheap",
            ),
        },
    ]

    table = get_summary_table_data(
        ChartContext(pd.DataFrame(), pd.DataFrame(rows), {}, {})
    )

    assert [row["Model"] for row in table] == [
        "Cheap (Agent, Prompt)",
        "Costly (Agent, Prompt)",
        "Null (Agent, Prompt)",
    ]
    assert [row["Benchmark Score"] for row in table] == [90.0, 90.0, 90.0]


def test_load_run_rejects_tampered_canonical_generation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    (tmp_path / "checkpoint_results.jsonl").write_text("{}\n")
    monkeypatch.setattr(
        "slop_code.dashboard.data.load_config_metadata",
        lambda _: {"model_name": "Model"},
    )
    monkeypatch.setattr(
        "slop_code.dashboard.data.load_verified_score_summary",
        lambda _: (_ for _ in ()).throw(ScoreEvidenceError({"tampered"})),
    )

    checkpoints, summary = load_run(tmp_path)

    assert checkpoints.empty
    assert summary is None


def test_load_run_rejects_malformed_checkpoint_artifacts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "slop_code.dashboard.data.load_config_metadata",
        lambda _: {"model_name": "Model"},
    )
    results_path = tmp_path / "checkpoint_results.jsonl"

    for payload in (b"not-json\n", b"\x80\x81"):
        results_path.write_bytes(payload)

        checkpoints, summary = load_run(tmp_path)

        assert checkpoints.empty
        assert summary is None


def test_common_problems_table_keeps_canonical_score_without_summary(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "checkpoint_results.jsonl").write_text(
        '{"problem": "shared", "idx": 1, "total_tests": 1, '
        '"passed_tests": 1, "strict_pass_rate": 1.0, '
        '"isolated_pass_rate": 1.0}\n'
    )
    monkeypatch.setattr(
        "slop_code.dashboard.data.load_config_metadata",
        lambda _: {
            "agent_type": "agent",
            "agent_version": "",
            "model_name": "Model",
            "thinking": "none",
            "prompt_template": "prompt",
            "run_date": "",
            "run_timestamp": "",
            "num_problems": 1,
        },
    )
    monkeypatch.setattr(
        "slop_code.dashboard.data.load_verified_score_summary",
        lambda _: {
            "benchmark_score": Decimal("83.125"),
            "ranking_key": (Decimal("-83.125"), "run"),
        },
    )

    context = build_chart_context([tmp_path], common_problems_only=True)

    assert get_summary_table_data(context) == [
        {
            "Model": "Model (Agent, Prompt)",
            "Benchmark Score": 83.125,
            "Solved (%)": 100.0,
            "Partial (%)": 100.0,
            "Wins": 0,
            "Tokens": 0,
            "Cost ($)": 0,
            "Time (min)": 0,
        }
    ]
