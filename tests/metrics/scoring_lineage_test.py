"""Hand-calculated contract scenarios for deterministic repeated-rework lineage."""

from __future__ import annotations

import hashlib
from decimal import Decimal
from typing import Literal

import pytest

from slop_code.metrics.scoring.lineage import calculate_problem_rework
from slop_code.metrics.scoring.lineage import calculate_transition_rework
from slop_code.metrics.scoring.models import PhysicalLineEvidence
from slop_code.metrics.scoring.models import ReworkCheckpointInput
from slop_code.metrics.scoring.models import SymbolIdentity


def _hash(label: str) -> str:
    return hashlib.sha256(label.encode()).hexdigest()


def _symbol(
    name: str,
    *,
    path: str = "src/mod.py",
    parent: str = "",
    kind: Literal["function", "method"] = "function",
    start: int = 10,
    end: int | None = None,
    language: str = "python",
    body: str = "",
    structure: str = "",
    signature: str = "",
) -> SymbolIdentity:
    return SymbolIdentity(
        path=path,
        qualified_name=name,
        parent_qualified_name=parent,
        kind=kind,
        start_line=start,
        end_line=end if end is not None else start + 2,
        language=language,
        body_sha256=_hash(body) if body else "",
        structure_sha256=_hash(structure) if structure else "",
        signature_sha256=_hash(signature) if signature else "",
    )


def _lines(
    side: Literal["added", "removed"], path: str, *numbers: int
) -> tuple[PhysicalLineEvidence, ...]:
    return tuple(
        PhysicalLineEvidence(path=path, line=line, side=side)
        for line in numbers
    )


def _edge_view(result):
    return [
        (
            edge.prior.qualified_name,
            edge.current.qualified_name,
            edge.body_hash_equal,
            edge.structure_hash_equal,
            edge.signature_hash_equal,
            edge.accepted,
            edge.match,
            edge.ambiguous_set_id,
        )
        for edge in result.lineage_candidates
    ]


@pytest.mark.parametrize(
    ("label", "prior", "current", "expected"),
    [
        ("no flags", _symbol("old"), _symbol("new"), []),
        (
            "body only",
            _symbol("old", body="same"),
            _symbol("new", body="same"),
            [(True, False, False, False)],
        ),
        (
            "structure only",
            _symbol("old", structure="same"),
            _symbol("new", structure="same"),
            [(False, True, False, False)],
        ),
        (
            "signature only",
            _symbol("old", signature="same"),
            _symbol("new", signature="same"),
            [(False, False, True, False)],
        ),
        (
            "body structure",
            _symbol("old", body="same", structure="tree"),
            _symbol("new", body="same", structure="tree"),
            [(True, True, False, True)],
        ),
        (
            "all flags",
            _symbol("old", body="same", structure="tree", signature="sig"),
            _symbol("new", body="same", structure="tree", signature="sig"),
            [(True, True, True, True)],
        ),
    ],
)
def test_hash_edge_flags_and_degree_one_acceptance(
    label, prior, current, expected
):
    result = calculate_transition_rework((prior,), (current,), (), (), {})

    assert [
        (edge[2], edge[3], edge[4], edge[5]) for edge in _edge_view(result)
    ] == expected, label
    assert [
        (degree.symbol.qualified_name, degree.inbound, degree.outbound)
        for degree in result.symbol_degrees
    ] == [("new", int(bool(expected)), 0), ("old", 0, int(bool(expected)))]
    assert result.lineage_components == (
        () if not expected else result.lineage_components
    )
    if expected:
        assert result.lineage_components[0].ambiguous is (not expected[0][3])


def test_exact_edit_rename_move_and_rename_plus_edit_no_edge():
    exact_prior = _symbol("f", start=1, end=3)
    exact_current = _symbol("f", start=4, end=6, body="edited")
    rename_prior = _symbol(
        "old", body="rename-body", structure="rename-tree", start=10
    )
    rename_current = _symbol(
        "new", body="rename-body", structure="rename-tree", start=20
    )
    move_prior = _symbol(
        "moved", path="src/old.py", body="move-body", structure="move-tree"
    )
    move_current = _symbol(
        "moved", path="src/new.py", body="move-body", structure="move-tree"
    )
    edited = _symbol("renamed", body="other", structure="other")
    result = calculate_transition_rework(
        (exact_prior, rename_prior, move_prior),
        (exact_current, rename_current, move_current, edited),
        _lines("removed", "src/mod.py", 1),
        _lines("added", "src/mod.py", 4),
        {exact_prior.stable_identity: True},
    )

    assert [
        (edge[0], edge[1], edge[5], edge[6]) for edge in _edge_view(result)
    ] == [
        ("f", "f", True, "exact"),
        ("moved", "moved", True, "hash"),
        ("old", "new", True, "hash"),
    ]
    assert result.changed_lines == 2
    assert result.repeated_lines == 2
    assert result.rework == Decimal("0")
    assert {
        entry.candidate.current.qualified_name: entry.current_modified_before
        for entry in result.lineage_ledger
    } == {"f": True, "moved": False, "new": False}


