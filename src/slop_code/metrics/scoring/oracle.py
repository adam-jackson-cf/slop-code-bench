"""Immutable, read-only capture of the strict baseline artifacts."""

from __future__ import annotations

import base64
import fcntl
import hashlib
import json
import os
import tempfile
from contextlib import contextmanager
from contextlib import suppress
from pathlib import Path
from typing import Any

from slop_code.common.constants import MEASUREMENT_ANALYSIS_DIR
from slop_code.common.constants import PENDING_ORACLES_DIR

from .models import OracleArtifact
from .models import OracleBaseline
from .models import OracleBundle
from .models import OracleCheckpointProjection

BASELINE_DIRECTORY_NAMES = (
    "strict-baseline-sol-20260831",
    "strict-baseline-terra-20260831",
    "strict-baseline-luna-20260831",
)

_TARGET_FILENAMES = frozenset(
    {
        "checkpoint_results.jsonl",
        "overall_quality.json",
        "files.jsonl",
        "symbols.jsonl",
    }
)


def _canonical_json_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def _report_rows(path: Path, content: bytes) -> tuple[Any, ...]:
    """Decode report records without rewriting their source bytes."""
    try:
        text = content.decode("utf-8")
        if path.suffix == ".jsonl":
            return tuple(json.loads(line) for line in text.splitlines())
        return (json.loads(text),)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError(f"invalid report artifact: {path}") from error


def _projection_rows(report_row: Any) -> tuple[tuple[str, str], ...]:
    """Represent a decoded report record as ordered identity/value pairs."""
    if isinstance(report_row, dict):
        return tuple(
            (
                key,
                _canonical_json_bytes(value).decode("ascii"),
            )
            for key, value in sorted(report_row.items())
        )
    return (("value", _canonical_json_bytes(report_row).decode("ascii")),)


def _checkpoint_id(
    path: Path, relative_path: str, report_row: Any, ordinal: int
) -> str:
    """Return the explicit checkpoint identity for one report record."""
    if isinstance(report_row, dict) and isinstance(
        report_row.get("checkpoint"), str
    ):
        return report_row["checkpoint"]
    if path.parent.name == "quality_analysis":
        return path.parent.parent.name
    return f"{relative_path}#{ordinal}"


def _projections(
    path: Path, relative_path: str, content: bytes
) -> tuple[OracleCheckpointProjection, ...]:
    """Project ordered report records into their typed canonical form."""
    return tuple(
        OracleCheckpointProjection(
            checkpoint_id=_checkpoint_id(
                path, relative_path, report_row, ordinal
            ),
            ordinal=ordinal,
            output_sha256=hashlib.sha256(
                _canonical_json_bytes(report_row)
            ).hexdigest(),
            report_rows=_projection_rows(report_row),
        )
        for ordinal, report_row in enumerate(_report_rows(path, content))
    )


def _artifact_paths(baseline_directory: Path) -> tuple[Path, ...]:
    checkpoint_results = baseline_directory / "checkpoint_results.jsonl"
    if not checkpoint_results.is_file():
        raise ValueError(f"missing baseline artifact: {checkpoint_results}")

    quality_artifacts = tuple(
        path
        for path in baseline_directory.rglob("*")
        if path.is_file()
        and path.parent.name == "quality_analysis"
        and path.name in _TARGET_FILENAMES - {"checkpoint_results.jsonl"}
    )
    return (
        checkpoint_results,
        *sorted(quality_artifacts, key=lambda path: path.as_posix()),
    )


def capture_baseline_oracle(repository_root: Path) -> OracleBundle:
    """Capture the three immutable baseline archives using repository-relative paths."""
    root = repository_root.resolve()
    baselines: list[OracleBaseline] = []
    for baseline_name in BASELINE_DIRECTORY_NAMES:
        baseline_directory = root / "experiments" / baseline_name
        if not baseline_directory.is_dir():
            raise ValueError(
                f"missing baseline directory: {baseline_directory}"
            )
        artifacts: list[OracleArtifact] = []
        for path in _artifact_paths(baseline_directory):
            content = path.read_bytes()
            relative_path = path.relative_to(root).as_posix()
            artifacts.append(
                OracleArtifact(
                    relative_path=relative_path,
                    sha256=hashlib.sha256(content).hexdigest(),
                    bytes_base64=base64.b64encode(content).decode("ascii"),
                    projections=_projections(path, relative_path, content),
                )
            )
        baselines.append(
            OracleBaseline(name=baseline_name, artifacts=tuple(artifacts))
        )
    return OracleBundle(baselines=tuple(baselines))


def serialize_baseline_oracle(oracle: OracleBundle) -> bytes:
    """Serialize an oracle in its checked-fixture canonical representation."""
    return _canonical_json_bytes(oracle.model_dump(mode="json")) + b"\n"


def validate_baseline_oracle(
    repository_root: Path, oracle: OracleBundle
) -> None:
    """Raise when archived bytes, hashes, paths, or decoded report rows differ."""
    captured = capture_baseline_oracle(repository_root)
    if serialize_baseline_oracle(captured) != serialize_baseline_oracle(oracle):
        raise ValueError("baseline oracle does not match archived artifacts")


_LIVE_ORACLE_LOCK_FILENAME = "oracle.lock"
_LIVE_ORACLE_TEMP_PREFIX = ".oracle."


def _live_artifact_paths(checkpoint_dir: Path) -> tuple[Path, ...]:
    """Return the canonical evaluation artifacts in their saved-path order."""
    from slop_code import common

    quality_dir = checkpoint_dir / common.QUALITY_DIR
    return (
        checkpoint_dir / common.EVALUATION_FILENAME,
        quality_dir / common.QUALITY_METRIC_SAVENAME,
        quality_dir / common.FILES_QUALITY_SAVENAME,
        quality_dir / common.SYMBOLS_QUALITY_SAVENAME,
    )


