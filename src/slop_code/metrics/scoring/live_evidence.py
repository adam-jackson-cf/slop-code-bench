"""Run-level production of score inputs from committed checkpoint oracles."""

from __future__ import annotations

import difflib
import hashlib
import json
from collections.abc import Iterable
from collections.abc import Sequence
from decimal import Decimal
from pathlib import Path
from typing import Any

import yaml
from pydantic import TypeAdapter
from pydantic import ValidationError

from slop_code import common
from slop_code.common.constants import HISTORICAL_PROVENANCE_DIR
from slop_code.common.constants import MEASUREMENT_ANALYSIS_DIR
from slop_code.common.constants import PENDING_ORACLES_DIR
from slop_code.evaluation import ProblemConfig
from slop_code.evaluation.locked_environment import LockedEnvironmentError
from slop_code.evaluation.locked_environment import (
    verify_locked_evaluator_environment,
)
from slop_code.evaluation.report import CorrectnessResults
from slop_code.execution import DockerEnvironmentSpec
from slop_code.execution import EnvironmentSpec
from slop_code.execution import EnvironmentSpecType
from slop_code.metrics.languages.python.graph import build_dependency_graph

from .inventory import build_inventory
from .lineage import calculate_problem_rework
from .models import Eligibility
from .models import PhysicalLineEvidence
from .models import ProductionQualityRawEvidence
from .models import ReworkCheckpointInput
from .models import SymbolIdentity
from .production import produce_production_evidence
from .production_quality import DockerProcessExecutor
from .production_quality import ProcessExecutor
from .schema import problem_key

_ENVIRONMENT_ADAPTER = TypeAdapter(EnvironmentSpecType)


def _canonical(value: object) -> bytes:
    return json.dumps(
        value, ensure_ascii=True, separators=(",", ":"), sort_keys=True
    ).encode()


def _checkpoint_status(
    prefix: str,
    problem: ProblemConfig,
    checkpoint_id: str,
    eligibility: Eligibility,
) -> tuple[str, bytes]:
    return (
        f"{prefix}/checkpoint_status.json",
        _canonical(
            {
                "checkpoint_id": checkpoint_id,
                "eligible": eligibility.eligible,
                "problem_key": problem_key(problem.name),
                "problem_name": problem.name,
                "reasons": list(eligibility.reasons),
            }
        ),
    )


def _rows(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text().splitlines() if line]


def _committed_artifacts(
    checkpoint_dir: Path,
    checkpoint_id: str,
    problem: ProblemConfig,
) -> dict[str, bytes]:
    """Return bytes verified by one exclusive live or historical bundle."""
    run_dir = checkpoint_dir.parents[1]
    problem_key = hashlib.sha256(problem.name.encode("utf-8")).hexdigest()
    oracle_dir = (
        run_dir
        / MEASUREMENT_ANALYSIS_DIR
        / "pending"
        / problem_key
        / checkpoint_id
        / PENDING_ORACLES_DIR
    )
    live = sorted(oracle_dir.glob("*.json"))
    historical_dir = (
        run_dir / MEASUREMENT_ANALYSIS_DIR / HISTORICAL_PROVENANCE_DIR
    )
    historical = sorted(historical_dir.glob("*.json"))
    if live and historical:
        raise ValueError("canonical_artifact_invalid")
    if historical:
        if len(historical) != 1:
            raise ValueError("canonical_artifact_invalid")
        bundle_path = historical[0]
        content = bundle_path.read_bytes()
        if bundle_path.stem != hashlib.sha256(content).hexdigest():
            raise ValueError("canonical_artifact_invalid")
        payload = json.loads(content)
        if (
            payload.get("kind") != "historical_provenance_bundle"
            or payload.get("source_type") != "historical"
        ):
            raise ValueError("canonical_artifact_invalid")
        problem_rows = [
            item
            for item in payload.get("problems", ())
            if item.get("problem_id") == problem.name
        ]
        if len(problem_rows) != 1:
            raise ValueError("canonical_provenance_unavailable")
        checkpoint_rows = [
            item
            for item in problem_rows[0].get("checkpoints", ())
            if item.get("checkpoint_id") == checkpoint_id
        ]
        if len(checkpoint_rows) != 1:
            raise ValueError("canonical_provenance_unavailable")
        artifacts: dict[str, bytes] = {}
        for item in checkpoint_rows[0].get("artifacts", ()):
            relative = item.get("path")
            if not isinstance(relative, str) or not item.get("presence"):
                raise ValueError("canonical_artifact_invalid")
            artifact = (checkpoint_dir / relative).read_bytes()
            if len(artifact) != item.get("bytes") or hashlib.sha256(
                artifact
            ).hexdigest() != item.get("sha256"):
                raise ValueError("canonical_artifact_invalid")
            artifacts[relative] = artifact
        return artifacts
    if len(live) != 1:
        raise RuntimeError("committed live oracle is missing")
    oracle_path = live[0]
    content = oracle_path.read_bytes()
    if oracle_path.stem != hashlib.sha256(content).hexdigest():
        raise ValueError("canonical_artifact_invalid")
    payload = json.loads(content)
    if (
        payload.get("checkpoint_id") != checkpoint_id
        or payload.get("problem_name") != problem.name
        or payload.get("problem_key") != problem_key
        or payload.get("source_type") != "live"
        or not isinstance(payload.get("canonical_parity"), dict)
    ):
        raise ValueError("canonical_artifact_invalid")
    artifacts = {}
    for item in payload.get("artifacts", ()):
        relative = item.get("relative_path")
        if not isinstance(relative, str) or not item.get("present"):
            raise ValueError("canonical_provenance_unavailable")
        artifact = (checkpoint_dir / relative).read_bytes()
        if len(artifact) != item.get("byte_count") or hashlib.sha256(
            artifact
        ).hexdigest() != item.get("sha256"):
            raise ValueError("canonical_artifact_invalid")
        artifacts[relative] = artifact
    return artifacts


