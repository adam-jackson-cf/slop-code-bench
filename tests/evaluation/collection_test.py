from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from slop_code import evaluation
from slop_code.common import WORKSPACE_TEST_DIR
from slop_code.evaluation.collection import _build_collect_cmd
from slop_code.evaluation.collection import _locked_evaluator_mounts
from slop_code.evaluation.collection import compute_tc_hash


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

    mounts = _locked_evaluator_mounts(session, Path("measurement_analysis"))

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