def _live_artifact_projection(
    path: Path, content: bytes
) -> tuple[dict[str, Any], ...]:
    """Decode canonical JSON reports without measuring or rewriting them."""
    return tuple(
        {
            "checkpoint_id": _checkpoint_id(
                path, path.as_posix(), row, ordinal
            ),
            "ordinal": ordinal,
            "output_sha256": hashlib.sha256(
                _canonical_json_bytes(row)
            ).hexdigest(),
            "report_rows": _projection_rows(row),
        }
        for ordinal, row in enumerate(_report_rows(path, content))
    )


def _live_oracle_payload(
    checkpoint_dir: Path, problem_name: str, checkpoint_id: str
) -> bytes:
    """Build the exact saved-artifact oracle for one evaluated checkpoint."""
    artifacts: list[dict[str, Any]] = []
    parity: dict[str, Any] | None = None
    for path in _live_artifact_paths(checkpoint_dir):
        relative_path = path.relative_to(checkpoint_dir).as_posix()
        if not path.is_file():
            artifacts.append(
                {
                    "relative_path": relative_path,
                    "present": False,
                    "sha256": None,
                    "byte_count": 0,
                    "projections": (),
                }
            )
            continue
        content = path.read_bytes()
        if relative_path == "evaluation.json":
            report = json.loads(content)
            parity = {
                "coverage_ledger": report.get("coverage_ledger"),
                "environment_fingerprint": report.get(
                    "environment_fingerprint"
                ),
                "evaluator_environment": report.get("evaluator_environment"),
                "invocation": report.get("invocation"),
                "platform": report.get("platform_identity"),
                "test_collection_hash": report.get("test_collection_hash"),
                "test_corpus": report.get("test_corpus"),
            }
            if (
                not isinstance(parity["coverage_ledger"], dict)
                or not isinstance(parity["environment_fingerprint"], str)
                or not isinstance(parity["evaluator_environment"], dict)
                or not isinstance(parity["invocation"], dict)
                or not isinstance(parity["platform"], dict)
                or not isinstance(parity["test_collection_hash"], str)
                or not isinstance(parity["test_corpus"], dict)
            ):
                raise ValueError("canonical parity evidence is unavailable")
        artifacts.append(
            {
                "relative_path": relative_path,
                "present": True,
                "sha256": hashlib.sha256(content).hexdigest(),
                "byte_count": len(content),
                "projections": _live_artifact_projection(path, content),
            }
        )
    if parity is None:
        raise ValueError("canonical parity evidence is unavailable")
    return _canonical_json_bytes(
        {
            "problem_key": hashlib.sha256(
                problem_name.encode("utf-8")
            ).hexdigest(),
            "problem_name": problem_name,
            "checkpoint_id": checkpoint_id,
            "source_type": "live",
            "canonical_parity": parity,
            "artifacts": artifacts,
        }
    )


@contextmanager
def _locked_live_oracle(oracle_dir: Path):
    """Serialize capture across threads and processes while recovering stale temps."""
    oracle_dir.mkdir(parents=True, exist_ok=True)
    lock_path = oracle_dir / _LIVE_ORACLE_LOCK_FILENAME
    with lock_path.open("a+b") as lock_file:
        fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
        try:
            for stale_temp in oracle_dir.glob(f"{_LIVE_ORACLE_TEMP_PREFIX}*"):
                if stale_temp.is_file():
                    with suppress(FileNotFoundError):
                        stale_temp.unlink()
            yield
        finally:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)


def _atomic_write_oracle(path: Path, payload: bytes) -> None:
    """Durably replace an oracle file with a fully fsynced payload."""
    descriptor, temp_name = tempfile.mkstemp(
        prefix=_LIVE_ORACLE_TEMP_PREFIX, dir=path.parent
    )
    try:
        with os.fdopen(descriptor, "wb") as temp_file:
            temp_file.write(payload)
            temp_file.flush()
            os.fsync(temp_file.fileno())
        Path(temp_name).replace(path)
        directory_descriptor = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory_descriptor)
        finally:
            os.close(directory_descriptor)
    except BaseException:
        with suppress(FileNotFoundError):
            Path(temp_name).unlink()
        raise


def capture_live_checkpoint_oracle(
    checkpoint_dir: Path, problem_name: str, checkpoint_id: str
) -> Path:
    """Commit an immutable, ID-addressed post-save canonical oracle."""
    run_dir = checkpoint_dir.parents[1]
    problem_key = hashlib.sha256(problem_name.encode("utf-8")).hexdigest()
    oracle_dir = (
        run_dir
        / MEASUREMENT_ANALYSIS_DIR
        / "pending"
        / problem_key
        / checkpoint_id
        / PENDING_ORACLES_DIR
    )
    payload = _live_oracle_payload(checkpoint_dir, problem_name, checkpoint_id)
    oracle_id = hashlib.sha256(payload).hexdigest()
    oracle_path = oracle_dir / f"{oracle_id}.json"
    with _locked_live_oracle(oracle_dir):
        existing = sorted(
            path for path in oracle_dir.glob("*.json") if path.is_file()
        )
        if existing:
            if (
                existing == [oracle_path]
                and oracle_path.read_bytes() == payload
            ):
                return oracle_path
            raise ValueError(
                f"ambiguous or conflicting committed oracle for checkpoint "
                f"'{checkpoint_id}'"
            )
        _atomic_write_oracle(oracle_path, payload)
    return oracle_path
