"""Finalization-only locked regression measurement for live runs."""

from __future__ import annotations

import hashlib
import json
import shutil
import tempfile
from collections import defaultdict
from collections.abc import Iterable
from collections.abc import Mapping
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from slop_code import common
from slop_code.common import ENV_CONFIG_NAME
from slop_code.common.constants import HISTORICAL_PROVENANCE_DIR
from slop_code.common.constants import MEASUREMENT_ANALYSIS_DIR
from slop_code.common.constants import PENDING_ORACLES_DIR
from slop_code.entrypoints.config.loader import resolve_environment
from slop_code.evaluation import CheckpointConfig
from slop_code.evaluation import CorrectnessResults
from slop_code.evaluation import GroupType
from slop_code.evaluation import ProblemConfig
from slop_code.evaluation import run_checkpoint_pytest

from .inventory import build_inventory
from .live_evidence import _changed_lines
from .live_evidence import _committed_artifacts
from .models import CorpusEvidence
from .models import CoverageContextEvidence
from .models import Eligibility
from .models import EvaluatorEnvironmentEvidence
from .models import FileRole
from .models import LineageCandidate
from .models import RegressionBreadthInput
from .models import RegressionInvocationEvidence
from .models import RegressionLedgerEvidence
from .models import RegressionOutcomeEvidence
from .models import RegressionRunEvidence
from .models import SymbolIdentity
from .regression import calculate_regression_breadth
from .schema import problem_key


def _canonical(value: object) -> bytes:
    return json.dumps(
        value, ensure_ascii=True, separators=(",", ":"), sort_keys=True
    ).encode()


def _validate_live_oracle(
    run_dir: Path,
    checkpoint_dir: Path,
    checkpoint_id: str,
    problem: ProblemConfig,
) -> dict[str, Any]:
    """Require every saved artifact and canonical parity record."""
    artifacts = _committed_artifacts(checkpoint_dir, checkpoint_id, problem)
    expected = {
        common.EVALUATION_FILENAME,
        f"{common.QUALITY_DIR}/{common.QUALITY_METRIC_SAVENAME}",
        f"{common.QUALITY_DIR}/{common.FILES_QUALITY_SAVENAME}",
        f"{common.QUALITY_DIR}/{common.SYMBOLS_QUALITY_SAVENAME}",
    }
    if set(artifacts) != expected:
        raise ValueError("canonical_provenance_unavailable")
    problem_key = hashlib.sha256(problem.name.encode("utf-8")).hexdigest()
    oracle_dir = (
        run_dir
        / MEASUREMENT_ANALYSIS_DIR
        / "pending"
        / problem_key
        / checkpoint_id
        / PENDING_ORACLES_DIR
    )
    candidates = sorted(oracle_dir.glob("*.json"))
    if len(candidates) != 1:
        raise ValueError("canonical_provenance_unavailable")
    payload = json.loads(candidates[0].read_bytes())
    parity = payload.get("canonical_parity")
    if not isinstance(parity, dict):
        raise ValueError("canonical_provenance_unavailable")
    return parity


def _group_by_ledger_node(
    tests: Sequence[Any], ledger_nodes: set[str]
) -> dict[str, str] | None:
    """Resolve report identifiers to the canonical coverage-ledger nodes."""
    group_by_node: dict[str, str] = {}
    for test in tests:
        test_id = test.id
        if not isinstance(test_id, str):
            return None
        if test_id in ledger_nodes:
            matches = (test_id,)
        else:
            file_path = test.file_path
            projected = (
                f"{file_path}::{test_id}"
                if isinstance(file_path, str) and file_path
                else ""
            )
            if projected in ledger_nodes:
                matches = (projected,)
            else:
                suffix = f"::{test_id}"
                matches = tuple(
                    node for node in ledger_nodes if node.endswith(suffix)
                )
        if len(matches) != 1:
            return None
        node_id = matches[0]
        group = test.group_type.value
        existing = group_by_node.get(node_id)
        if existing is not None and existing != group:
            return None
        group_by_node[node_id] = group
    if set(group_by_node) != ledger_nodes:
        return None
    return group_by_node


