"""Path-independent provenance capture for immutable historical runs."""

from __future__ import annotations

import base64
import hashlib
import json
import os
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from slop_code import common
from slop_code.common.constants import HISTORICAL_PROVENANCE_DIR
from slop_code.common.constants import MEASUREMENT_ANALYSIS_DIR
from slop_code.evaluation import ProblemConfig

from .schema import canonical_json_bytes

_CANONICAL_ARTIFACTS = (
    common.EVALUATION_FILENAME,
    f"{common.QUALITY_DIR}/{common.QUALITY_METRIC_SAVENAME}",
    f"{common.QUALITY_DIR}/{common.FILES_QUALITY_SAVENAME}",
    f"{common.QUALITY_DIR}/{common.SYMBOLS_QUALITY_SAVENAME}",
)


def _hash(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _snapshot_inventory(snapshot: Path) -> list[dict[str, Any]]:
    inventory: list[dict[str, Any]] = []
    if not snapshot.is_dir():
        return inventory
    for root, directories, filenames in os.walk(snapshot, followlinks=False):
        directories.sort(key=lambda value: value.encode("utf-8"))
        filenames.sort(key=lambda value: value.encode("utf-8"))
        root_path = Path(root)
        for name in (*directories, *filenames):
            path = root_path / name
            relative = path.relative_to(snapshot).as_posix()
            if path.is_symlink():
                inventory.append(
                    {
                        "path": relative,
                        "kind": "symlink",
                        "target": path.readlink().as_posix(),
                    }
                )
            elif path.is_file():
                content = path.read_bytes()
                inventory.append(
                    {
                        "path": relative,
                        "kind": "file",
                        "bytes": len(content),
                        "sha256": _hash(content),
                    }
                )
    return sorted(inventory, key=lambda item: item["path"].encode("utf-8"))


def capture_historical_provenance(
    run_dir: Path, problem_configs: Sequence[ProblemConfig]
) -> str:
    """Capture one immutable bundle without changing canonical run artifacts."""
    problems: list[dict[str, Any]] = []
    for problem in problem_configs:
        recorded_configs: list[object] = []
        checkpoints: list[dict[str, Any]] = []
        for checkpoint_id, _ in problem.iterate_checkpoint_items():
            checkpoint_dir = run_dir / problem.name / checkpoint_id
            artifacts: list[dict[str, Any]] = []
            for relative in _CANONICAL_ARTIFACTS:
                path = checkpoint_dir / relative
                if path.is_file():
                    content = path.read_bytes()
                    record: dict[str, Any] = {
                        "path": relative,
                        "presence": True,
                        "bytes": len(content),
                        "sha256": _hash(content),
                        "observation": "observed_at_backfill",
                    }
                    if relative == common.EVALUATION_FILENAME:
                        try:
                            evaluation = json.loads(content)
                        except json.JSONDecodeError:
                            evaluation = None
                        if isinstance(evaluation, dict):
                            recorded_configs.append(
                                evaluation.get("problem_config")
                            )
                            record["recorded_at_run"] = {
                                "coverage_ledger": evaluation.get(
                                    "coverage_ledger"
                                ),
                                "environment_fingerprint": evaluation.get(
                                    "environment_fingerprint"
                                ),
                                "evaluator_environment": evaluation.get(
                                    "evaluator_environment"
                                ),
                                "entrypoint": evaluation.get("entrypoint"),
                                "invocation": evaluation.get("invocation"),
                                "platform_identity": evaluation.get(
                                    "platform_identity"
                                ),
                                "test_collection_hash": evaluation.get(
                                    "test_collection_hash"
                                ),
                                "test_corpus": evaluation.get("test_corpus"),
                                "tests": evaluation.get("tests"),
                            }
                            record["field_provenance"] = {
                                field: "recorded_at_run"
                                for field in record["recorded_at_run"]
                            }
                    artifacts.append(record)
                else:
                    artifacts.append(
                        {
                            "path": relative,
                            "presence": False,
                            "observation": "observed_at_backfill",
                        }
                    )
            snapshot = _snapshot_inventory(
                checkpoint_dir / common.SNAPSHOT_DIR_NAME
            )
            checkpoints.append(
                {
                    "checkpoint_id": checkpoint_id,
                    "artifacts": artifacts,
                    "snapshot": snapshot,
                    "snapshot_field_provenance": tuple(
                        {
                            field: "observed_at_backfill"
                            for field in sorted(item)
                        }
                        for item in snapshot
                    ),
                }
            )
        canonical_config = problem.model_dump(mode="json")
        config_bytes = canonical_json_bytes(canonical_config)
        config_recorded = (
            bool(recorded_configs)
            and len(recorded_configs) == len(checkpoints)
            and all(item == canonical_config for item in recorded_configs)
        )
        problems.append(
            {
                "problem_id": problem.name,
                "config": canonical_config,
                "config_canonical_base64": base64.b64encode(
                    config_bytes
                ).decode("ascii"),
                "config_sha256": _hash(config_bytes),
                "config_observation": (
                    "recorded_at_run"
                    if config_recorded
                    else "observed_at_backfill"
                ),
                "checkpoints": checkpoints,
            }
        )
    payload = {
        "kind": "historical_provenance_bundle",
        "source_type": "historical",
        "problems": problems,
    }
    content = canonical_json_bytes(payload)
    bundle_id = _hash(content)
    directory = run_dir / MEASUREMENT_ANALYSIS_DIR / HISTORICAL_PROVENANCE_DIR
    directory.mkdir(parents=True, exist_ok=True)
    candidates = sorted(directory.glob("*.json"))
    target = directory / f"{bundle_id}.json"
    if candidates:
        if len(candidates) != 1 or candidates[0] != target:
            raise ValueError("conflicting historical provenance bundles")
        if candidates[0].read_bytes() != content:
            raise ValueError("historical provenance bundle is corrupt")
        return bundle_id
    temporary = directory / f".{bundle_id}.{os.getpid()}.tmp"
    with temporary.open("xb") as handle:
        handle.write(content)
        handle.flush()
        os.fsync(handle.fileno())
    temporary.replace(target)
    descriptor = os.open(directory, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    return bundle_id