def _correctness(checkpoint_dir: Path, checkpoint_id: str) -> dict[str, object]:
    report = CorrectnessResults.from_dir(checkpoint_dir)
    passed = sum(report.pass_counts.values())
    total = sum(report.total_counts.values())
    if total <= 0:
        raise ValueError("canonical_test_denominator_zero")
    return {
        "checkpoint_id": checkpoint_id,
        "produced": True,
        "passed": passed,
        "total": total,
        "rate": str(Decimal(passed) / Decimal(total)),
    }


def _verified_evaluator_python(checkpoint_dir: Path) -> Path:
    report = CorrectnessResults.from_dir(checkpoint_dir)
    metadata = report.evaluator_environment
    if not isinstance(metadata, dict):
        raise LockedEnvironmentError(
            "canonical evaluator metadata is unavailable"
        )
    environment_id = metadata.get("environment_id")
    if not isinstance(environment_id, str):
        raise LockedEnvironmentError(
            "canonical evaluator identity is unavailable"
        )
    run_dir = checkpoint_dir.resolve().parents[1]
    environment = verify_locked_evaluator_environment(
        run_dir
        / MEASUREMENT_ANALYSIS_DIR
        / "evaluator_environments"
        / environment_id,
        environment_id,
    )
    return environment.python


def _saved_environment(checkpoint_dir: Path) -> EnvironmentSpec:
    run_dir = checkpoint_dir.resolve().parents[1]
    try:
        payload = yaml.safe_load((run_dir / "environment.yaml").read_text())
        if not isinstance(payload, dict):
            raise LockedEnvironmentError("saved environment config is invalid")
        if payload.get("type") == "docker":
            docker = payload.get("docker")
            binary = docker.get("binary") if isinstance(docker, dict) else None
            if not isinstance(binary, str) or not binary:
                raise LockedEnvironmentError("saved Docker binary is invalid")
        return _ENVIRONMENT_ADAPTER.validate_python(payload)
    except ValidationError as error:
        raise LockedEnvironmentError(
            "saved environment config is invalid"
        ) from error


def _measurement_executor(
    checkpoint_dir: Path,
    environment: EnvironmentSpec | None = None,
) -> tuple[ProcessExecutor | None, str | None]:
    """Return the canonical runtime for the saved evaluation environment."""
    run_dir = checkpoint_dir.resolve().parents[1]
    environment = environment or _saved_environment(checkpoint_dir)
    if environment.type == "local":
        return None, None
    if not isinstance(environment, DockerEnvironmentSpec):
        raise LockedEnvironmentError("saved environment runtime is invalid")
    binary = environment.docker.binary
    if not binary:
        raise LockedEnvironmentError("saved Docker binary is invalid")
    run_info = yaml.safe_load(
        (checkpoint_dir.parent / common.RUN_INFO_FILENAME).read_text()
    )
    image = run_info.get("image") if isinstance(run_info, dict) else None
    if not isinstance(image, str) or not image:
        raise LockedEnvironmentError("saved Docker image is invalid")
    report = CorrectnessResults.from_dir(checkpoint_dir)
    metadata = report.evaluator_environment
    interpreter_spec = (
        metadata.get("interpreter") if isinstance(metadata, dict) else None
    )
    identity = (
        tuple(line for line in interpreter_spec.splitlines() if line)
        if isinstance(interpreter_spec, str)
        else ()
    )
    expected_hash = identity[-1] if len(identity) >= 2 else None
    if (
        expected_hash is None
        or len(expected_hash) != 64
        or any(
            character not in "0123456789abcdef" for character in expected_hash
        )
    ):
        raise LockedEnvironmentError("saved evaluator interpreter is invalid")
    return (
        DockerProcessExecutor(
            image=image,
            mount_root=run_dir,
            binary=binary,
        ),
        expected_hash,
    )