def test_split_and_merge_are_ambiguous_components_with_complete_edges_and_conservative_ledger():
    split_prior = _symbol(
        "split", body="copy", structure="tree", start=1, end=4
    )
    split_current_a = _symbol(
        "split_a", body="copy", structure="tree", start=20, end=23
    )
    split_current_b = _symbol(
        "split_b", body="copy", structure="tree", start=30, end=33
    )
    merge_prior_a = _symbol(
        "merge_a", body="copy", structure="tree", start=40, end=43
    )
    merge_prior_b = _symbol(
        "merge_b", body="copy", structure="tree", start=50, end=53
    )
    merge_current = _symbol(
        "merge", body="copy", structure="tree", start=60, end=63
    )
    split = calculate_transition_rework(
        (split_prior,),
        (split_current_a, split_current_b),
        _lines("removed", "src/mod.py", 2),
        _lines("added", "src/mod.py", 21, 31),
        {split_prior.stable_identity: True},
    )
    merge = calculate_transition_rework(
        (merge_prior_a, merge_prior_b),
        (merge_current,),
        _lines("removed", "src/mod.py", 41, 51),
        _lines("added", "src/mod.py", 61),
        {merge_prior_a.stable_identity: True},
    )

    for result, priors, currents, expected_edges, expected_degrees in (
        (
            split,
            (split_prior,),
            (split_current_a, split_current_b),
            [("split", "split_a"), ("split", "split_b")],
            [("split", 0, 2), ("split_a", 1, 0), ("split_b", 1, 0)],
        ),
        (
            merge,
            (merge_prior_a, merge_prior_b),
            (merge_current,),
            [("merge_a", "merge"), ("merge_b", "merge")],
            [("merge", 2, 0), ("merge_a", 0, 1), ("merge_b", 0, 1)],
        ),
    ):
        expected_component_id = hashlib.sha256(
            repr(
                (
                    tuple(
                        symbol.stable_identity
                        for symbol in sorted(
                            priors, key=lambda item: item.stable_identity
                        )
                    ),
                    tuple(
                        symbol.stable_identity
                        for symbol in sorted(
                            currents, key=lambda item: item.stable_identity
                        )
                    ),
                    tuple(
                        (
                            prior.stable_identity,
                            current.stable_identity,
                            True,
                            True,
                            False,
                        )
                        for prior in sorted(
                            priors, key=lambda item: item.stable_identity
                        )
                        for current in sorted(
                            currents, key=lambda item: item.stable_identity
                        )
                    ),
                )
            ).encode()
        ).hexdigest()

        assert [
            (edge[0], edge[1]) for edge in _edge_view(result)
        ] == expected_edges
        assert all(
            not edge.accepted and edge.match == "none"
            for edge in result.lineage_candidates
        )
        assert {
            edge.ambiguous_set_id for edge in result.lineage_candidates
        } == {expected_component_id}
        assert [
            (degree.symbol.qualified_name, degree.inbound, degree.outbound)
            for degree in result.symbol_degrees
        ] == expected_degrees
        assert (
            result.lineage_components[0].component_id == expected_component_id
        )
        assert result.lineage_components[0].ambiguous is True

    assert [
        (owned.symbol.qualified_name, owned.lines)
        for owned in split.owned_lines
    ] == [
        ("split", (2,)),
        ("split_a", (21,)),
        ("split_b", (31,)),
    ]
    assert (split.changed_lines, split.repeated_lines, split.rework) == (
        3,
        3,
        Decimal("0"),
    )
    assert [
        (
            transition.current.qualified_name,
            transition.input_modified_before,
            transition.output_modified_before,
        )
        for transition in split.ledger_transitions
    ] == [
        ("split_a", True, True),
        ("split_b", True, True),
    ]
    assert [
        (owned.symbol.qualified_name, owned.lines)
        for owned in merge.owned_lines
    ] == [
        ("merge", (61,)),
        ("merge_a", (41,)),
        ("merge_b", (51,)),
    ]
    assert (merge.changed_lines, merge.repeated_lines, merge.rework) == (
        3,
        3,
        Decimal("0"),
    )


