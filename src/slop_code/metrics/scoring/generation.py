"""Atomic immutable publication from verified, typed score evidence."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import uuid
from collections.abc import Callable
from contextlib import contextmanager
from pathlib import Path
from typing import Literal

from slop_code.common.constants import BENCHMARK_SCORE_FILENAME
from slop_code.common.constants import CHECKPOINT_REPORT_ADDITIONS_FILENAME
from slop_code.common.constants import CURRENT_POINTER_FILENAME
from slop_code.common.constants import ELIGIBILITY_FILENAME
from slop_code.common.constants import EVIDENCE_INDEX_FILENAME
from slop_code.common.constants import FINALIZE_LOCK_FILENAME
from slop_code.common.constants import GENERATIONS_DIR
from slop_code.common.constants import MANIFEST_FILENAME
from slop_code.common.constants import MEASUREMENT_ANALYSIS_DIR
from slop_code.common.constants import PROBLEM_SCORE_FILENAME
from slop_code.common.constants import PRODUCER_STATUS_FILENAME
from slop_code.common.constants import STAGING_DIR

from .models import BenchmarkScore
from .models import CheckpointReportAddition
from .models import Eligibility
from .models import EvidenceIndexEntry
from .models import GenerationManifest
from .models import ProblemScore
from .models import PublicationState
from .models import ScoreEvidenceIndex
from .schema import calculate_scores
from .schema import canonical_json_bytes
from .schema import generation_formula_id
from .schema import problem_key
from .schema import scoring_schema_id

_SCORE_EVIDENCE_PATH = "score_evidence.json"
_READY_FILENAME = "READY"

PublicationBoundary = Literal[
    "before_file_write",
    "after_file_write",
    "before_file_fsync",
    "after_file_fsync",
    "before_directory_fsync",
    "after_directory_fsync",
    "before_generation_rename",
    "after_generation_rename",
    "before_pointer_write",
    "after_pointer_write",
    "before_pointer_rename",
    "after_pointer_rename",
    "before_cleanup",
    "after_cleanup",
]
PublicationFailureObserver = Callable[[PublicationBoundary], None]


def _observe(
    observer: PublicationFailureObserver | None, boundary: PublicationBoundary
) -> None:
    if observer is not None:
        observer(boundary)


class ScoreEvidenceError(ValueError):
    """Closed-set aggregate validation failure for score input sidecars."""

    def __init__(self, reasons: set[str]) -> None:
        self.reasons = tuple(sorted(reasons))
        super().__init__(", ".join(self.reasons))


def _hash(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _safe_relative_path(path: str) -> Path:
    relative = Path(path)
    if relative.is_absolute() or ".." in relative.parts or not relative.parts:
        raise ValueError("evidence paths must be non-empty relative paths")
    return relative


def _index_bytes(entries: tuple[EvidenceIndexEntry, ...]) -> bytes:
    return canonical_json_bytes(
        [entry.model_dump(mode="json") for entry in entries]
    )


def _mkdir_durable(
    path: Path, observer: PublicationFailureObserver | None = None
) -> None:
    missing: list[Path] = []
    cursor = path
    while not cursor.exists():
        missing.append(cursor)
        cursor = cursor.parent
    for directory in reversed(missing):
        directory.mkdir()
        _fsync_directory(directory.parent, observer)
        _fsync_directory(directory, observer)


def _fsync_directory(
    path: Path, observer: PublicationFailureObserver | None = None
) -> None:
    _observe(observer, "before_directory_fsync")
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    _observe(observer, "after_directory_fsync")


def _write_bytes(
    path: Path,
    content: bytes,
    observer: PublicationFailureObserver | None = None,
    *,
    pointer: bool = False,
) -> None:
    write_before: PublicationBoundary = (
        "before_pointer_write" if pointer else "before_file_write"
    )
    write_after: PublicationBoundary = (
        "after_pointer_write" if pointer else "after_file_write"
    )
    _observe(observer, write_before)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as handle:
        handle.write(content)
        handle.flush()
        _observe(observer, "before_file_fsync")
        os.fsync(handle.fileno())
        _observe(observer, "after_file_fsync")
    _observe(observer, write_after)


def checkpoint_sidecar(
    problem_id: str, checkpoint_id: str, raw_formula_inputs: object
) -> tuple[str, bytes]:
    if not problem_id or not checkpoint_id:
        raise ValueError("problem and checkpoint identifiers are required")
    return (
        str(
            _safe_relative_path(
                f"problems/{problem_id}/checkpoints/{checkpoint_id}.json"
            )
        ),
        canonical_json_bytes(raw_formula_inputs),
    )


def transition_sidecar(
    problem_id: str,
    prior_checkpoint_id: str,
    checkpoint_id: str,
    raw_formula_inputs: object,
) -> tuple[str, bytes]:
    if not problem_id or not prior_checkpoint_id or not checkpoint_id:
        raise ValueError("problem and checkpoint identifiers are required")
    return (
        str(
            _safe_relative_path(
                f"problems/{problem_id}/transitions/{prior_checkpoint_id}--{checkpoint_id}.json"
            )
        ),
        canonical_json_bytes(raw_formula_inputs),
    )


def score_evidence_sidecar(evidence: ScoreEvidenceIndex) -> tuple[str, bytes]:
    """Encode every score formula input as the canonical score sidecar."""
    return _SCORE_EVIDENCE_PATH, canonical_json_bytes(
        evidence.model_dump(mode="json")
    )


def _evidence_kind(path: str) -> str:
    if path == _SCORE_EVIDENCE_PATH:
        return "score_evidence"
    name = Path(path).stem
    if name in {"production_quality", "production_graph"}:
        return name
    if "/transitions/" in path:
        return "transition"
    if "/checkpoints/" in path:
        return "checkpoint"
    return "canonical_evidence"


def freeze_evidence_index(
    sidecars: dict[str, bytes], producers: dict[str, str] | None = None
) -> tuple[EvidenceIndexEntry, ...]:
    producers = producers or {}
    entries = tuple(
        EvidenceIndexEntry(
            path=str(_safe_relative_path(path)),
            kind=_evidence_kind(path),
            byte_length=len(content),
            sha256=_hash(content),
            producer=producers.get(path, "checkpoint-transition"),
        )
        for path, content in sorted(sidecars.items())
    )
    if len({entry.path for entry in entries}) != len(entries):
        raise ValueError("evidence paths must be unique")
    return entries


def aggregate_eligibility(decisions: tuple[Eligibility, ...]) -> Eligibility:
    reasons = tuple(
        sorted(
            {reason for decision in decisions for reason in decision.reasons}
        )
    )
    return Eligibility(eligible=not reasons, reasons=reasons)


def read_verified_evidence(generation_directory: Path) -> dict[str, bytes]:
    try:
        raw_index = (
            generation_directory / EVIDENCE_INDEX_FILENAME
        ).read_bytes()
        decoded = json.loads(raw_index)
        if not isinstance(decoded, list):
            raise ValueError("evidence index must be a JSON array")
        entries = tuple(
            EvidenceIndexEntry.model_validate(item) for item in decoded
        )
        if raw_index != _index_bytes(entries):
            raise ValueError("canonical evidence index bytes are invalid")
    except (OSError, json.JSONDecodeError, ValueError) as error:
        raise ValueError("canonical evidence index is invalid") from error
    if tuple(entry.path for entry in entries) != tuple(
        sorted(entry.path for entry in entries)
    ) or len({entry.path for entry in entries}) != len(entries):
        raise ValueError("canonical evidence index paths are invalid")
    result: dict[str, bytes] = {}
    for entry in entries:
        path = generation_directory / _safe_relative_path(entry.path)
        try:
            content = path.read_bytes()
        except OSError as error:
            raise ValueError(
                f"canonical sidecar missing: {entry.path}"
            ) from error
        if len(content) != entry.byte_length:
            raise ValueError(f"canonical sidecar length mismatch: {entry.path}")
        if _hash(content) != entry.sha256:
            raise ValueError(f"canonical sidecar hash mismatch: {entry.path}")
        result[entry.path] = content
    return result


def _decode_score_evidence(evidence: dict[str, bytes]) -> ScoreEvidenceIndex:
    reasons: set[str] = set()
    raw = evidence.get(_SCORE_EVIDENCE_PATH)
    if raw is None:
        raise ScoreEvidenceError({"score_evidence_invalid"})
    try:
        decoded = json.loads(raw)
        model = ScoreEvidenceIndex.model_validate(decoded)
        if raw != canonical_json_bytes(model.model_dump(mode="json")):
            reasons.add("score_evidence_invalid")
    except (json.JSONDecodeError, ValueError):
        reasons.add("score_evidence_invalid")
        model = None
    if reasons or model is None:
        raise ScoreEvidenceError(reasons or {"score_evidence_invalid"})
    return model


def calculate_scores_from_evidence(
    evidence: dict[str, bytes],
) -> tuple[tuple[ProblemScore, ...], BenchmarkScore]:
    """Pure score calculation from already hash-verified sidecar bytes only."""
    source = _decode_score_evidence(evidence)
    try:
        problems, benchmark = calculate_scores(
            source.problems, source.benchmark
        )
    except ValueError as error:
        raise ScoreEvidenceError({"score_formula_invalid"}) from error
    return problems, benchmark


def load_verified_current_generation_state(
    run_directory: Path,
) -> tuple[GenerationManifest, dict[str, bytes]]:
    """Load any current generation after complete artifact checks."""
    analysis_directory = run_directory / MEASUREMENT_ANALYSIS_DIR
    pointer_path = analysis_directory / CURRENT_POINTER_FILENAME
    try:
        pointer_bytes = pointer_path.read_bytes()
        pointer = json.loads(pointer_bytes)
        generation_id = pointer["generation_id"]
    except (OSError, json.JSONDecodeError, KeyError, TypeError) as exc:
        raise ScoreEvidenceError(
            {"current generation pointer is invalid"}
        ) from exc
    if (
        not isinstance(generation_id, str)
        or not generation_id
        or pointer_bytes
        != canonical_json_bytes({"generation_id": generation_id})
    ):
        raise ScoreEvidenceError({"current generation pointer is invalid"})
    final_directory = analysis_directory / GENERATIONS_DIR / generation_id
    try:
        manifest = _read_manifest(final_directory / MANIFEST_FILENAME)
        manifest = _verify_published(
            final_directory,
            generation_id,
            manifest.entries,
            manifest.eligibility,
        )
        evidence = read_verified_evidence(final_directory)
    except (OSError, ValueError) as exc:
        raise ScoreEvidenceError(
            {"current generation manifest is invalid"}
        ) from exc
    return manifest, evidence


def load_verified_current_generation(
    run_directory: Path,
) -> tuple[BenchmarkScore, tuple[CheckpointReportAddition, ...]]:
    """Load the current eligible generation after complete artifact checks."""
    manifest, _ = load_verified_current_generation_state(run_directory)
    if not manifest.eligibility.eligible or manifest.benchmark is None:
        raise ScoreEvidenceError(set(manifest.eligibility.reasons))
    return manifest.benchmark, manifest.report_additions


def _read_manifest(path: Path) -> GenerationManifest:
    raw = path.read_bytes()
    manifest = GenerationManifest.model_validate_json(raw)
    if raw != canonical_json_bytes(manifest.model_dump(mode="json")):
        raise ValueError(f"canonical artifact bytes are invalid: {path.name}")
    return manifest


def _read_benchmark(path: Path) -> BenchmarkScore:
    raw = path.read_bytes()
    benchmark = BenchmarkScore.model_validate_json(raw)
    if raw != canonical_json_bytes(benchmark.model_dump(mode="json")):
        raise ValueError(f"canonical artifact bytes are invalid: {path.name}")
    return benchmark


def _read_problem(path: Path) -> ProblemScore:
    raw = path.read_bytes()
    problem = ProblemScore.model_validate_json(raw)
    if raw != canonical_json_bytes(problem.model_dump(mode="json")):
        raise ValueError(f"canonical artifact bytes are invalid: {path.name}")
    return problem


def _verify_published(
    final_directory: Path,
    generation_id: str,
    entries: tuple[EvidenceIndexEntry, ...],
    eligibility: Eligibility,
    *,
    allow_obsolete_formula: bool = False,
) -> GenerationManifest:
    manifest_path = final_directory / MANIFEST_FILENAME
    manifest_bytes = manifest_path.read_bytes()
    manifest = _read_manifest(manifest_path)
    index_bytes = (final_directory / EVIDENCE_INDEX_FILENAME).read_bytes()
    status_bytes = (final_directory / PRODUCER_STATUS_FILENAME).read_bytes()
    eligibility_bytes = (final_directory / ELIGIBILITY_FILENAME).read_bytes()
    if (
        _hash(manifest_bytes) != generation_id
        or (final_directory / _READY_FILENAME).read_bytes()
        != f"{generation_id}\n".encode()
        or manifest.schema_id != scoring_schema_id()
        or manifest.entries != entries
        or manifest.eligibility != eligibility
        or manifest.evidence_index_sha256 != _hash(index_bytes)
        or manifest.producer_status_sha256 != _hash(status_bytes)
        or manifest.eligibility_sha256 != _hash(eligibility_bytes)
        or eligibility_bytes
        != canonical_json_bytes(eligibility.model_dump(mode="json"))
    ):
        raise ValueError("published generation manifest is invalid")
    try:
        status_payload = json.loads(status_bytes)
        rows = status_payload["rows"]
        if (
            status_bytes != canonical_json_bytes(status_payload)
            or not isinstance(rows, list)
            or any(
                not isinstance(row, dict)
                or row.get("status") not in {"successful", "blocked"}
                or not isinstance(row.get("producer"), str)
                or not isinstance(row.get("unit"), str)
                or (
                    row.get("status") == "blocked"
                    and not isinstance(row.get("blocked_by"), str)
                )
                or (
                    row.get("status") == "successful"
                    and row.get("blocked_by") is not None
                )
                for row in rows
            )
            or (
                eligibility.eligible
                and any(row.get("status") != "successful" for row in rows)
            )
        ):
            raise ValueError
    except (KeyError, TypeError, json.JSONDecodeError, ValueError) as error:
        raise ValueError("published producer status is invalid") from error
    evidence = read_verified_evidence(final_directory)
    score_source = (
        _decode_score_evidence(evidence)
        if _SCORE_EVIDENCE_PATH in evidence
        else None
    )
    parser_tokenizer_schema_id = (
        score_source.parser_tokenizer_schema_id
        if score_source is not None
        else None
    )
    if (
        manifest.parser_tokenizer_schema_id != parser_tokenizer_schema_id
        or (
            not allow_obsolete_formula
            and manifest.formula_id
            != generation_formula_id(parser_tokenizer_schema_id)
        )
    ):
        raise ValueError("published generation formula identity is invalid")
    expected_paths = {
        EVIDENCE_INDEX_FILENAME,
        PRODUCER_STATUS_FILENAME,
        ELIGIBILITY_FILENAME,
        MANIFEST_FILENAME,
        _READY_FILENAME,
        *(entry.path for entry in entries),
    }
    if eligibility.eligible:
        problems, benchmark = calculate_scores_from_evidence(evidence)
        if (
            manifest.publication_state is not PublicationState.PUBLISHED
            or manifest.benchmark != benchmark
        ):
            raise ValueError("published generation score is invalid")
        for problem in problems:
            path = f"problems/{problem_key(problem.problem_id)}/{PROBLEM_SCORE_FILENAME}"
            if _read_problem(final_directory / path) != problem:
                raise ValueError("published problem score is invalid")
            expected_paths.add(path)
        if (
            _read_benchmark(final_directory / BENCHMARK_SCORE_FILENAME)
            != benchmark
        ):
            raise ValueError("published benchmark score is invalid")
        additions = b"".join(
            canonical_json_bytes(item.model_dump(mode="json")) + b"\n"
            for item in manifest.report_additions
        )
        if (
            final_directory / CHECKPOINT_REPORT_ADDITIONS_FILENAME
        ).read_bytes() != additions:
            raise ValueError("published report additions are invalid")
        expected_paths.update(
            {
                BENCHMARK_SCORE_FILENAME,
                CHECKPOINT_REPORT_ADDITIONS_FILENAME,
            }
        )
    elif (
        manifest.publication_state is not PublicationState.INELIGIBLE
        or manifest.benchmark is not None
        or manifest.report_additions
    ):
        raise ValueError("ineligible generation contains score outputs")
    actual_paths = {
        path.relative_to(final_directory).as_posix()
        for path in final_directory.rglob("*")
        if path.is_file()
    }
    if actual_paths != expected_paths:
        raise ValueError("published generation inventory is invalid")
    return manifest


@contextmanager
def _finalize_lock(
    analysis_directory: Path, observer: PublicationFailureObserver | None = None
):
    import fcntl

    lock_path = analysis_directory / FINALIZE_LOCK_FILENAME
    _mkdir_durable(lock_path.parent, observer)
    with lock_path.open("a+b") as lock:
        _observe(observer, "before_file_fsync")
        os.fsync(lock.fileno())
        _observe(observer, "after_file_fsync")
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(lock.fileno(), fcntl.LOCK_UN)


@contextmanager
def finalize_lock(
    run_directory: Path,
    observer: PublicationFailureObserver | None = None,
):
    """Hold the run finalization lock across all evidence work."""
    analysis_directory = run_directory / MEASUREMENT_ANALYSIS_DIR
    _mkdir_durable(analysis_directory, observer)
    with _finalize_lock(analysis_directory, observer):
        yield


def _replace_durable(
    source: Path,
    destination: Path,
    observer: PublicationFailureObserver | None,
    *,
    before: PublicationBoundary,
    after: PublicationBoundary,
) -> None:
    _observe(observer, before)
    source.replace(destination)
    _observe(observer, after)
    _fsync_directory(destination.parent, observer)


def _cleanup(
    path: Path,
    parent: Path,
    observer: PublicationFailureObserver | None,
    *,
    directory: bool,
) -> None:
    _observe(observer, "before_cleanup")
    if directory:
        shutil.rmtree(path)
    else:
        path.unlink()
    _fsync_directory(parent, observer)
    _observe(observer, "after_cleanup")


def publish_generation(
    run_directory: Path,
    sidecars: dict[str, bytes],
    eligibility: Eligibility,
    *,
    producers: dict[str, str] | None = None,
    producer_status_rows: tuple[dict[str, object], ...] | None = None,
    failure_observer: PublicationFailureObserver | None = None,
    lock_held: bool = False,
    allow_formula_cutover: bool = False,
) -> GenerationManifest:
    """Publish one complete immutable eligible or ineligible generation."""
    analysis_directory = run_directory / MEASUREMENT_ANALYSIS_DIR

    def publish_locked() -> GenerationManifest:
        entries = freeze_evidence_index(sidecars, producers)
        index_bytes = _index_bytes(entries)
        eligibility_bytes = canonical_json_bytes(
            eligibility.model_dump(mode="json")
        )
        rows = producer_status_rows or tuple(
            {
                "producer": entry.producer,
                "unit": entry.path,
                "status": "successful",
                "blocked_by": None,
            }
            for entry in entries
        )
        rows = tuple(
            sorted(
                rows,
                key=lambda row: (
                    str(row.get("producer")),
                    str(row.get("unit")),
                ),
            )
        )
        identities = tuple(
            (row.get("producer"), row.get("unit")) for row in rows
        )
        if (
            len(identities) != len(set(identities))
            or any(
                row.get("status") not in {"successful", "blocked"}
                or not isinstance(row.get("producer"), str)
                or not isinstance(row.get("unit"), str)
                or (
                    row.get("status") == "blocked"
                    and not isinstance(row.get("blocked_by"), str)
                )
                or (
                    row.get("status") == "successful"
                    and row.get("blocked_by") is not None
                )
                for row in rows
            )
            or (
                eligibility.eligible
                and any(row.get("status") != "successful" for row in rows)
            )
        ):
            raise ValueError("producer status matrix is invalid")
        status_bytes = canonical_json_bytes({"rows": rows})
        fingerprint_source = sidecars.get(
            "generation_inputs.json",
            canonical_json_bytes(
                [
                    {
                        "path": entry.path,
                        "byte_length": entry.byte_length,
                        "sha256": entry.sha256,
                    }
                    for entry in entries
                ]
            ),
        )
        input_fingerprint = _hash(fingerprint_source)
        generations = analysis_directory / GENERATIONS_DIR
        _mkdir_durable(generations, failure_observer)
        staging_parent = analysis_directory / STAGING_DIR
        _mkdir_durable(staging_parent, failure_observer)
        staging = staging_parent / f"{os.getpid()}-{uuid.uuid4()}"
        pointer_temporary: Path | None = None
        pointer_bytes: bytes | None = None
        final_directory: Path | None = None
        try:
            _mkdir_durable(staging, failure_observer)
            for path, content in sorted(sidecars.items()):
                target = staging / _safe_relative_path(path)
                _mkdir_durable(target.parent, failure_observer)
                _write_bytes(target, content, failure_observer)
            _write_bytes(
                staging / EVIDENCE_INDEX_FILENAME,
                index_bytes,
                failure_observer,
            )
            _write_bytes(
                staging / PRODUCER_STATUS_FILENAME,
                status_bytes,
                failure_observer,
            )
            _write_bytes(
                staging / ELIGIBILITY_FILENAME,
                eligibility_bytes,
                failure_observer,
            )
            _fsync_directory(staging, failure_observer)
            frozen_sidecars = read_verified_evidence(staging)
            problems: tuple[ProblemScore, ...] = ()
            benchmark: BenchmarkScore | None = None
            if eligibility.eligible:
                problems, benchmark = calculate_scores_from_evidence(
                    frozen_sidecars
                )
            score_source = (
                _decode_score_evidence(frozen_sidecars)
                if _SCORE_EVIDENCE_PATH in frozen_sidecars
                else None
            )
            parser_tokenizer_schema_id = (
                score_source.parser_tokenizer_schema_id
                if score_source is not None
                else None
            )
            score_by_problem = {
                problem.problem_id: problem for problem in problems
            }
            report_additions = (
                tuple(
                    CheckpointReportAddition(
                        problem_key=problem_key(item.problem_id),
                        problem_name=item.problem_id,
                        checkpoint_id=checkpoint_id,
                        checkpoint_index=index,
                        correctness=item.checkpoint_correctness[index].rate,
                        verbosity=item.verbosity[index],
                        erosion=item.erosion[index],
                        architecture=item.architecture[index],
                        rework=None if index == 0 else item.rework[index - 1],
                        regression=None
                        if index == 0
                        else item.regression[index - 1],
                        problem_components=score_by_problem[
                            item.problem_id
                        ].components,
                        problem_score=score_by_problem[item.problem_id].score,
                    )
                    for item in score_source.problems
                    for index, checkpoint_id in enumerate(item.checkpoint_ids)
                )
                if score_source is not None and benchmark is not None
                else ()
            )
            manifest = GenerationManifest(
                kind="benchmark_score_generation",
                schema_id=scoring_schema_id(),
                formula_id=generation_formula_id(parser_tokenizer_schema_id),
                parser_tokenizer_schema_id=parser_tokenizer_schema_id,
                input_fingerprint=input_fingerprint,
                entries=entries,
                eligibility=eligibility,
                publication_state=(
                    PublicationState.PUBLISHED
                    if eligibility.eligible
                    else PublicationState.INELIGIBLE
                ),
                evidence_index_sha256=_hash(index_bytes),
                producer_status_sha256=_hash(status_bytes),
                eligibility_sha256=_hash(eligibility_bytes),
                benchmark=benchmark,
                report_additions=report_additions,
            )
            manifest_bytes = canonical_json_bytes(
                manifest.model_dump(mode="json")
            )
            generation_id = _hash(manifest_bytes)
            final_directory = generations / generation_id
            pointer_bytes = canonical_json_bytes(
                {"generation_id": generation_id}
            )
            current_pointer = analysis_directory / CURRENT_POINTER_FILENAME
            if current_pointer.is_file():
                try:
                    current_payload = json.loads(current_pointer.read_bytes())
                    current_id = current_payload["generation_id"]
                    current_directory = generations / current_id
                    if current_directory.is_dir():
                        try:
                            current_manifest, _ = (
                                load_verified_current_generation_state(
                                    run_directory
                                )
                            )
                        except ScoreEvidenceError:
                            if not allow_formula_cutover:
                                raise
                            try:
                                obsolete = _read_manifest(
                                    current_directory / MANIFEST_FILENAME
                                )
                                current_manifest = _verify_published(
                                    current_directory,
                                    current_id,
                                    obsolete.entries,
                                    obsolete.eligibility,
                                    allow_obsolete_formula=True,
                                )
                            except (OSError, ValueError) as error:
                                raise ScoreEvidenceError(
                                    {
                                        "current generation manifest "
                                        "is invalid"
                                    }
                                ) from error
                        same_formula = (
                            current_manifest.formula_id == manifest.formula_id
                        )
                        if (
                            same_formula
                            and current_manifest.eligibility.eligible
                            and not eligibility.eligible
                        ):
                            raise ValueError(
                                "eligible generation cannot degrade"
                            )
                        if (
                            same_formula
                            and current_manifest.input_fingerprint
                            == input_fingerprint
                            and current_id != generation_id
                        ):
                            raise ValueError(
                                "identical input fingerprint changed output"
                            )
                except (
                    KeyError,
                    TypeError,
                    json.JSONDecodeError,
                    ScoreEvidenceError,
                ) as error:
                    raise ValueError("current generation is corrupt") from error
            if final_directory.exists():
                verified = _verify_published(
                    final_directory,
                    generation_id,
                    entries,
                    eligibility,
                )
                pointer = analysis_directory / CURRENT_POINTER_FILENAME
                if (
                    not pointer.exists()
                    or pointer.read_bytes() != pointer_bytes
                ):
                    pointer_temporary = (
                        analysis_directory
                        / f".current-{os.getpid()}-{uuid.uuid4()}"
                    )
                    _write_bytes(
                        pointer_temporary,
                        pointer_bytes,
                        failure_observer,
                        pointer=True,
                    )
                    _replace_durable(
                        pointer_temporary,
                        pointer,
                        failure_observer,
                        before="before_pointer_rename",
                        after="after_pointer_rename",
                    )
                    pointer_temporary = None
                _cleanup(
                    staging,
                    staging_parent,
                    failure_observer,
                    directory=True,
                )
                return verified
            if benchmark is not None:
                for problem in problems:
                    _write_bytes(
                        staging
                        / "problems"
                        / problem_key(problem.problem_id)
                        / PROBLEM_SCORE_FILENAME,
                        canonical_json_bytes(problem.model_dump(mode="json")),
                        failure_observer,
                    )
                _write_bytes(
                    staging / BENCHMARK_SCORE_FILENAME,
                    canonical_json_bytes(benchmark.model_dump(mode="json")),
                    failure_observer,
                )
                additions_bytes = b"".join(
                    canonical_json_bytes(addition.model_dump(mode="json"))
                    + b"\n"
                    for addition in report_additions
                )
                _write_bytes(
                    staging / CHECKPOINT_REPORT_ADDITIONS_FILENAME,
                    additions_bytes,
                    failure_observer,
                )
            _write_bytes(
                staging / MANIFEST_FILENAME,
                manifest_bytes,
                failure_observer,
            )
            _write_bytes(
                staging / _READY_FILENAME,
                f"{generation_id}\n".encode(),
                failure_observer,
            )
            _fsync_directory(staging, failure_observer)
            _replace_durable(
                staging,
                final_directory,
                failure_observer,
                before="before_generation_rename",
                after="after_generation_rename",
            )
            _verify_published(
                final_directory, generation_id, entries, eligibility
            )
            pointer_temporary = (
                analysis_directory / f".current-{os.getpid()}-{uuid.uuid4()}"
            )
            _write_bytes(
                pointer_temporary,
                pointer_bytes,
                failure_observer,
                pointer=True,
            )
            _replace_durable(
                pointer_temporary,
                analysis_directory / CURRENT_POINTER_FILENAME,
                failure_observer,
                before="before_pointer_rename",
                after="after_pointer_rename",
            )
            pointer_temporary = None
            return manifest
        except BaseException:
            if staging.exists():
                _cleanup(
                    staging,
                    staging_parent,
                    failure_observer,
                    directory=True,
                )
            if pointer_temporary is not None and pointer_temporary.exists():
                _cleanup(
                    pointer_temporary,
                    analysis_directory,
                    failure_observer,
                    directory=False,
                )
            raise

    _mkdir_durable(analysis_directory, failure_observer)
    if lock_held:
        return publish_locked()
    with _finalize_lock(analysis_directory, failure_observer):
        return publish_locked()