def produce_checkpoint_evidence(
    checkpoint_dir: Path, checkpoint_id: str, problem: ProblemConfig
) -> tuple[dict[str, bytes], Eligibility]:
    """Produce V/E/H raw evidence only after its saved inputs are committed.

    The oracle is verified before any expensive producer starts.  Producer
    execution errors are intentionally not caught: a broken measurement must
    not replace an already-published score generation.
    """
    checkpoint_dir = checkpoint_dir.resolve()
    prefix = f"problems/{problem_key(problem.name)}/checkpoints/{checkpoint_id}"
    try:
        _committed_artifacts(checkpoint_dir, checkpoint_id, problem)
    except ValueError as error:
        code = str(error)
        eligibility = Eligibility(
            eligible=False,
            reasons=(
                code
                if code
                in {
                    "canonical_artifact_invalid",
                    "canonical_provenance_unavailable",
                    "canonical_test_denominator_zero",
                }
                else "canonical_artifact_invalid",
            ),
        )
        return dict(
            [_checkpoint_status(prefix, problem, checkpoint_id, eligibility)]
        ), eligibility
    except (OSError, json.JSONDecodeError):
        eligibility = Eligibility(
            eligible=False, reasons=("canonical_provenance_unavailable",)
        )
        return dict(
            [_checkpoint_status(prefix, problem, checkpoint_id, eligibility)]
        ), eligibility
    file_rows = _rows(
        checkpoint_dir / common.QUALITY_DIR / common.FILES_QUALITY_SAVENAME
    )
    symbol_rows = _rows(
        checkpoint_dir / common.QUALITY_DIR / common.SYMBOLS_QUALITY_SAVENAME
    )
    snapshot = checkpoint_dir / common.SNAPSHOT_DIR_NAME
    inventory = build_inventory(
        snapshot,
        generated_globs=problem.measurement_generated_globs,
        test_globs=problem.measurement_test_globs,
    )
    try:
        environment = _saved_environment(checkpoint_dir)
        entrypoint = snapshot / environment.format_entry_file(problem.entry_file)
        evaluator_python = _verified_evaluator_python(checkpoint_dir)
        executor, expected_executable_sha256 = _measurement_executor(
            checkpoint_dir, environment
        )
    except (
        LockedEnvironmentError,
        OSError,
        UnicodeError,
        ValueError,
        yaml.YAMLError,
    ):
        eligibility = Eligibility(
            eligible=False,
            reasons=("measurement_environment_mismatch",),
        )
        return dict(
            [_checkpoint_status(prefix, problem, checkpoint_id, eligibility)]
        ), eligibility
    graph = build_dependency_graph(snapshot, entrypoint)
    produced = produce_production_evidence(
        checkpoint_id,
        snapshot,
        inventory,
        file_rows,
        symbol_rows,
        graph,
        evaluator_python,
        executor=executor,
        expected_executable_sha256=expected_executable_sha256,
    )
    raw = {
        f"{prefix}/{name}": _canonical(payload.model_dump(mode="json"))
        for name, payload in produced.payloads.items()
    }
    raw.update(
        [
            _checkpoint_status(
                prefix, problem, checkpoint_id, produced.eligibility
            )
        ]
    )
    if not produced.eligibility.eligible:
        return raw, produced.eligibility
    quality = produced.production_quality
    architecture = produced.production_graph
    if quality is None or architecture is None:
        eligibility = Eligibility(
            eligible=False, reasons=("score_evidence_invalid",)
        )
        raw.update(
            [_checkpoint_status(prefix, problem, checkpoint_id, eligibility)]
        )
        return raw, eligibility
    try:
        correctness = _correctness(checkpoint_dir, checkpoint_id)
    except ValueError as error:
        if str(error) != "canonical_test_denominator_zero":
            raise
        correctness = None
    inference = json.loads(
        (checkpoint_dir / common.INFERENCE_RESULT_FILENAME).read_bytes()
    )
    raw_cost = inference.get("usage", {}).get("cost")
    try:
        cost = Decimal(str(raw_cost))
    except Exception:  # noqa: BLE001
        cost = None
    if cost is not None and (not cost.is_finite() or cost < 0):
        cost = None
    raw.update(
        {
            f"{prefix}/production_quality.json": _canonical(
                quality.model_dump(mode="json")
            ),
            f"{prefix}/production_graph.json": _canonical(
                architecture.model_dump(mode="json")
            ),
        }
    )
    if correctness is None:
        eligibility = Eligibility(
            eligible=False,
            reasons=("canonical_test_denominator_zero",),
        )
        raw.update(
            [_checkpoint_status(prefix, problem, checkpoint_id, eligibility)]
        )
        return raw, eligibility
    row = {
        "checkpoint_correctness": correctness,
        "verbosity": str(quality.verbosity),
        "erosion": str(quality.erosion),
        "architecture": str(architecture.architecture),
        "cost": None if cost is None else str(cost),
    }
    raw[f"{prefix}.json"] = _canonical(row)
    eligibility = Eligibility(eligible=True)
    raw.update(
        [_checkpoint_status(prefix, problem, checkpoint_id, eligibility)]
    )
    return raw, eligibility