def test_addition_deletion_lookalikes_and_nested_module_ownership_are_physical_and_deduplicated():
    outer_prior = _symbol(
        "outer", start=1, end=20, body="body", structure="tree"
    )
    inner_prior = _symbol(
        "inner",
        parent="outer",
        kind="method",
        start=5,
        end=9,
        body="body",
        structure="tree",
    )
    outer_current = _symbol(
        "outer", start=1, end=20, body="body", structure="tree"
    )
    inner_current = _symbol(
        "inner",
        parent="outer",
        kind="method",
        start=5,
        end=9,
        body="body",
        structure="tree",
    )
    added_lookalike = _symbol(
        "added", path="src/added.py", body="added", structure="added"
    )
    deleted_lookalike = _symbol(
        "deleted", path="src/deleted.py", body="deleted", structure="deleted"
    )
    result = calculate_transition_rework(
        (outer_prior, inner_prior, deleted_lookalike),
        (outer_current, inner_current, added_lookalike),
        _lines("removed", "src/mod.py", 6, 6)
        + _lines("removed", "src/deleted.py", 10),
        _lines("added", "src/mod.py", 6, 6)
        + _lines("added", "src/added.py", 10),
        {},
    )

    assert [
        (
            line.side,
            line.path,
            line.line,
            line.owner.qualified_name if line.owner else None,
        )
        for line in result.changed_physical_lines
    ] == [
        ("removed", "src/mod.py", 6, "inner"),
        ("removed", "src/mod.py", 6, "inner"),
        ("removed", "src/deleted.py", 10, "deleted"),
        ("added", "src/mod.py", 6, "inner"),
        ("added", "src/mod.py", 6, "inner"),
        ("added", "src/added.py", 10, "added"),
    ]
    assert [
        (owned.symbol.qualified_name, owned.lines)
        for owned in result.owned_lines
    ] == [("inner", (6,))]
    assert result.changed_lines == 2
    assert result.repeated_lines == 0
    assert result.rework == Decimal("1")


def test_first_and_repeated_ambiguity_and_rerun_bytes_are_deterministic():
    prior_a = _symbol("a", body="copy", structure="tree", start=1)
    prior_b = _symbol("b", body="copy", structure="tree", start=10)
    current_a = _symbol("x", body="copy", structure="tree", start=20)
    current_b = _symbol("y", body="copy", structure="tree", start=30)
    first_args = (
        (prior_a, prior_b),
        (current_a, current_b),
        _lines("removed", "src/mod.py", 2),
        _lines("added", "src/mod.py", 21),
        {},
    )
    first = calculate_transition_rework(*first_args)
    repeated_ledger: dict[object, bool] = {prior_a.stable_identity: True}
    repeated = calculate_transition_rework(*first_args[:-1], repeated_ledger)
    rerun = calculate_transition_rework(*first_args[:-1], repeated_ledger)
    component_payload = repr(
        (
            tuple(symbol.stable_identity for symbol in (prior_a, prior_b)),
            tuple(symbol.stable_identity for symbol in (current_a, current_b)),
            tuple(
                (
                    prior.stable_identity,
                    current.stable_identity,
                    True,
                    True,
                    False,
                )
                for prior in (prior_a, prior_b)
                for current in (current_a, current_b)
            ),
        )
    ).encode("utf-8")
    component_id = hashlib.sha256(component_payload).hexdigest()

    assert first.model_dump_json() != repeated.model_dump_json()
    assert repeated.model_dump_json() == rerun.model_dump_json()
    assert [
        (component.component_id, component.ambiguous)
        for component in repeated.lineage_components
    ] == [(component_id, True)]
    assert {
        candidate.ambiguous_set_id for candidate in repeated.lineage_candidates
    } == {component_id}
    assert (first.changed_lines, first.repeated_lines, first.rework) == (
        2,
        0,
        Decimal("1"),
    )
    assert (
        repeated.changed_lines,
        repeated.repeated_lines,
        repeated.rework,
    ) == (
        2,
        2,
        Decimal("0"),
    )
    assert [
        (
            item.prior.qualified_name,
            item.current.qualified_name,
            item.input_modified_before,
            item.mapped_changed,
            item.output_modified_before,
        )
        for item in repeated.ledger_transitions
    ] == [
        ("a", "x", True, True, True),
        ("a", "y", True, True, True),
    ]
    assert [
        (
            item.candidate.prior.qualified_name,
            item.candidate.current.qualified_name,
            item.disposition,
            item.reason,
            item.prior_modified_before,
            item.current_modified_before,
        )
        for item in repeated.lineage_ledger
    ] == [
        ("a", "x", "rejected", "ambiguous candidate set", True, True),
        ("a", "y", "rejected", "ambiguous candidate set", True, True),
        ("b", "x", "rejected", "ambiguous candidate set", False, True),
        ("b", "y", "rejected", "ambiguous candidate set", False, True),
    ]


