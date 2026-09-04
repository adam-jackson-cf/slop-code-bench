"""Pure deterministic repeated-rework lineage scoring."""

from __future__ import annotations

import hashlib
from collections import defaultdict
from collections.abc import Mapping
from collections.abc import Sequence
from decimal import Decimal

from .models import LedgerTransitionEvidence
from .models import LineageCandidate
from .models import LineageComponentEvidence
from .models import LineageLedgerEntry
from .models import OwnedLineEvidence
from .models import PhysicalLineEvidence
from .models import ProblemReworkEvidence
from .models import ReworkCheckpointInput
from .models import SymbolDegreeEvidence
from .models import SymbolIdentity
from .models import TransitionReworkEvidence

Ledger = Mapping[object, bool]


def _endpoint_key(
    symbol: SymbolIdentity,
) -> tuple[str, str, str, str, str, int, int]:
    return symbol.stable_identity


def _ordered_symbols(
    symbols: Sequence[SymbolIdentity],
) -> tuple[SymbolIdentity, ...]:
    return tuple(sorted(symbols, key=_endpoint_key))


def _equal(left: str, right: str) -> bool:
    return bool(left) and left == right


def _candidate(
    prior: SymbolIdentity,
    current: SymbolIdentity,
    *,
    accepted: bool = False,
    match: str = "none",
    ambiguous_set_id: str | None = None,
) -> LineageCandidate:
    return LineageCandidate(
        prior=prior,
        current=current,
        body_hash_equal=_equal(prior.body_sha256, current.body_sha256),
        structure_hash_equal=_equal(
            prior.structure_sha256, current.structure_sha256
        ),
        signature_hash_equal=_equal(
            prior.signature_sha256, current.signature_sha256
        ),
        accepted=accepted,
        match=match,  # type: ignore[arg-type]
        ambiguous_set_id=ambiguous_set_id,
    )


