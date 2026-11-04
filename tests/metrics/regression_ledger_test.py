"""Regression transition ledger and prior-outcome identity matching."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from slop_code.metrics.checkpoint.regression_ledger import load_results
from slop_code.metrics.checkpoint.regression_ledger import regression_ledger
from slop_code.metrics.scoring.live_regression import _prior_regression_outcomes
from slop_code.metrics.scoring.models import RegressionOutcome


def _write_eval(
    root: Path, tests: dict[str, dict[str, list[str]]], exit_code: int = 1
) -> Path:
    counts = {"passed": {}, "total": {}}
    for key, buckets in tests.items():
        group = key.rpartition("-")[2]
        counts["passed"][group] = counts["passed"].get(group, 0) + len(
            buckets.get("passed", [])
        )
        counts["total"][group] = counts["total"].get(group, 0) + len(
            buckets.get("passed", []) + buckets.get("failed", [])
        )
    root.mkdir(parents=True)
    (root / "evaluation.json").write_text(
        json.dumps(
            {
                "problem_name": "p",
                "problem_version": 1,
                "checkpoint_name": root.name,
                "checkpoint_version": 1,
                "duration": 1.0,
                "entrypoint": "python main.py",
                "tests": {
                    key: {"passed": [], "failed": [], "skipped": [], **buckets}
                    for key, buckets in tests.items()
                },
                "pass_counts": counts["passed"],
                "total_counts": counts["total"],
                "pytest_exit_code": exit_code,
                "pytest_collected": sum(counts["total"].values()),
            }
        )
    )
    return root


def test_ledger_classifies_all_four_transitions_by_origin_and_name(
    tmp_path: Path,
):
    prior = _write_eval(
        tmp_path / "checkpoint_2",
        {
            "checkpoint_1-Regression": {
                "passed": ["retained", "broken"],
                "failed": ["repaired", "still"],
            },
            "checkpoint_2-Core": {"passed": ["new_core"]},
        },
    )
    current = _write_eval(
        tmp_path / "checkpoint_3",
        {
            "checkpoint_1-Regression": {
                "passed": ["retained", "repaired"],
                "failed": ["broken", "still"],
            },
            "checkpoint_2-Regression": {"passed": ["new_core"]},
            "checkpoint_3-Core": {"failed": ["unrelated"]},
        },
    )

    assert regression_ledger(load_results(prior), load_results(current)) == {
        "regression_retained": 2,
        "regression_broken": 1,
        "regression_repaired": 1,
        "regression_still_failing": 1,
    }


def test_same_test_name_from_different_origin_checkpoint_is_distinct(
    tmp_path: Path,
):
    prior = _write_eval(
        tmp_path / "checkpoint_2",
        {"checkpoint_1-Regression": {"passed": ["same"]}},
    )
    current = _write_eval(
        tmp_path / "checkpoint_3",
        {
            "checkpoint_1-Regression": {"passed": ["same"]},
            "checkpoint_2-Regression": {"failed": ["same"]},
        },
    )

    ledger = regression_ledger(load_results(prior), load_results(current))

    assert ledger["regression_retained"] == 1
    assert ledger["regression_broken"] == 0
    assert ledger["regression_still_failing"] == 0


def test_ledger_is_null_without_usable_prior_evaluation(tmp_path: Path):
    current = _write_eval(
        tmp_path / "checkpoint_2",
        {"checkpoint_1-Regression": {"passed": ["a"]}},
    )
    errored = _write_eval(
        tmp_path / "checkpoint_1_errored",
        {"checkpoint_1-Core": {"passed": ["a"]}},
        exit_code=2,
    )

    expected = dict.fromkeys(
        (
            "regression_retained",
            "regression_broken",
            "regression_repaired",
            "regression_still_failing",
        )
    )
    assert regression_ledger(None, load_results(current)) == expected
    assert (
        regression_ledger(load_results(errored), load_results(current))
        == expected
    )
    assert load_results(tmp_path / "missing") is None


def _test(checkpoint: str, test_id: str, status: str, group: str, path: str):
    return SimpleNamespace(
        checkpoint=checkpoint,
        id=test_id,
        status=status,
        group_type=SimpleNamespace(value=group),
        file_path=path,
    )


def test_prior_outcomes_match_node_by_origin_checkpoint_and_test_id():
    from slop_code.evaluation import GroupType

    def regression(checkpoint: str, test_id: str, status: str):
        test = _test(
            checkpoint,
            test_id,
            status,
            "Regression",
            f".evaluation_tests/test_{checkpoint}.py",
        )
        test.group_type = GroupType.REGRESSION
        return test

    nodes = {
        ".evaluation_tests/test_checkpoint_1.py::a",
        ".evaluation_tests/test_checkpoint_2.py::a",
        ".evaluation_tests/test_checkpoint_2.py::new",
    }
    current = [
        regression("checkpoint_1", "a", "failed"),
        regression("checkpoint_2", "a", "failed"),
        regression("checkpoint_2", "new", "failed"),
    ]
    prior = [
        _test("checkpoint_1", "a", "passed", "Regression", ""),
        _test("checkpoint_2", "a", "failed", "Core", ""),
    ]

    outcomes = _prior_regression_outcomes(current, prior, nodes)

    assert {item.node_id: item.outcome for item in outcomes} == {
        ".evaluation_tests/test_checkpoint_1.py::a": RegressionOutcome.PASSED,
        ".evaluation_tests/test_checkpoint_2.py::a": RegressionOutcome.FAILED,
    }