def test_problem_rework_carries_modified_lineage_across_every_transition():
    first = _symbol("f", start=1, end=3)
    second = _symbol("f", start=1, end=3)
    third = _symbol("f", start=1, end=3)
    evidence = calculate_problem_rework(
        (
            ReworkCheckpointInput(checkpoint_id="one", symbols=(first,)),
            ReworkCheckpointInput(
                checkpoint_id="two",
                symbols=(second,),
                removed_lines=_lines("removed", "src/mod.py", 2),
                added_lines=_lines("added", "src/mod.py", 2),
            ),
            ReworkCheckpointInput(
                checkpoint_id="three",
                symbols=(third,),
                removed_lines=_lines("removed", "src/mod.py", 2),
                added_lines=_lines("added", "src/mod.py", 2),
            ),
        )
    )

    assert evidence.checkpoint_ids == ("one", "two", "three")
    assert [
        (item.changed_lines, item.repeated_lines, item.rework)
        for item in evidence.transitions
    ] == [
        (2, 0, Decimal("1")),
        (2, 2, Decimal("0")),
    ]
    assert [
        (
            item.prior.qualified_name,
            item.current.qualified_name,
            item.input_modified_before,
            item.mapped_changed,
            item.output_modified_before,
        )
        for item in evidence.final_ledger
    ] == [("f", "f", True, False, True)]


def test_problem_rework_rejects_missing_symbol_evidence():
    with pytest.raises(ValueError, match="complete symbol evidence"):
        calculate_problem_rework(
            (
                ReworkCheckpointInput(checkpoint_id="one", symbols=()),
                ReworkCheckpointInput(checkpoint_id="two", symbols=None),
            )
        )


def test_empty_symbol_collections_are_complete_rework_evidence():
    symbol = _symbol("f", start=1, end=3)
    missing_prior = calculate_transition_rework(
        (), (symbol,), (), _lines("added", "src/mod.py", 2), {}
    )
    missing_current = calculate_transition_rework(
        (symbol,), (), _lines("removed", "src/mod.py", 2), (), {}
    )

    assert (
        missing_prior.lineage_candidates
        == missing_current.lineage_candidates
        == ()
    )
    assert missing_prior.changed_lines == missing_current.changed_lines == 0
    assert missing_prior.rework == missing_current.rework == Decimal("1")


def test_copied_absolute_roots_produce_byte_identical_canonical_lineage_evidence(
    tmp_path,
):
    left_root = tmp_path / "left-copy"
    right_root = tmp_path / "right-copy"
    left_source = left_root / "src" / "mod.py"
    right_source = right_root / "src" / "mod.py"
    left_source.parent.mkdir(parents=True)
    right_source.parent.mkdir(parents=True)
    left_source.write_text("def f():\n    return 1\n")
    right_source.write_text(left_source.read_text())
    left_path = left_source.relative_to(left_root).as_posix()
    right_path = right_source.relative_to(right_root).as_posix()

    left = calculate_transition_rework(
        (_symbol("f", path=left_path, body="body", structure="tree", start=1),),
        (
            _symbol(
                "renamed",
                path=left_path,
                body="body",
                structure="tree",
                start=1,
            ),
        ),
        _lines("removed", left_path, 2),
        _lines("added", left_path, 2),
        {},
    )
    right = calculate_transition_rework(
        (
            _symbol(
                "f", path=right_path, body="body", structure="tree", start=1
            ),
        ),
        (
            _symbol(
                "renamed",
                path=right_path,
                body="body",
                structure="tree",
                start=1,
            ),
        ),
        _lines("removed", right_path, 2),
        _lines("added", right_path, 2),
        {},
    )

    assert left_path == right_path == "src/mod.py"
    assert left.model_dump_json() == right.model_dump_json()
