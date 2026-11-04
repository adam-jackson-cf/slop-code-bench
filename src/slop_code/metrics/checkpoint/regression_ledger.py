"""Exact prior/current matching of canonical regression test outcomes.

Stable test identity is ``(origin checkpoint, test id)``: the ``checkpoint`` and
``id`` fields recorded in ``evaluation.json`` (``checkpoint_1-Core`` keys become
``checkpoint_1-Regression`` at later checkpoints with the same test ids).
"""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path
from typing import Any, Literal

from slop_code.evaluation.report import CorrectnessResults
from slop_code.evaluation.report import GroupType
from slop_code.logging import get_logger

logger = get_logger(__name__)

Outcome = Literal["passed", "failed"]
TestIdentity = tuple[str, str]

LEDGER_FIELDS = (
    "regression_retained",
    "regression_broken",
    "regression_repaired",
    "regression_still_failing",
)


def outcome_class(status: str) -> Outcome | None:
    """Classify a test status; skipped/unknown tests are not classified."""
    if status == "passed":
        return "passed"
    if status in ("failed", "error"):
        return "failed"
    return None


def identity_of(test: Any) -> TestIdentity:
    return (str(test.checkpoint), str(test.id))


def outcome_index(tests: Iterable[Any]) -> dict[TestIdentity, Outcome | None]:
    """Index every test of an evaluation by stable identity."""
    return {identity_of(test): outcome_class(test.status) for test in tests}


def load_results(checkpoint_dir: Path | None) -> CorrectnessResults | None:
    """Load a produced canonical evaluation; absent/errored evaluations are None."""
    if checkpoint_dir is None:
        return None
    try:
        results = CorrectnessResults.from_dir(checkpoint_dir)
    except (OSError, ValueError):
        return None
    if not results.tests or results.pytest_exit_code not in (0, 1):
        return None
    return results


def regression_ledger(
    prior: CorrectnessResults | None, current: CorrectnessResults | None
) -> dict[str, int | None]:
    """Count retained/broken/repaired/still-failing Regression-group tests.

    Fields are all ``None`` when either evaluation is unavailable. Regression
    tests absent from the prior evaluation (or skipped on either side) are
    counted nowhere and logged.
    """
    if prior is None or current is None:
        return dict.fromkeys(LEDGER_FIELDS)
    prior_outcomes = outcome_index(prior.tests)
    retained = broken = repaired = still = 0
    for test in current.tests:
        if test.group_type != GroupType.REGRESSION:
            continue
        now = outcome_class(test.status)
        before = prior_outcomes.get(identity_of(test))
        if now is None or before is None:
            logger.warning(
                "Regression test not classifiable against prior checkpoint",
                checkpoint=test.checkpoint,
                test_id=test.id,
                in_prior=identity_of(test) in prior_outcomes,
                status=test.status,
            )
            continue
        if before == "passed":
            if now == "passed":
                retained += 1
            else:
                broken += 1
        elif now == "passed":
            repaired += 1
        else:
            still += 1
    return {
        "regression_retained": retained,
        "regression_broken": broken,
        "regression_repaired": repaired,
        "regression_still_failing": still,
    }
