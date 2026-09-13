from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import cast

from slop_code import evaluation
from slop_code.common import WORKSPACE_TEST_DIR
from slop_code.evaluation.collection import CheckpointTestCollection
from slop_code.evaluation.collection import CollectedTestCase
from slop_code.evaluation.collection import _build_collect_cmd
from slop_code.evaluation.collection import _group_key
from slop_code.evaluation.collection import _locked_evaluator_mounts
from slop_code.evaluation.collection import _parse_collect_stdout
from slop_code.evaluation.collection import apply_collection_inventory
from slop_code.evaluation.collection import compute_tc_hash
from slop_code.evaluation.config import MarkerConfig
from slop_code.evaluation.config import classify_test_group
from slop_code.evaluation.report import CorrectnessResults
from slop_code.evaluation.report import GroupType
from slop_code.evaluation.report import TestResult as EvalTestResult
from slop_code.execution.session import Session


def test_public_collection_functions_exported() -> None:
    assert callable(evaluation.collect_checkpoint_tc)
    assert callable(evaluation.compute_tc_hash)


def test_collect_cmd_uses_locked_evaluator_and_excludes_agent_conftest(
    tmp_path: Path,
) -> None:
    """Collection runs with the verified evaluator interpreter."""
    evaluator_python = tmp_path / "evaluator/bin/python"
    cmd = _build_collect_cmd(
        evaluator_python=evaluator_python,
        checkpoint_name="checkpoint_1",
        entrypoint="python main.py",
        marker="functionality",
        pytest_args=["--disable-warnings"],
    )

    assert cmd == (
        f"{evaluator_python} -m pytest --collect-only -q "
        f"{WORKSPACE_TEST_DIR} --confcutdir={WORKSPACE_TEST_DIR} "
        "--entrypoint='python main.py' --checkpoint=checkpoint_1 "
        "-m functionality -k checkpoint_1 --disable-warnings"
    )


def test_locked_evaluator_mount_resolves_relative_host_path() -> None:
    """Docker evaluator mounts always use absolute host paths."""
    session = SimpleNamespace(
        spec=SimpleNamespace(
            type="docker",
            docker=SimpleNamespace(workdir="/workspace"),
        )
    )

    mounts = _locked_evaluator_mounts(
        cast(Session, session), Path("measurement_analysis")
    )

    assert mounts == {
        str(Path("measurement_analysis").resolve()): {
            "bind": "/workspace/.scbench-evaluator-cache",
            "mode": "rw",
        }
    }


def test_compute_tc_hash_stable_for_reordered_input() -> None:
    hash_a = compute_tc_hash(
        {
            "checkpoint_2-Core": ["test_b", "test_a"],
            "checkpoint_2-Error": ["test_e"],
        }
    )
    hash_b = compute_tc_hash(
        {
            "checkpoint_2-Error": ["test_e"],
            "checkpoint_2-Core": ["test_a", "test_b"],
        }
    )
    assert hash_a == hash_b


def test_collection_preserves_parameterized_nodeids_with_whitespace() -> None:
    nodeid = (
        "tests/test_checkpoint_2.py::test_parameterized[space / punctuation: !]"
    )
    test_id = "test_parameterized[space / punctuation: !]"
    collection = CheckpointTestCollection(
        tests=[
            CollectedTestCase(
                nodeid=nodeid,
                test_id=test_id,
                file_path="tests/test_checkpoint_2.py",
                checkpoint="checkpoint_2",
                group_type=GroupType.CORE,
            )
        ],
        by_nodeid={},
        grouped_test_ids={"checkpoint_2-Core": [test_id]},
        total_collected=1,
        test_collection_hash=compute_tc_hash({"checkpoint_2-Core": [test_id]}),
    )
    results = CorrectnessResults(
        problem_name="fixture",
        problem_version=1,
        checkpoint_name="checkpoint_2",
        checkpoint_version=1,
        duration=0.0,
        entrypoint="python main.py",
        pytest_exit_code=0,
        pytest_collected=1,
    )
    results.add_test_result(
        EvalTestResult(
            id=test_id,
            checkpoint="checkpoint_2",
            group_type=GroupType.CORE,
            status="skipped",
            duration_ms=0.0,
            file_path="tests/test_checkpoint_2.py",
        )
    )

    assert _parse_collect_stdout(f"{nodeid}\n") == [nodeid]
    applied = apply_collection_inventory(results, collection)

    assert applied.tests[0].id == test_id
    assert applied.test_collection_hash == collection.test_collection_hash
    assert applied.pytest_collected == 1
    assert applied.total_counts[GroupType.CORE] == 0
    assert applied.pass_counts[GroupType.CORE] == 0
    assert not applied.infrastructure_failure


def test_custom_functionality_marker_collects_and_reconciles() -> None:
    custom_markers = {
        "custom_functionality": MarkerConfig(
            description="custom functionality tests",
            group=GroupType.FUNCTIONALITY,
        )
    }
    group_type = classify_test_group(
        test_checkpoint="checkpoint_2",
        current_checkpoint="checkpoint_2",
        markers=["custom_functionality"],
        custom_markers=custom_markers,
    )
    nodeid = "tests/test_checkpoint_2.py::test_custom_functionality"
    collected = CollectedTestCase(
        nodeid=nodeid,
        test_id="test_custom_functionality",
        file_path="tests/test_checkpoint_2.py",
        checkpoint="checkpoint_2",
        group_type=group_type,
    )
    collection = CheckpointTestCollection(
        tests=[collected],
        by_nodeid={nodeid: collected},
        grouped_test_ids={
            _group_key(collected.checkpoint, collected.group_type): [
                collected.test_id
            ]
        },
        total_collected=1,
        test_collection_hash="custom-hash",
    )
    results = CorrectnessResults(
        problem_name="fixture",
        problem_version=1,
        checkpoint_name="checkpoint_2",
        checkpoint_version=1,
        duration=0.0,
        entrypoint="python main.py",
        pytest_exit_code=0,
        pytest_collected=1,
    )
    results.add_test_result(
        EvalTestResult(
            id=collected.test_id,
            checkpoint=collected.checkpoint,
            group_type=GroupType.CORE,
            status="passed",
            duration_ms=0.0,
            file_path=collected.file_path,
        )
    )

    applied = apply_collection_inventory(results, collection)

    assert type(group_type) is GroupType
    assert applied.tests[0].group_type is GroupType.FUNCTIONALITY
    assert applied.total_counts[GroupType.FUNCTIONALITY] == 1
    assert applied.pass_counts[GroupType.FUNCTIONALITY] == 1