def _run_evidence(
    results: Any,
    *,
    platform_identity: dict[str, str],
) -> RegressionRunEvidence | None:
    """Project one locked evaluator execution; absent provenance is ineligible."""
    metadata = results.evaluator_environment
    ledger = results.coverage_ledger
    corpus = results.test_corpus
    invocation = results.invocation
    environment_fingerprint = results.environment_fingerprint
    if (
        not isinstance(metadata, dict)
        or not isinstance(ledger, dict)
        or not isinstance(corpus, dict)
        or not isinstance(invocation, dict)
        or not isinstance(environment_fingerprint, str)
    ):
        return None
    inputs = metadata.get("input_sha256")
    environment_id = metadata.get("environment_id")
    if not isinstance(inputs, dict) or not isinstance(environment_id, str):
        return None
    try:
        environment = EvaluatorEnvironmentEvidence(
            environment_id=environment_id,
            project_sha256=inputs["pyproject.toml"],
            lock_sha256=inputs["uv.lock"],
            plugin_sha256=inputs["coverage_plugin.py"],
            interpreter_sha256=inputs["interpreter"],
            platform_sha256=hashlib.sha256(
                _canonical(platform_identity)
            ).hexdigest(),
        )
        if ledger.get("invalid_coverage_paths", 0) != 0:
            return None
        raw_ledger = ledger["ledger"]
        raw_coverage = ledger["coverage"]
        raw_events = ledger.get("process_events", [])
        ledger_nodes = {row["node_id"] for row in raw_ledger}
        group_by_node = _group_by_ledger_node(results.tests, ledger_nodes)
        if group_by_node is None:
            return None
        regression_nodes = {
            node
            for node, group in group_by_node.items()
            if group == GroupType.REGRESSION.value
        }
        by_coverage: dict[tuple[str, str], set[int]] = defaultdict(set)
        for row in raw_coverage:
            if row["node_id"] in regression_nodes:
                by_coverage[(row["node_id"], row["path"])].add(
                    row["executed_line"]
                )
        entries = tuple(
            RegressionLedgerEvidence.model_validate(row) for row in raw_ledger
        )
        outcomes = tuple(
            RegressionOutcomeEvidence(
                node_id=row.node_id,
                group_type=group_by_node[row.node_id],
                phase=row.phase,
                outcome=row.outcome,
            )
            for row in entries
        )
        corpus_sha256 = corpus["manifest_sha256"]
        command = invocation["command"]
        cwd = invocation["cwd"]
        if not all(
            isinstance(value, str) for value in (corpus_sha256, command, cwd)
        ):
            return None
        return RegressionRunEvidence(
            environment=environment,
            corpus=CorpusEvidence(
                corpus_id=environment_fingerprint,
                manifest_sha256=corpus_sha256,
            ),
            invocation=RegressionInvocationEvidence(argv=(command,), cwd=cwd),
            outcomes=outcomes,
            ledger=entries,
            coverage=tuple(
                CoverageContextEvidence(
                    node_id=node,
                    path=path,
                    executed_lines=tuple(sorted(lines)),
                )
                for (node, path), lines in sorted(by_coverage.items())
            ),
            process_events=tuple(raw_events),
        )
    except (KeyError, TypeError, ValueError):
        return None


