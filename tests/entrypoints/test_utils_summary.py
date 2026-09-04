from __future__ import annotations

import json
from decimal import Decimal
from types import SimpleNamespace

import pytest
from rich.console import Console

from slop_code.common import SUMMARY_FILENAME
from slop_code.entrypoints.utils import EXPERIMENT_SUMMARY_FILENAME
from slop_code.entrypoints.utils import display_and_save_summary


def _patch_verified_generation(
    monkeypatch,
    tmp_path,
    benchmark,
    additions=(),
) -> None:
    analysis_dir = tmp_path / "measurement_analysis"
    analysis_dir.mkdir()
    (analysis_dir / "current.json").write_text(
        json.dumps({"generation_id": "a" * 64})
    )
    eligibility = SimpleNamespace(
        eligible=True,
        reasons=(),
        model_dump=lambda **_kwargs: {"eligible": True, "reasons": []},
    )
    manifest = SimpleNamespace(
        benchmark=benchmark,
        eligibility=eligibility,
        formula_id="f" * 64,
        report_additions=additions,
    )
    evidence = {
        "problems/prob1/checkpoints/checkpoint_1/production_quality.json": (
            json.dumps(
                {
                    "interpreter": {
                        "implementation": "cpython",
                        "version": "3.12.14",
                        "cache_tag": "cpython-312",
                        "executable": "/private/evaluator/bin/python",
                        "executable_sha256": "e" * 64,
                    }
                }
            ).encode()
        )
    }
    monkeypatch.setattr(
        "slop_code.entrypoints.utils.load_verified_current_generation_state",
        lambda _run_dir: (manifest, evidence),
    )


def _config() -> dict:
    return {
        "model": {"name": "test-model"},
        "thinking": "none",
        "prompt_path": "test_prompt.jinja",
        "agent": {"type": "test-agent", "version": "v1"},
        "assessment_policy": "any-case",
    }


def test_display_and_save_summary_uses_new_composite_formulas(tmp_path):
    results_file = tmp_path / "checkpoint_results.jsonl"
    rows = [
        {
            "problem": "prob1",
            "idx": 1,
            "strict_pass_rate": 1.0,
            "isolated_pass_rate": 1.0,
            "verbosity": 0.6,
            "erosion": 0.6,
        },
        {
            "problem": "prob1",
            "idx": 2,
            "strict_pass_rate": 1.0,
            "isolated_pass_rate": 1.0,
            "verbosity": 0.3,
            "erosion": 0.4,
        },
    ]
    results_file.write_text("\n".join(json.dumps(row) for row in rows) + "\n")
    console = Console(record=True)

    summary = display_and_save_summary(
        results_file, tmp_path, _config(), console, expected_checkpoints=2
    )

    assert summary is not None
    assert summary.verbosity.mean == pytest.approx(0.45)
    assert summary.erosion.mean == pytest.approx(0.5)
    assert summary.erosion.count == 2
    saved = json.loads((tmp_path / SUMMARY_FILENAME).read_text())
    assert saved["verbosity"]["mean"] == summary.verbosity.mean
    assert saved["erosion"]["mean"] == summary.erosion.mean
    assert saved["completion"]["strict_score"] is None
    rendered = console.export_text()
    assert "Completion Summary" in rendered
    assert "Scoring Quality" not in rendered
    persisted = (tmp_path / EXPERIMENT_SUMMARY_FILENAME).read_text()
    assert "Completion Summary" in persisted
    assert "Scoring Quality" not in persisted