def _changed_lines(
    prior_snapshot: Path, current_snapshot: Path, paths: Iterable[str]
) -> tuple[tuple[PhysicalLineEvidence, ...], tuple[PhysicalLineEvidence, ...]]:
    """Return globally deduplicated physical lines from adjacent snapshots."""
    removed: set[tuple[str, int]] = set()
    added: set[tuple[str, int]] = set()
    for path in sorted(set(paths), key=lambda value: value.encode()):
        prior_path, current_path = (
            prior_snapshot / path,
            current_snapshot / path,
        )
        prior_lines = (
            prior_path.read_text(encoding="utf-8").splitlines()
            if prior_path.is_file()
            else []
        )
        current_lines = (
            current_path.read_text(encoding="utf-8").splitlines()
            if current_path.is_file()
            else []
        )
        matcher = difflib.SequenceMatcher(
            None, prior_lines, current_lines, autojunk=False
        )
        for (
            tag,
            prior_start,
            prior_end,
            current_start,
            current_end,
        ) in matcher.get_opcodes():
            if tag != "equal":
                removed.update(
                    (path, line)
                    for line in range(prior_start + 1, prior_end + 1)
                )
                added.update(
                    (path, line)
                    for line in range(current_start + 1, current_end + 1)
                )
    return (
        tuple(
            PhysicalLineEvidence(path=path, line=line, side="removed")
            for path, line in sorted(
                removed, key=lambda item: (item[0].encode(), item[1])
            )
        ),
        tuple(
            PhysicalLineEvidence(path=path, line=line, side="added")
            for path, line in sorted(
                added, key=lambda item: (item[0].encode(), item[1])
            )
        ),
    )


def _symbols_from_raw(
    raw: dict[str, bytes], prefix: str
) -> tuple[SymbolIdentity, ...]:
    """Project canonical eligible quality symbols into lineage identities."""
    payload = ProductionQualityRawEvidence.model_validate_json(
        raw[f"{prefix}/production_quality.json"]
    )
    return tuple(
        SymbolIdentity(
            path=path,
            qualified_name=qualified_name,
            kind=kind,
            start_line=start_line,
            end_line=end_line,
        )
        for path, qualified_name, kind, start_line, end_line in (
            item.identity for item in payload.eligible_symbols
        )
    )