def _artifact_digest(checkpoint_dir: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(checkpoint_dir.rglob("*")):
        if path.is_file() and "snapshot" not in path.parts:
            digest.update(path.relative_to(checkpoint_dir).as_posix().encode())
            digest.update(b"\0")
            digest.update(path.read_bytes())
    return digest.hexdigest()


def _current_production_symbols(
    checkpoint_dir: Path,
    *,
    generated_globs: Iterable[str] = (),
    test_globs: Iterable[str] = (),
) -> tuple[SymbolIdentity, ...]:
    """Load canonical current production identities from saved quality rows."""
    snapshot = checkpoint_dir / common.SNAPSHOT_DIR_NAME
    production_paths = {
        item.path
        for item in build_inventory(
            snapshot,
            generated_globs=generated_globs,
            test_globs=test_globs,
        ).files
        if item.role == FileRole.PRODUCTION
    }
    rows_path = (
        checkpoint_dir / common.QUALITY_DIR / common.SYMBOLS_QUALITY_SAVENAME
    )
    rows = (
        json.loads(line) for line in rows_path.read_text().splitlines() if line
    )
    identities: dict[
        tuple[str, str, str, str, str, int, int], SymbolIdentity
    ] = {}
    for row in rows:
        if row["file_path"] not in production_paths or row["type"] not in {
            "function",
            "method",
        }:
            continue
        symbol = SymbolIdentity(
            path=row["file_path"],
            qualified_name=row["name"],
            kind=row["type"],
            start_line=row["start"],
            end_line=row["end"],
            parent_qualified_name=row.get("parent_class") or "",
            body_sha256=row.get("body_hash") or "",
            structure_sha256=row.get("structure_hash") or "",
            signature_sha256=row.get("signature_hash") or "",
        )
        identities[symbol.stable_identity] = symbol
    return tuple(
        sorted(identities.values(), key=lambda item: item.stable_identity)
    )


def _changed_production_symbols(
    prior_dir: Path,
    current_dir: Path,
    *,
    generated_globs: Iterable[str] = (),
    test_globs: Iterable[str] = (),
) -> tuple[SymbolIdentity, ...]:
    """Map exact snapshot additions to one innermost canonical current symbol."""
    prior_snapshot = prior_dir / common.SNAPSHOT_DIR_NAME
    current_snapshot = current_dir / common.SNAPSHOT_DIR_NAME
    prior_paths = {
        item.path
        for item in build_inventory(
            prior_snapshot,
            generated_globs=generated_globs,
            test_globs=test_globs,
        ).files
        if item.role == FileRole.PRODUCTION
    }
    symbols = _current_production_symbols(
        current_dir,
        generated_globs=generated_globs,
        test_globs=test_globs,
    )
    _, added = _changed_lines(
        prior_snapshot,
        current_snapshot,
        (*prior_paths, *(symbol.path for symbol in symbols)),
    )
    changed: dict[tuple[str, str, str, str, str, int, int], SymbolIdentity] = {}
    for line in added:
        matches = [
            symbol
            for symbol in symbols
            if symbol.path == line.path
            and symbol.start_line <= line.line <= symbol.end_line
        ]
        if matches:
            symbol = max(
                matches,
                key=lambda candidate: (
                    candidate.start_line,
                    -candidate.end_line,
                    candidate.stable_identity,
                ),
            )
            changed[symbol.stable_identity] = symbol
    return tuple(
        sorted(changed.values(), key=lambda item: item.stable_identity)
    )


def _accepted_changed_current_symbols(
    lineage_sidecars: Mapping[str, bytes],
    lineage_path: str,
) -> tuple[SymbolIdentity, ...]:
    """Load changed current endpoints from accepted production lineages."""
    payload = json.loads(lineage_sidecars[lineage_path])
    changed: dict[tuple[str, str, str, str, str, int, int], SymbolIdentity] = {}
    for raw in payload["lineage_candidates"]:
        candidate = LineageCandidate.model_validate(raw)
        if not candidate.accepted:
            continue
        if (
            candidate.prior.exact_identity == candidate.current.exact_identity
            and candidate.body_hash_equal
            and candidate.structure_hash_equal
            and candidate.signature_hash_equal
        ):
            continue
        changed[candidate.current.stable_identity] = candidate.current
    return tuple(
        sorted(changed.values(), key=lambda item: item.stable_identity)
    )


def _historical_checkpoint_parity(
    bundle_path: Path,
    problem: ProblemConfig,
    checkpoint_id: str,
) -> dict[str, object] | None:
    content = bundle_path.read_bytes()
    if bundle_path.stem != hashlib.sha256(content).hexdigest():
        return None
    payload = json.loads(content)
    if (
        payload.get("kind") != "historical_provenance_bundle"
        or payload.get("source_type") != "historical"
    ):
        return None
    problems = [
        row
        for row in payload.get("problems", ())
        if row.get("problem_id") == problem.name
    ]
    if (
        len(problems) != 1
        or problems[0].get("config_observation") != "recorded_at_run"
        or problems[0].get("config") != problem.model_dump(mode="json")
    ):
        return None
    checkpoints = [
        row
        for row in problems[0].get("checkpoints", ())
        if row.get("checkpoint_id") == checkpoint_id
    ]
    if len(checkpoints) != 1:
        return None
    evaluations = [
        artifact
        for artifact in checkpoints[0].get("artifacts", ())
        if artifact.get("path") == common.EVALUATION_FILENAME
    ]
    if len(evaluations) != 1:
        return None
    recorded = evaluations[0].get("recorded_at_run")
    if not isinstance(recorded, dict):
        return None
    parity: dict[str, object] = {
        "coverage_ledger": recorded.get("coverage_ledger"),
        "environment_fingerprint": recorded.get("environment_fingerprint"),
        "evaluator_environment": recorded.get("evaluator_environment"),
        "invocation": recorded.get("invocation"),
        "platform": recorded.get("platform_identity"),
        "test_collection_hash": recorded.get("test_collection_hash"),
        "test_corpus": recorded.get("test_corpus"),
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
        return None
    return parity


def produce_live_regression_evidence(
    run_dir: Path,
    problem_configs: Sequence[ProblemConfig],
    required_transitions: set[tuple[str, str, str]] | None = None,
    *,
    lineage_sidecars: Mapping[str, bytes] | None = None,
) -> tuple[dict[str, bytes], Eligibility]:
    """Measure only transitions with committed live inputs and real provenance."""
    sidecars: dict[str, bytes] = {}
    historical = sorted(
        (run_dir / MEASUREMENT_ANALYSIS_DIR / HISTORICAL_PROVENANCE_DIR).glob(
            "*.json"
        )
    )
    if len(historical) > 1:
        return sidecars, Eligibility(
            eligible=False, reasons=("canonical_artifact_invalid",)
        )
    targets: list[
        tuple[
            ProblemConfig,
            str,
            CheckpointConfig,
            str,
            CheckpointConfig,
            dict[str, object],
        ]
    ] = []
    for problem in problem_configs:
        if not isinstance(problem, ProblemConfig):
            return {}, Eligibility(
                eligible=False, reasons=("canonical_provenance_unavailable",)
            )
        checkpoints = tuple(problem.iterate_checkpoint_items())
        for (prior_id, prior), (current_id, current) in zip(
            checkpoints, checkpoints[1:], strict=False
        ):
            transition = (problem.name, prior_id, current_id)
            if (
                required_transitions is not None
                and transition not in required_transitions
            ):
                continue
            prior_dir = run_dir / problem.name / prior_id
            current_dir = run_dir / problem.name / current_id
            if (
                not (prior_dir / common.INFERENCE_RESULT_FILENAME).is_file()
                or not (
                    current_dir / common.INFERENCE_RESULT_FILENAME
                ).is_file()
            ):
                prefix = (
                    f"problems/{problem_key(problem.name)}/transitions/"
                    f"{prior_id}--{current_id}"
                )
                sidecars[f"{prefix}/regression.json"] = _canonical(
                    {"regression": "0"}
                )
                continue
            if historical:
                canonical_problem_key = problem_key(problem.name)
                live = (
                    run_dir
                    / MEASUREMENT_ANALYSIS_DIR
                    / "pending"
                    / canonical_problem_key
                    / current_id
                    / PENDING_ORACLES_DIR
                )
                if any(live.glob("*.json")):
                    return sidecars, Eligibility(
                        eligible=False,
                        reasons=("canonical_artifact_invalid",),
                    )
                try:
                    prior_parity = _historical_checkpoint_parity(
                        historical[0], problem, prior_id
                    )
                    current_parity = _historical_checkpoint_parity(
                        historical[0], problem, current_id
                    )
                except (OSError, json.JSONDecodeError):
                    prior_parity = current_parity = None
                if prior_parity is None or current_parity is None:
                    return sidecars, Eligibility(
                        eligible=False,
                        reasons=(
                            "canonical_provenance_unavailable",
                            "coverage_parity_unavailable",
                        ),
                    )
                targets.append(
                    (
                        problem,
                        prior_id,
                        prior,
                        current_id,
                        current,
                        current_parity,
                    )
                )
                continue
            try:
                _validate_live_oracle(run_dir, prior_dir, prior_id, problem)
                canonical_parity = _validate_live_oracle(
                    run_dir, current_dir, current_id, problem
                )
            except ValueError as error:
                code = str(error)
                return sidecars, Eligibility(
                    eligible=False,
                    reasons=(
                        (
                            code
                            if code
                            in {
                                "canonical_artifact_invalid",
                                "canonical_provenance_unavailable",
                            }
                            else "canonical_artifact_invalid"
                        ),
                    ),
                )
            except (OSError, json.JSONDecodeError):
                return sidecars, Eligibility(
                    eligible=False,
                    reasons=("canonical_provenance_unavailable",),
                )
            targets.append(
                (
                    problem,
                    prior_id,
                    prior,
                    current_id,
                    current,
                    canonical_parity,
                )
            )
    if not targets:
        return sidecars, Eligibility(eligible=True)
    try:
        environment = resolve_environment(run_dir / ENV_CONFIG_NAME)
    except (OSError, ValueError):
        return sidecars, Eligibility(
            eligible=False, reasons=("canonical_provenance_unavailable",)
        )
    reasons: set[str] = set()
    for (
        problem,
        prior_id,
        prior,
        current_id,
        current,
        canonical_parity,
    ) in targets:
        prior_dir = run_dir / problem.name / prior_id
        current_dir = run_dir / problem.name / current_id
        prior_digest = _artifact_digest(prior_dir)
        current_digest = _artifact_digest(current_dir)
        canonical_result = CorrectnessResults.from_dir(current_dir)
        with tempfile.TemporaryDirectory(
            prefix="slop-code-regression-"
        ) as temporary:
            measurement_snapshot = Path(temporary) / common.SNAPSHOT_DIR_NAME
            shutil.copytree(
                current_dir / common.SNAPSHOT_DIR_NAME,
                measurement_snapshot,
                symlinks=True,
            )
            measurement_result = run_checkpoint_pytest(
                measurement_snapshot,
                problem,
                current,
                environment,
                evaluator_environment_parent=(
                    run_dir / MEASUREMENT_ANALYSIS_DIR
                ),
                measurement_coverage=True,
            )
        raw_platform_identity = canonical_parity.get("platform")
        if not isinstance(raw_platform_identity, dict) or any(
            not isinstance(key, str) or not isinstance(value, str)
            for key, value in raw_platform_identity.items()
        ):
            reasons.add("coverage_parity_unavailable")
            continue
        platform_identity = {
            key: value
            for key, value in raw_platform_identity.items()
            if isinstance(key, str) and isinstance(value, str)
        }
        raw_measurement_platform = measurement_result.platform_identity
        if not isinstance(raw_measurement_platform, dict) or any(
            not isinstance(key, str) or not isinstance(value, str)
            for key, value in raw_measurement_platform.items()
        ):
            reasons.add("coverage_parity_unavailable")
            continue
        measurement_platform = {
            key: value
            for key, value in raw_measurement_platform.items()
            if isinstance(key, str) and isinstance(value, str)
        }
        baseline = _run_evidence(
            canonical_result, platform_identity=platform_identity
        )
        produced = _run_evidence(
            measurement_result,
            platform_identity=measurement_platform,
        )
        if prior_digest != _artifact_digest(
            prior_dir
        ) or current_digest != _artifact_digest(current_dir):
            raise RuntimeError(
                "locked regression measurement altered canonical artifacts"
            )
        if baseline is None or produced is None:
            reasons.add("coverage_parity_unavailable")
            continue
        try:
            changed_symbols = _changed_production_symbols(
                prior_dir,
                current_dir,
                generated_globs=problem.measurement_generated_globs,
                test_globs=problem.measurement_test_globs,
            )
            lineage_path = (
                f"problems/{problem_key(problem.name)}/transitions/"
                f"{prior_id}--{current_id}/lineage.json"
            )
            if (
                lineage_sidecars is not None
                and lineage_path in lineage_sidecars
            ):
                accepted = _accepted_changed_current_symbols(
                    lineage_sidecars, lineage_path
                )
                changed_symbols = tuple(
                    sorted(
                        {
                            symbol.stable_identity: symbol
                            for symbol in (*changed_symbols, *accepted)
                        }.values(),
                        key=lambda item: item.stable_identity,
                    )
                )
        except (
            KeyError,
            OSError,
            TypeError,
            UnicodeError,
            ValueError,
            json.JSONDecodeError,
        ):
            reasons.add("coverage_parity_unavailable")
            continue
        attribution = calculate_regression_breadth(
            RegressionBreadthInput(
                transition_id=f"{prior_id}--{current_id}",
                baseline=baseline,
                produced=produced,
                changed_symbols=changed_symbols,
            )
        )
        prefix = (
            f"problems/{problem_key(problem.name)}/transitions/"
            f"{prior_id}--{current_id}"
        )
        sidecars[f"{prefix}/regression_attribution.json"] = _canonical(
            attribution.model_dump(mode="json")
        )
        if attribution.regression is None:
            reasons.update(attribution.eligibility.reasons)
        else:
            sidecars[f"{prefix}/regression.json"] = _canonical(
                {"regression": str(attribution.regression)}
            )
    if reasons:
        return sidecars, Eligibility(
            eligible=False, reasons=tuple(sorted(reasons))
        )
    return sidecars, Eligibility(eligible=True)
