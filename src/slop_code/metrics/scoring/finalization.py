"""Run-level finalization from durable canonical scoring producer artifacts."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Sequence
from pathlib import Path
from typing import cast

from slop_code.evaluation import ProblemConfig

from .generation import aggregate_eligibility
from .generation import finalize_lock
from .generation import publish_generation
from .generation import score_evidence_sidecar
from .live_evidence import produce_live_evidence
from .live_regression import produce_live_regression_evidence
from .models import BenchmarkScore
from .models import BenchmarkScoreInput
from .models import CheckpointCostEvidence
from .models import Eligibility
from .models import ProblemCostEvidence
from .models import ProblemScoreInput
from .models import ScoreEvidenceIndex
from .schema import canonical_json_bytes
from .schema import problem_key
from .schema import scoring_schema_id

_CHECKPOINT_PREFIX = "problems/"
_RUN_IDENTITY = "run_identity.json"
_NO_PRODUCED_CHECKPOINTS_SCHEMA_ID = hashlib.sha256(
    b"no-produced-checkpoints"
).hexdigest()


def _fragment_identity(sidecars: dict[str, bytes]) -> str:
    raw = sidecars.get(_RUN_IDENTITY)
    if raw is not None:
        try:
            value = json.loads(raw)
            if isinstance(value, str) and value:
                return value
        except json.JSONDecodeError:
            pass
    digest = hashlib.sha256()
    for path in sorted(sidecars):
        digest.update(path.encode())
        digest.update(b"\0")
        digest.update(sidecars[path])
    return digest.hexdigest()


def _build_score_evidence(
    sidecars: dict[str, bytes], problem_configs: Sequence[ProblemConfig]
) -> tuple[ScoreEvidenceIndex | None, Eligibility]:
    """Assemble canonical aggregate evidence from checkpoint producer sidecars."""
    checkpoints: dict[tuple[str, str], object] = {}
    checkpoint_statuses: dict[tuple[str, str], dict[str, object]] = {}
    transitions: dict[tuple[str, str], dict[str, object]] = {}
    parser_tokenizer_schema_ids: set[str] = set()
    reasons: set[str] = set()
    for path, raw in sidecars.items():
        if not path.startswith(_CHECKPOINT_PREFIX):
            continue
        try:
            problem, tail = path[len(_CHECKPOINT_PREFIX) :].split(
                "/", maxsplit=1
            )
            if tail.startswith("checkpoints/") and tail.endswith(
                "/checkpoint_status.json"
            ):
                checkpoint_id = tail.removeprefix("checkpoints/").removesuffix(
                    "/checkpoint_status.json"
                )
                checkpoint_statuses[(problem, checkpoint_id)] = json.loads(raw)
            elif tail.startswith("checkpoints/") and tail.endswith(
                "/production_quality.json"
            ):
                quality = json.loads(raw)
                parser_tokenizer_schema_ids.add(
                    quality["parser_tokenizer_schema_id"]
                )
            elif tail.startswith("checkpoints/") and tail.endswith(".json"):
                checkpoints[
                    (problem, tail.removeprefix("checkpoints/")[:-5])
                ] = json.loads(raw)
            elif tail.startswith("transitions/") and tail.endswith(
                "/rework.json"
            ):
                transition_id = tail.removeprefix("transitions/").removesuffix(
                    "/rework.json"
                )
                transitions.setdefault((problem, transition_id), {}).update(
                    json.loads(raw)
                )
            elif tail.startswith("transitions/") and tail.endswith(
                "/regression.json"
            ):
                transition_id = tail.removeprefix("transitions/").removesuffix(
                    "/regression.json"
                )
                transitions.setdefault((problem, transition_id), {}).update(
                    json.loads(raw)
                )
        except (ValueError, json.JSONDecodeError):
            reasons.add("canonical_artifact_invalid")
    inputs: list[ProblemScoreInput] = []
    costs: list[ProblemCostEvidence] = []
    for config in problem_configs:
        checkpoint_ids = tuple(
            name for name, _ in config.iterate_checkpoint_items()
        )
        if len(checkpoint_ids) < 2:
            reasons.add("configured_problem_too_short")
            continue
        rows: list[dict[str, object]] = []
        for checkpoint_id in checkpoint_ids:
            payload = checkpoints.get((problem_key(config.name), checkpoint_id))
            if not isinstance(payload, dict):
                status = checkpoint_statuses.get(
                    (problem_key(config.name), checkpoint_id)
                )
                status_reasons = (
                    status.get("reasons") if isinstance(status, dict) else None
                )
                if (
                    isinstance(status_reasons, list)
                    and status_reasons
                    and all(
                        isinstance(reason, str) for reason in status_reasons
                    )
                ):
                    reasons.update(cast("list[str]", status_reasons))
                else:
                    reasons.add("canonical_provenance_unavailable")
                continue
            rows.append(cast("dict[str, object]", payload))
        transition_rows: list[dict[str, object]] = []
        for prior, current in zip(checkpoint_ids, checkpoint_ids[1:]):
            payload = transitions.get(
                (problem_key(config.name), f"{prior}--{current}")
            )
            if not isinstance(payload, dict) or not {
                "rework",
                "regression",
            }.issubset(payload):
                reasons.add("canonical_provenance_unavailable")
                continue
            transition_rows.append(payload)
        if (
            len(rows) != len(checkpoint_ids)
            or len(transition_rows) != len(checkpoint_ids) - 1
        ):
            continue
        try:
            inputs.append(
                ProblemScoreInput.model_validate(
                    {
                        "problem_id": config.name,
                        "checkpoint_ids": checkpoint_ids,
                        "checkpoint_correctness": [
                            row["checkpoint_correctness"] for row in rows
                        ],
                        "verbosity": [row["verbosity"] for row in rows],
                        "erosion": [row["erosion"] for row in rows],
                        "architecture": [row["architecture"] for row in rows],
                        "rework": [row["rework"] for row in transition_rows],
                        "regression": [
                            row["regression"] for row in transition_rows
                        ],
                    }
                )
            )
            costs.append(
                ProblemCostEvidence(
                    problem_id=config.name,
                    checkpoints=tuple(
                        CheckpointCostEvidence.model_validate(
                            {
                                "checkpoint_id": checkpoint_id,
                                "produced": bool(row.get("produced", True)),
                                "cost": row["cost"],
                            }
                        )
                        for checkpoint_id, row in zip(
                            checkpoint_ids, rows, strict=True
                        )
                    ),
                )
            )
        except (KeyError, TypeError, ValueError):
            reasons.add("canonical_artifact_invalid")
    if not parser_tokenizer_schema_ids:
        all_declared_zero = bool(checkpoints) and all(
            isinstance(payload, dict)
            and cast("dict[str, object]", payload).get("produced") is False
            for payload in checkpoints.values()
        )
        if all_declared_zero:
            parser_tokenizer_schema_ids.add(_NO_PRODUCED_CHECKPOINTS_SCHEMA_ID)
        else:
            reasons.add("measurement_environment_mismatch")
    elif len(parser_tokenizer_schema_ids) != 1:
        reasons.add("measurement_environment_mismatch")
    if reasons:
        return None, Eligibility(eligible=False, reasons=tuple(sorted(reasons)))
    evidence = ScoreEvidenceIndex(
        parser_tokenizer_schema_id=next(iter(parser_tokenizer_schema_ids)),
        problems=tuple(inputs),
        benchmark=BenchmarkScoreInput.model_validate(
            {
                "configured_problem_ids": tuple(
                    config.name for config in problem_configs
                ),
                "configured_checkpoint_counts": tuple(
                    len(tuple(config.iterate_checkpoint_items()))
                    for config in problem_configs
                ),
                "costs": costs,
                "run_identity": _fragment_identity(sidecars),
            }
        ),
    )
    return evidence, Eligibility(eligible=True)


def _missing_regression_transitions(
    sidecars: dict[str, bytes], problem_configs: Sequence[ProblemConfig]
) -> set[tuple[str, str, str]]:
    """Return configured transitions without a canonical regression fragment."""
    missing: set[tuple[str, str, str]] = set()
    for config in problem_configs:
        checkpoint_ids = tuple(
            name for name, _ in config.iterate_checkpoint_items()
        )
        for prior, current in zip(checkpoint_ids, checkpoint_ids[1:]):
            path = (
                f"problems/{problem_key(config.name)}/transitions/"
                f"{prior}--{current}/regression.json"
            )
            if path not in sidecars:
                missing.add((config.name, prior, current))
    return missing


def _generation_inputs(
    run_dir: Path,
    problem_configs: Sequence[ProblemConfig],
    sidecars: dict[str, bytes],
) -> bytes:
    analysis = run_dir / "measurement_analysis"
    source_artifacts = []
    for directory in ("pending", "historical_provenance"):
        root = analysis / directory
        for path in sorted(root.rglob("*.json")):
            content = path.read_bytes()
            source_artifacts.append(
                {
                    "path": path.relative_to(analysis).as_posix(),
                    "byte_length": len(content),
                    "sha256": hashlib.sha256(content).hexdigest(),
                }
            )
    return canonical_json_bytes(
        {
            "schema_id": scoring_schema_id(),
            "problem_configs": [
                config.model_dump(mode="json") for config in problem_configs
            ],
            "source_artifacts": source_artifacts,
            "producer_inputs": [
                {
                    "path": path,
                    "byte_length": len(content),
                    "sha256": hashlib.sha256(content).hexdigest(),
                }
                for path, content in sorted(sidecars.items())
            ],
        }
    )


def _materialize_score_evidence(
    sidecars: dict[str, bytes],
    problem_configs: Sequence[ProblemConfig],
    run_dir: Path,
) -> Eligibility:
    checkpoint_evidence, checkpoint_eligibility = produce_live_evidence(
        run_dir, problem_configs
    )
    sidecars.update(checkpoint_evidence)
    transitions = _missing_regression_transitions(sidecars, problem_configs)
    regression, regression_eligibility = produce_live_regression_evidence(
        run_dir,
        problem_configs,
        transitions,
        lineage_sidecars=checkpoint_evidence,
    )
    sidecars.update(regression)
    sidecars["generation_inputs.json"] = _generation_inputs(
        run_dir, problem_configs, sidecars
    )
    evidence, evidence_eligibility = _build_score_evidence(
        sidecars, problem_configs
    )
    if evidence is not None:
        name, payload = score_evidence_sidecar(evidence)
        sidecars[name] = payload
    return aggregate_eligibility(
        (
            checkpoint_eligibility,
            regression_eligibility,
            evidence_eligibility,
        )
    )


def _producer_status_rows(
    problem_configs: Sequence[ProblemConfig],
    sidecars: dict[str, bytes],
    eligibility: Eligibility,
) -> tuple[dict[str, object], ...]:
    blocked_by = (
        eligibility.reasons[0]
        if eligibility.reasons
        else "required_evidence_missing"
    )
    rows: list[dict[str, object]] = []
    for problem in problem_configs:
        checkpoint_ids = tuple(
            name for name, _ in problem.iterate_checkpoint_items()
        )
        for checkpoint_id in checkpoint_ids:
            prefix = (
                f"problems/{problem_key(problem.name)}/checkpoints/"
                f"{checkpoint_id}"
            )
            checkpoint_payload = sidecars.get(f"{prefix}.json")
            declared_zero = False
            if checkpoint_payload is not None:
                try:
                    declared_zero = (
                        json.loads(checkpoint_payload).get("produced") is False
                    )
                except (AttributeError, json.JSONDecodeError):
                    declared_zero = False
            complete = declared_zero or all(
                path in sidecars
                for path in (
                    f"{prefix}.json",
                    f"{prefix}/production_quality.json",
                    f"{prefix}/production_graph.json",
                )
            )
            checkpoint_blocked_by = blocked_by
            status_raw = sidecars.get(f"{prefix}/checkpoint_status.json")
            if status_raw is not None:
                try:
                    status = json.loads(status_raw)
                    status_reasons = status.get("reasons")
                    if (
                        isinstance(status_reasons, list)
                        and status_reasons
                        and isinstance(status_reasons[0], str)
                    ):
                        checkpoint_blocked_by = status_reasons[0]
                except (AttributeError, json.JSONDecodeError):
                    checkpoint_blocked_by = "canonical_artifact_invalid"
            rows.append(
                {
                    "producer": "checkpoint_evidence",
                    "unit": f"{problem.name}/{checkpoint_id}",
                    "status": ("successful" if complete else "blocked"),
                    "blocked_by": (None if complete else checkpoint_blocked_by),
                }
            )
        for prior, current in zip(
            checkpoint_ids, checkpoint_ids[1:], strict=False
        ):
            prefix = (
                f"problems/{problem_key(problem.name)}/transitions/"
                f"{prior}--{current}"
            )
            complete = all(
                path in sidecars
                for path in (
                    f"{prefix}/rework.json",
                    f"{prefix}/regression.json",
                )
            )
            rows.append(
                {
                    "producer": "transition_evidence",
                    "unit": f"{problem.name}/{prior}--{current}",
                    "status": ("successful" if complete else "blocked"),
                    "blocked_by": None if complete else blocked_by,
                }
            )
    score_complete = "score_evidence.json" in sidecars
    rows.append(
        {
            "producer": "score_assembly",
            "unit": "benchmark",
            "status": ("successful" if score_complete else "blocked"),
            "blocked_by": None if score_complete else blocked_by,
        }
    )
    return tuple(rows)


def finalize_benchmark_score(
    run_dir: Path,
    problem_configs: Sequence[ProblemConfig],
    *,
    lock_held: bool = False,
) -> BenchmarkScore | None:
    """Publish one verified score generation from durable producer artifacts."""
    names = tuple(problem.name for problem in problem_configs)
    if len(names) != len(set(names)):
        raise ValueError("configured problem names must be unique")

    def finalize_locked() -> BenchmarkScore | None:
        sidecars: dict[str, bytes] = {}
        eligibility = _materialize_score_evidence(
            sidecars, problem_configs, run_dir
        )
        manifest = publish_generation(
            run_dir,
            sidecars,
            eligibility,
            producer_status_rows=_producer_status_rows(
                problem_configs, sidecars, eligibility
            ),
            lock_held=True,
            allow_formula_cutover=True,
        )
        return manifest.benchmark

    if lock_held:
        return finalize_locked()
    with finalize_lock(run_dir):
        return finalize_locked()