def _produce_rework_evidence(
    run_dir: Path, problem: ProblemConfig, checkpoint_raw: dict[str, bytes]
) -> tuple[dict[str, bytes], Eligibility]:
    """Materialize adjacent R evidence only from complete canonical inputs."""
    checkpoint_ids = tuple(
        name for name, _ in problem.iterate_checkpoint_items()
    )
    if len(checkpoint_ids) < 2:
        return {}, Eligibility(eligible=True)
    checkpoints: list[ReworkCheckpointInput] = []
    snapshots: dict[str, Path] = {}
    for checkpoint_id in checkpoint_ids:
        prefix = (
            f"problems/{problem_key(problem.name)}/checkpoints/{checkpoint_id}"
        )
        try:
            symbols = _symbols_from_raw(checkpoint_raw, prefix)
        except (KeyError, TypeError, ValueError, json.JSONDecodeError):
            return {}, Eligibility(
                eligible=False,
                reasons=("canonical_provenance_unavailable",),
            )
        snapshots[checkpoint_id] = (
            run_dir / problem.name / checkpoint_id / common.SNAPSHOT_DIR_NAME
        )
        checkpoints.append(
            ReworkCheckpointInput(checkpoint_id=checkpoint_id, symbols=symbols)
        )
    populated: list[ReworkCheckpointInput] = [checkpoints[0]]
    for prior, current in zip(checkpoints, checkpoints[1:]):
        if prior.symbols is None or current.symbols is None:
            return {}, Eligibility(
                eligible=False,
                reasons=("canonical_provenance_unavailable",),
            )
        try:
            removed, added = _changed_lines(
                snapshots[prior.checkpoint_id],
                snapshots[current.checkpoint_id],
                (symbol.path for symbol in (*prior.symbols, *current.symbols)),
            )
        except (OSError, UnicodeError):
            return {}, Eligibility(
                eligible=False,
                reasons=("canonical_provenance_unavailable",),
            )
        populated.append(
            current.model_copy(
                update={"removed_lines": removed, "added_lines": added}
            )
        )
    evidence = calculate_problem_rework(populated)
    sidecars: dict[str, bytes] = {}
    for index, transition in enumerate(evidence.transitions):
        prior = checkpoint_ids[index]
        current = checkpoint_ids[index + 1]
        transition_id = f"{prior}--{current}"
        prefix = (
            f"problems/{problem_key(problem.name)}/transitions/{transition_id}"
        )
        sidecars[f"{prefix}/lineage.json"] = _canonical(
            transition.model_dump(mode="json")
        )
        sidecars[f"{prefix}/rework.json"] = _canonical(
            {"rework": str(transition.rework)}
        )
    return sidecars, Eligibility(eligible=True)


def produce_live_evidence(
    run_dir: Path, problem_configs: Sequence[ProblemConfig]
) -> tuple[dict[str, bytes], Eligibility]:
    """Produce ordered checkpoint evidence from immutable checkpoint snapshots."""
    sidecars: dict[str, bytes] = {}
    reasons: set[str] = set()
    evaluator_identities: set[tuple[str, ...]] = set()
    for problem in problem_configs:
        for checkpoint_id, _ in problem.iterate_checkpoint_items():
            checkpoint_dir = run_dir / problem.name / checkpoint_id
            if not (
                checkpoint_dir / common.INFERENCE_RESULT_FILENAME
            ).is_file():
                prefix = (
                    f"problems/{problem_key(problem.name)}/checkpoints/"
                    f"{checkpoint_id}"
                )
                sidecars[f"{prefix}.json"] = _canonical(
                    {
                        "checkpoint_correctness": {
                            "checkpoint_id": checkpoint_id,
                            "produced": False,
                            "passed": 0,
                            "total": 0,
                            "rate": "0",
                        },
                        "produced": False,
                        "verbosity": "0",
                        "erosion": "0",
                        "architecture": "0",
                        "cost": None,
                    }
                )
                continue
            produced, eligibility = produce_checkpoint_evidence(
                checkpoint_dir, checkpoint_id, problem
            )
            if not eligibility.eligible:
                reasons.update(eligibility.reasons)
            sidecars.update(produced)
            quality_path = (
                f"problems/{problem_key(problem.name)}/checkpoints/"
                f"{checkpoint_id}/production_quality.json"
            )
            if quality_path in produced:
                interpreter = json.loads(produced[quality_path])["interpreter"]
                evaluator_identities.add(
                    tuple(
                        interpreter[field]
                        for field in (
                            "implementation",
                            "version",
                            "cache_tag",
                            "executable_sha256",
                            "ast_sha256",
                            "tokenize_sha256",
                        )
                    )
                )
        rework, eligibility = _produce_rework_evidence(
            run_dir, problem, sidecars
        )
        sidecars.update(rework)
        if not eligibility.eligible:
            reasons.update(eligibility.reasons)
    if len(evaluator_identities) > 1:
        reasons.add("measurement_environment_mismatch")
    if reasons:
        return sidecars, Eligibility(
            eligible=False, reasons=tuple(sorted(reasons))
        )
    return sidecars, Eligibility(eligible=True)
