"""Pure regression-breadth attribution from locked evaluator evidence."""

from __future__ import annotations

from decimal import Decimal

from .models import Eligibility
from .models import RegressionAttribution
from .models import RegressionBreadthInput
from .models import RegressionOutcome
from .models import RegressionPhase
from .models import RegressionRunEvidence
from .models import RegressionSymbolAttribution
from .models import SymbolIdentity
from .models import canonical_decimal


def _outcome_ledger(
    run: RegressionRunEvidence,
) -> tuple[tuple[str, str, str], ...]:
    return tuple(
        (item.node_id, item.phase.value, item.outcome.value)
        for item in run.outcomes
    )


def _ledger(run: RegressionRunEvidence) -> tuple[tuple[str, str, str], ...]:
    return tuple(
        (item.node_id, item.phase.value, item.outcome.value)
        for item in run.ledger
    )


def _process_ledger(
    run: RegressionRunEvidence,
) -> tuple[tuple[str, str, str], ...]:
    return tuple(
        (item.node_id, item.phase.value, item.event)
        for item in run.process_events
    )


def _ineligible_attribution(
    evidence: RegressionBreadthInput,
) -> RegressionAttribution:
    return RegressionAttribution(
        input=evidence,
        attributions=(),
        eligibility=Eligibility(
            eligible=False, reasons=("coverage_parity_unavailable",)
        ),
        regression=None,
    )


def _coverage_nodes(run: RegressionRunEvidence) -> frozenset[str]:
    return frozenset(item.node_id for item in run.coverage)


def _parity_available(evidence: RegressionBreadthInput) -> bool:
    """Require exact run identity and complete, internally consistent ledgers."""
    baseline = evidence.baseline
    produced = evidence.produced
    if (
        baseline.environment != produced.environment
        or baseline.corpus != produced.corpus
        or baseline.invocation != produced.invocation
    ):
        return False
    baseline_outcomes = _outcome_ledger(baseline)
    produced_outcomes = _outcome_ledger(produced)
    if (
        baseline_outcomes != _ledger(baseline)
        or produced_outcomes != _ledger(produced)
        or baseline_outcomes != produced_outcomes
        or _process_ledger(baseline) != _process_ledger(produced)
    ):
        return False
    outcome_nodes = frozenset(item.node_id for item in produced.outcomes)
    return _coverage_nodes(produced) <= outcome_nodes


def _innermost_symbol(
    symbols: tuple[SymbolIdentity, ...], path: str, line: int
) -> SymbolIdentity | None:
    candidates = tuple(
        symbol
        for symbol in symbols
        if symbol.path == path and symbol.start_line <= line <= symbol.end_line
    )
    if not candidates:
        return None
    return min(
        candidates,
        key=lambda symbol: (
            symbol.end_line - symbol.start_line,
            -symbol.start_line,
            symbol.qualified_name,
            symbol.kind,
        ),
    )


def calculate_regression_breadth(
    evidence: RegressionBreadthInput,
) -> RegressionAttribution:
    """Calculate G from failing canonical regressions and changed symbols only.

    Exact parity is required. Process-created failing regressions are attributable
    only when the locked measurement includes coverage for their canonical nodes.
    """
    if not _parity_available(evidence):
        return _ineligible_attribution(evidence)
    failed_nodes = frozenset(
        item.node_id
        for item in evidence.produced.outcomes
        if item.group_type == "Regression"
        and item.outcome in (RegressionOutcome.FAILED, RegressionOutcome.ERROR)
    )
    coverage_nodes = _coverage_nodes(evidence.produced)
    if any(
        event.phase is RegressionPhase.COLLECTION
        or (
            event.node_id in failed_nodes
            and event.node_id not in coverage_nodes
        )
        for event in evidence.produced.process_events
    ):
        return _ineligible_attribution(evidence)
    attributions = tuple(
        RegressionSymbolAttribution(
            node_id=context.node_id,
            path=context.path,
            line=line,
            symbol=symbol,
        )
        for context in evidence.produced.coverage
        if context.node_id in failed_nodes
        for line in context.executed_lines
        if (
            symbol := _innermost_symbol(
                evidence.changed_symbols, context.path, line
            )
        )
        is not None
    )
    unique_attributions = tuple(
        sorted(
            {
                (
                    item.node_id,
                    item.path,
                    item.line,
                    item.symbol.stable_identity,
                ): item
                for item in attributions
            }.values(),
            key=lambda item: (
                item.node_id.encode("utf-8"),
                item.path.encode("utf-8"),
                item.line,
                item.symbol.stable_identity,
            ),
        )
    )
    changed = {symbol.stable_identity for symbol in evidence.changed_symbols}
    affected = {item.symbol.stable_identity for item in unique_attributions}
    regression = (
        Decimal("1")
        if not changed
        else Decimal("1") - (Decimal(len(affected)) / Decimal(len(changed)))
    )
    return RegressionAttribution(
        input=evidence,
        attributions=unique_attributions,
        eligibility=Eligibility(eligible=True),
        regression=canonical_decimal(regression),
    )