def test_display_and_save_summary_projects_verified_score(
    tmp_path, monkeypatch
):
    results_file = tmp_path / "checkpoint_results.jsonl"
    results_file.write_text(
        json.dumps(
            {
                "problem": "prob1",
                "checkpoint": "checkpoint_1",
                "idx": 1,
                "strict_pass_rate": 1.0,
                "isolated_pass_rate": 1.0,
                "passed_tests": 23,
                "total_tests": 29,
                "cost": 0.00911456,
                "duration": 164.246467,
                "steps": 15,
            }
        )
        + "\n"
    )
    components = SimpleNamespace(
        verbosity=Decimal("0.1"),
        erosion=Decimal("0.2"),
        architecture=Decimal("0.3"),
        rework=Decimal("0.4"),
        regression=Decimal("0.5"),
    )
    benchmark = SimpleNamespace(
        benchmark_score=Decimal("88.500000"),
        correctness=Decimal("0.9"),
        inertia=Decimal("0.8"),
        cost_per_configured_checkpoint=Decimal("1.2"),
        problems=(
            SimpleNamespace(
                problem_id="prob1",
                score=Decimal("88.5"),
                components=components,
            ),
        ),
    )
    _patch_verified_generation(monkeypatch, tmp_path, benchmark)

    console = Console(record=True)
    display_and_save_summary(
        results_file,
        tmp_path,
        _config(),
        console,
        expected_checkpoints=8,
    )

    saved = json.loads((tmp_path / SUMMARY_FILENAME).read_text())
    assert saved["benchmark_score"] == "88.500000"
    assert saved["completion"] == {
        "model": "test-model",
        "assessment_policy": "any-case",
        "checkpoints_produced": 1,
        "checkpoints_configured": 8,
        "tests_passed": 23,
        "tests_total": 29,
        "strict_score": "88.500000",
        "total_cost": 0.00911456,
        "duration_seconds": 164.246467,
        "steps": 15,
    }
    assert saved["scoring"]["correctness"] == "0.9"
    assert saved["scoring"]["problems"]["prob1"] == {
        "score": "88.5",
        "production_concision": "0.1",
        "structural_quality": "0.2",
        "acyclic_architecture": "0.3",
        "rework_stability": "0.4",
        "regression_resistance": "0.5",
    }
    assert saved["scoring"]["evaluator_identity"] == {
        "implementation": "cpython",
        "cache_tag": "cpython-312",
        "executable_sha256": "e" * 64,
    }
    assert "/private/evaluator/bin/python" not in json.dumps(saved)
    rendered = console.export_text()
    assert "Completion Summary" in rendered
    assert "Scoring Quality" in rendered
    assert "Key Takeaways" in rendered
    persisted = (tmp_path / EXPERIMENT_SUMMARY_FILENAME).read_text()
    assert "Correctness" in persisted
    assert "Inertia" in persisted
    assert "Production concision" in persisted
    assert "Structural quality" in persisted
    assert "Acyclic architecture" in persisted
    assert "Rework stability" in persisted
    assert "Regression resistance" in persisted
    assert "cpython cpython-312" in persisted
    assert "e" * 64 in persisted
    assert "/private/evaluator/bin/python" not in persisted


def test_verified_checkpoint_additions_merge_by_exact_checkpoint_identity(
    tmp_path, monkeypatch
):
    results_file = tmp_path / "checkpoint_results.jsonl"
    checkpoint_row = {
        "problem": "prob1",
        "checkpoint": "checkpoint_twenty",
        "idx": 20,
        "strict_pass_rate": 1.0,
        "isolated_pass_rate": 1.0,
    }
    original = json.dumps(checkpoint_row) + "\n"
    results_file.write_text(original)
    addition = SimpleNamespace(
        problem_name="prob1",
        checkpoint_id="checkpoint_twenty",
        model_dump=lambda **_kwargs: {
            "problem_name": "prob1",
            "checkpoint_id": "checkpoint_twenty",
            "problem_score": "42.000000",
        },
    )
    unmatched_addition = SimpleNamespace(
        problem_name="prob1",
        checkpoint_id="checkpoint_twenty_one",
        model_dump=lambda **_kwargs: {
            "problem_name": "prob1",
            "checkpoint_id": "checkpoint_twenty_one",
            "problem_score": "99.000000",
        },
    )
    benchmark = SimpleNamespace(
        benchmark_score=Decimal("42"),
        correctness=Decimal("1"),
        inertia=Decimal("0.2"),
        cost_per_configured_checkpoint=None,
        problems=(),
    )
    _patch_verified_generation(
        monkeypatch,
        tmp_path,
        benchmark,
        (addition, unmatched_addition),
    )

    display_and_save_summary(
        results_file,
        tmp_path,
        _config(),
        Console(),
        expected_checkpoints=1,
    )

    assert results_file.read_text() == original
    saved = json.loads((tmp_path / SUMMARY_FILENAME).read_text())
    assert saved["scoring"]["report_additions"] == [
        {
            "problem_name": "prob1",
            "checkpoint_id": "checkpoint_twenty",
            "problem_score": "42.000000",
        }
    ]


def test_display_and_save_summary_omits_tampered_score(tmp_path, monkeypatch):
    from slop_code.metrics.scoring import ScoreEvidenceError

    results_file = tmp_path / "checkpoint_results.jsonl"
    results_file.write_text(
        json.dumps(
            {
                "problem": "prob1",
                "idx": 1,
                "strict_pass_rate": 1.0,
                "isolated_pass_rate": 1.0,
            }
        )
        + "\n"
    )
    monkeypatch.setattr(
        "slop_code.entrypoints.utils.load_verified_current_generation_state",
        lambda _run_dir: (_ for _ in ()).throw(
            ScoreEvidenceError({"tampered"})
        ),
    )

    display_and_save_summary(
        results_file,
        tmp_path,
        _config(),
        Console(),
        expected_checkpoints=1,
    )

    saved = json.loads((tmp_path / SUMMARY_FILENAME).read_text())
    assert "benchmark_score" not in saved
    assert "scoring" not in saved
    assert saved["completion"]["strict_score"] is None
    assert saved["pct_checkpoints_solved"] == 100.0
    persisted = (tmp_path / EXPERIMENT_SUMMARY_FILENAME).read_text()
    assert "Completion Summary" in persisted
    assert "Scoring Quality" not in persisted