def _component_id(
    priors: Sequence[SymbolIdentity],
    currents: Sequence[SymbolIdentity],
    edges: Sequence[LineageCandidate],
) -> str:
    """Hash sorted endpoint identities and every frozen candidate equality flag."""
    payload = repr(
        (
            tuple(_endpoint_key(symbol) for symbol in _ordered_symbols(priors)),
            tuple(
                _endpoint_key(symbol) for symbol in _ordered_symbols(currents)
            ),
            tuple(
                (
                    _endpoint_key(edge.prior),
                    _endpoint_key(edge.current),
                    edge.body_hash_equal,
                    edge.structure_hash_equal,
                    edge.signature_hash_equal,
                )
                for edge in sorted(
                    edges,
                    key=lambda edge: (
                        _endpoint_key(edge.prior),
                        _endpoint_key(edge.current),
                    ),
                )
            ),
        )
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _ledger_value(ledger: Ledger, symbol: SymbolIdentity) -> bool:
    return bool(ledger.get(symbol, ledger.get(_endpoint_key(symbol), False)))


def _innermost(
    symbols: Sequence[SymbolIdentity], path: str, line: int
) -> SymbolIdentity | None:
    candidates = [
        symbol
        for symbol in symbols
        if symbol.path == path and symbol.start_line <= line <= symbol.end_line
    ]
    return min(
        candidates,
        key=lambda symbol: (
            symbol.end_line - symbol.start_line,
            _endpoint_key(symbol),
        ),
        default=None,
    )


def calculate_transition_rework(
    prior_symbols: Sequence[SymbolIdentity],
    current_symbols: Sequence[SymbolIdentity],
    removed_lines: Sequence[PhysicalLineEvidence],
    added_lines: Sequence[PhysicalLineEvidence],
    prior_ledger: Ledger,
) -> TransitionReworkEvidence:
    """Score one transition using only frozen exact/hash lineage evidence.

    ``removed_lines`` must contain only ``side='removed'`` entries and
    ``added_lines`` only ``side='added'`` entries.  Every supplied line is
    mapped once before candidate ownership is considered.
    """
    if any(line.side != "removed" for line in removed_lines) or any(
        line.side != "added" for line in added_lines
    ):
        raise ValueError("diff line side must match its transition input")
    priors = _ordered_symbols(prior_symbols)
    currents = _ordered_symbols(current_symbols)
    prior_by_exact: dict[
        tuple[str, str, str, str, str], list[SymbolIdentity]
    ] = defaultdict(list)
    current_by_exact: dict[
        tuple[str, str, str, str, str], list[SymbolIdentity]
    ] = defaultdict(list)
    for symbol in priors:
        prior_by_exact[symbol.exact_identity].append(symbol)
    for symbol in currents:
        current_by_exact[symbol.exact_identity].append(symbol)

    accepted: list[LineageCandidate] = []
    matched_priors: set[SymbolIdentity] = set()
    matched_currents: set[SymbolIdentity] = set()
    for identity in sorted(set(prior_by_exact) & set(current_by_exact)):
        left, right = prior_by_exact[identity], current_by_exact[identity]
        if len(left) == len(right) == 1:
            accepted.append(
                _candidate(left[0], right[0], accepted=True, match="exact")
            )
            matched_priors.add(left[0])
            matched_currents.add(right[0])

    remaining_priors = tuple(
        symbol for symbol in priors if symbol not in matched_priors
    )
    remaining_currents = tuple(
        symbol for symbol in currents if symbol not in matched_currents
    )
    raw_edges = [
        _candidate(prior, current)
        for prior in remaining_priors
        for current in remaining_currents
        if prior.language == current.language
        and prior.kind == current.kind
        and any(
            (
                _equal(prior.body_sha256, current.body_sha256),
                _equal(prior.structure_sha256, current.structure_sha256),
                _equal(prior.signature_sha256, current.signature_sha256),
            )
        )
    ]
    inbound: dict[SymbolIdentity, int] = defaultdict(int)
    outbound: dict[SymbolIdentity, int] = defaultdict(int)
    for edge in raw_edges:
        outbound[edge.prior] += 1
        inbound[edge.current] += 1

    # Partition the complete candidate graph, never a subset selected by a match.
    adjacency: dict[
        tuple[str, SymbolIdentity], set[tuple[str, SymbolIdentity]]
    ] = defaultdict(set)
    for edge in raw_edges:
        left, right = ("prior", edge.prior), ("current", edge.current)
        adjacency[left].add(right)
        adjacency[right].add(left)
    visited: set[tuple[str, SymbolIdentity]] = set()
    components: list[LineageComponentEvidence] = []
    candidates: list[LineageCandidate] = list(accepted)
    for seed in sorted(
        adjacency, key=lambda item: (item[0], _endpoint_key(item[1]))
    ):
        if seed in visited:
            continue
        stack, nodes = [seed], set()
        while stack:
            node = stack.pop()
            if node in visited:
                continue
            visited.add(node)
            nodes.add(node)
            stack.extend(adjacency[node] - visited)
        component_priors = _ordered_symbols(
            [symbol for side, symbol in nodes if side == "prior"]
        )
        component_currents = _ordered_symbols(
            [symbol for side, symbol in nodes if side == "current"]
        )
        component_edges = [
            edge
            for edge in raw_edges
            if edge.prior in component_priors
            and edge.current in component_currents
        ]
        component_id = _component_id(
            component_priors, component_currents, component_edges
        )
        hash_accepts = [
            edge
            for edge in component_edges
            if edge.body_hash_equal
            and edge.structure_hash_equal
            and outbound[edge.prior] == 1
            and inbound[edge.current] == 1
        ]
        ambiguous = not bool(hash_accepts)
        components.append(
            LineageComponentEvidence(
                component_id=component_id,
                priors=component_priors,
                currents=component_currents,
                ambiguous=ambiguous,
            )
        )
        for edge in component_edges:
            if edge in hash_accepts:
                candidates.append(
                    _candidate(
                        edge.prior, edge.current, accepted=True, match="hash"
                    )
                )
            else:
                candidates.append(
                    _candidate(
                        edge.prior,
                        edge.current,
                        ambiguous_set_id=component_id,
                    )
                )

    candidates.sort(
        key=lambda edge: (
            _endpoint_key(edge.prior),
            _endpoint_key(edge.current),
        )
    )
    degrees = tuple(
        SymbolDegreeEvidence(
            symbol=symbol, inbound=inbound[symbol], outbound=outbound[symbol]
        )
        for symbol in _ordered_symbols((*priors, *currents))
    )

    all_lines = (*removed_lines, *added_lines)
    mapped = tuple(
        PhysicalLineEvidence(
            path=line.path,
            line=line.line,
            side=line.side,
            owner=_innermost(
                priors if line.side == "removed" else currents,
                line.path,
                line.line,
            ),
        )
        for line in all_lines
    )
    accepted_pairs = {
        (edge.prior, edge.current) for edge in candidates if edge.accepted
    }
    ambiguous_ids = {
        edge.ambiguous_set_id for edge in candidates if edge.ambiguous_set_id
    }
    eligible_symbol_keys = {
        _endpoint_key(symbol) for pair in accepted_pairs for symbol in pair
    } | {
        _endpoint_key(symbol)
        for edge in candidates
        if edge.ambiguous_set_id in ambiguous_ids
        for symbol in (edge.prior, edge.current)
    }
    owned_map: dict[SymbolIdentity, set[int]] = defaultdict(set)
    changed_keys: set[tuple[str, str, int]] = set()
    by_symbol: dict[SymbolIdentity, set[tuple[str, str, int]]] = defaultdict(
        set
    )
    for line in mapped:
        if (
            line.owner is not None
            and _endpoint_key(line.owner) in eligible_symbol_keys
        ):
            key = (line.side, line.path, line.line)
            changed_keys.add(key)
            by_symbol[line.owner].add(key)
            owned_map[line.owner].add(line.line)
    owned = tuple(
        OwnedLineEvidence(symbol=symbol, lines=tuple(sorted(lines)))
        for symbol, lines in sorted(
            owned_map.items(), key=lambda item: _endpoint_key(item[0])
        )
    )

    repeated: set[tuple[str, str, int]] = set()
    ledger_transitions: list[LedgerTransitionEvidence] = []
    for edge in candidates:
        if edge.accepted:
            line_keys = by_symbol[edge.prior] | by_symbol[edge.current]
            before = _ledger_value(prior_ledger, edge.prior)
            if before:
                repeated.update(line_keys)
            ledger_transitions.append(
                LedgerTransitionEvidence(
                    prior=edge.prior,
                    current=edge.current,
                    input_modified_before=before,
                    mapped_changed=bool(line_keys),
                    output_modified_before=before or bool(line_keys),
                )
            )
    for component in components:
        component_edges = [
            edge
            for edge in candidates
            if edge.ambiguous_set_id == component.component_id
        ]
        if not component_edges:
            continue
        line_keys = set().union(
            *(
                by_symbol[edge.prior] | by_symbol[edge.current]
                for edge in component_edges
            )
        )
        before = any(
            _ledger_value(prior_ledger, edge.prior) for edge in component_edges
        )
        if before:
            repeated.update(line_keys)
        for current in component.currents:
            ledger_transitions.append(
                LedgerTransitionEvidence(
                    prior=component.priors[0],
                    current=current,
                    input_modified_before=before,
                    mapped_changed=bool(line_keys),
                    output_modified_before=before or bool(line_keys),
                )
            )

    ledger = tuple(
        LineageLedgerEntry(
            candidate=edge,
            disposition="accepted" if edge.accepted else "rejected",
            reason=(
                "exact identity"
                if edge.match == "exact"
                else "body and structure degree-one"
                if edge.match == "hash"
                else "ambiguous candidate set"
            ),
            prior_modified_before=_ledger_value(prior_ledger, edge.prior),
            current_modified_before=next(
                (
                    transition.output_modified_before
                    for transition in ledger_transitions
                    if transition.current == edge.current
                ),
                False,
            ),
        )
        for edge in candidates
    )
    denominator, numerator = len(changed_keys), len(repeated)
    return TransitionReworkEvidence(
        changed_physical_lines=mapped,
        lineage_candidates=tuple(candidates),
        symbol_degrees=degrees,
        lineage_components=tuple(components),
        owned_lines=owned,
        lineage_ledger=ledger,
        ledger_transitions=tuple(ledger_transitions),
        changed_lines=denominator,
        repeated_lines=numerator,
        rework=Decimal("1")
        if denominator == 0
        else Decimal("1") - Decimal(numerator) / Decimal(denominator),
    )


def calculate_problem_rework(
    checkpoints: Sequence[ReworkCheckpointInput],
) -> ProblemReworkEvidence:
    """Calculate every configured adjacent transition from complete evidence."""
    if len(checkpoints) < 2:
        raise ValueError("rework requires at least two configured checkpoints")
    checkpoint_ids = tuple(
        checkpoint.checkpoint_id for checkpoint in checkpoints
    )
    if len(set(checkpoint_ids)) != len(checkpoint_ids):
        raise ValueError("checkpoint identifiers must be unique")
    ledger: dict[object, bool] = {}
    transitions: list[TransitionReworkEvidence] = []
    prior = checkpoints[0]
    for current in checkpoints[1:]:
        if prior.symbols is None or current.symbols is None:
            raise ValueError("rework requires complete symbol evidence")
        transition = calculate_transition_rework(
            prior.symbols,
            current.symbols,
            current.removed_lines,
            current.added_lines,
            ledger,
        )
        transitions.append(transition)
        ledger = {
            item.current.stable_identity: item.output_modified_before
            for item in transition.ledger_transitions
        }
        prior = current
    final_ledger = tuple(
        LedgerTransitionEvidence(
            prior=item.prior,
            current=item.current,
            input_modified_before=item.output_modified_before,
            mapped_changed=False,
            output_modified_before=item.output_modified_before,
        )
        for item in transitions[-1].ledger_transitions
    )
    return ProblemReworkEvidence(
        checkpoint_ids=checkpoint_ids,
        transitions=tuple(transitions),
        final_ledger=final_ledger,
    )
