from __future__ import annotations

import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

import yaml
from pydantic import BaseModel
from pydantic import ValidationError
from rich import box
from rich.console import Console
from rich.table import Table

from slop_code import common
from slop_code.agent_runner import ProviderCatalog
from slop_code.common.constants import CURRENT_POINTER_FILENAME
from slop_code.common.constants import MEASUREMENT_ANALYSIS_DIR
from slop_code.common.llms import ModelCatalog
from slop_code.common.llms import ModelDefinition
from slop_code.evaluation import CheckpointConfig
from slop_code.evaluation import ConfigError
from slop_code.evaluation import ProblemConfig
from slop_code.logging import get_logger
from slop_code.metrics import RunSummary
from slop_code.metrics import compute_run_summary
from slop_code.metrics import load_checkpoint_data
from slop_code.metrics import save_summary_json
from slop_code.metrics.scoring import ScoreEvidenceError
from slop_code.metrics.scoring import load_verified_current_generation_state

EXPERIMENT_SUMMARY_FILENAME = "experiment_summary.txt"

logger = get_logger(__name__)


class CLIContext(BaseModel):
    verbosity: int
    seed: int
    scbench_home: Path
    overwrite: bool
    debug: bool
    snapshot_dir_name: str
    quiet: bool = False


class CLIError(Exception):
    """Exception raised by the CLI."""


@dataclass(frozen=True)
class ModelOverride:
    """Parsed model specification from CLI in {provider}/{model} format.

    Attributes:
        model_def: The ModelDefinition from the catalog
        provider: The credential provider (e.g., "anthropic")
    """

    model_def: ModelDefinition
    provider: str

    @property
    def name(self) -> str:
        """Registered model name (config filename)."""
        return self.model_def.name

    @property
    def internal_name(self) -> str:
        """API model identifier."""
        return self.model_def.internal_name


def ensure_dir_exists(path: Path, *, create: bool = False) -> Path:
    logger.debug(
        "Ensuring directory exists", path=path, create=create, verbose=True
    )
    if not path.exists():
        if create:
            path.mkdir(parents=True, exist_ok=True)
            return path
        raise FileNotFoundError(f"{path} does not exist")

    if not path.is_dir():
        raise FileNotFoundError(f"Path {path} is not a directory")
    return path


def ensure_file_exists(path: Path) -> Path:
    logger.debug("Ensuring file exists", path=path, verbose=True)
    if not path.exists():
        raise FileNotFoundError(f"{path} does not exist")
    if not path.is_file():
        raise FileNotFoundError(f"Path {path} is not a file")
    return path


def ensure_at_least_one_file_exists(*paths: Path) -> Path:
    logger.debug("Ensuring at least one file exists", paths=paths, verbose=True)
    for path in paths:
        if path.exists():
            return path
    raise FileNotFoundError(f"No files exist in {paths}")


def parse_model_override(raw_value: str) -> ModelOverride:
    """Parse a CLI model specification of the form '{provider}/{model}'.

    Both provider and model are required.

    Args:
        raw_value: The raw CLI value in '{provider}/{model}' format.

    Returns:
        ModelOverride with provider and model.

    Raises:
        ValueError: If the format is invalid or provider is unknown.
    """
    value = raw_value.strip()
    if not value:
        raise ValueError("Model specification cannot be empty")

    if "/" not in value:
        raise ValueError(
            f"Model must be in '{{provider}}/{{model}}' format. Got: '{value}'"
        )

    provider, model = value.split("/", 1)
    provider = provider.strip()
    model = model.strip()

    if not provider:
        raise ValueError(
            "Provider cannot be empty. Use '{provider}/{model}' format."
        )
    if not model:
        raise ValueError(
            "Model name cannot be empty. Use '{provider}/{model}' format."
        )

    # Validate provider exists
    ProviderCatalog.ensure_loaded()
    if ProviderCatalog.get(provider) is None:
        available = ", ".join(ProviderCatalog.list_providers())
        raise ValueError(
            f"Unknown provider '{provider}'. "
            f"Known providers: {available or 'none'}."
        )

    canonical_model = ModelCatalog.resolve_canonical(model)

    # Validate model exists in catalog
    model_def = ModelCatalog.get(canonical_model)
    if model_def is None:
        available = ModelCatalog.list_models()
        if len(available) > 10:
            models_str = ", ".join(available[:10]) + "..."
        else:
            models_str = ", ".join(available) if available else "none"
        raise ValueError(f"Unknown model '{model}'. Known models: {models_str}")

    return ModelOverride(model_def=model_def, provider=provider)


def load_problem_from_snapshot_dir(
    snapshot_dir: Path,
) -> tuple[Path, ProblemConfig, CheckpointConfig] | None:
    logger.info(
        "Loading problem from snapshot directory", snapshot_dir=snapshot_dir
    )
    chkpt_dir = snapshot_dir.parent.name
    problem_dir = snapshot_dir.parents[1]
    logger.debug(
        "Checkpoint directory", chkpt_dir=chkpt_dir, problem_dir=problem_dir
    )
    if not (problem_dir / "problem.yaml").exists():
        logger.info("Problem directory not found", problem_dir=problem_dir)
        return None
    with (problem_dir / "problem.yaml").open() as f:
        problem_config = ProblemConfig.model_validate(yaml.safe_load(f))
    checkpoint_config = problem_config.checkpoints[chkpt_dir]
    return problem_dir, problem_config, checkpoint_config


def discover_problems(run_dir: Path) -> list[Path]:
    """Discover problem directories in a run directory.

    A problem directory is identified by containing checkpoint_* subdirectories.

    Args:
        run_dir: Path to the run directory.

    Returns:
        List of paths to problem directories, sorted by name.
    """
    problems: list[Path] = []

    for child in run_dir.iterdir():
        if not child.is_dir():
            continue

        # Check if this directory contains checkpoint_* subdirectories
        has_checkpoints = any(
            subdir.is_dir() and subdir.name.startswith("checkpoint_")
            for subdir in child.iterdir()
        )
        if has_checkpoints:
            problems.append(child)

    return sorted(problems)


def discover_run_directories(collection_dir: Path) -> list[Path]:
    """Discover run directories by finding config.yaml files with 'agent' field.

    A run directory is identified by containing a config.yaml file that has
    an 'agent' key at the top level.

    Args:
        collection_dir: Path to search for run directories.

    Returns:
        Sorted list of valid run directory paths.
    """
    run_dirs: list[Path] = []

    for config_file in collection_dir.rglob(common.CONFIG_FILENAME):
        # Skip snapshot directories (problem test data)
        if "snapshot" in config_file.parts:
            continue

        try:
            with config_file.open() as f:
                config_data = yaml.safe_load(f)

            if isinstance(config_data, dict) and "agent" in config_data:
                run_dirs.append(config_file.parent)
        except (yaml.YAMLError, OSError):
            continue

    return sorted(run_dirs)


def discover_checkpoints(problem_dir: Path) -> list[Path]:
    """Discover checkpoint directories in a problem directory.

    Args:
        problem_dir: Path to the problem directory.

    Returns:
        List of paths to checkpoint directories, sorted by checkpoint number.
    """
    checkpoint_pattern = re.compile(r"^checkpoint_(\d+)$")
    checkpoints: list[tuple[int, Path]] = []

    for child in problem_dir.iterdir():
        if not child.is_dir():
            continue

        match = checkpoint_pattern.match(child.name)
        if match:
            checkpoint_num = int(match.group(1))
            checkpoints.append((checkpoint_num, child))

    # Sort by checkpoint number
    checkpoints.sort(key=lambda x: x[0])
    return [path for _, path in checkpoints]


def _verified_score_projection(
    run_dir: Path, checkpoint_keys: set[tuple[str, str]]
) -> dict[str, object] | None:
    """Return the verified canonical score projection for saved checkpoints."""
    try:
        manifest, evidence = load_verified_current_generation_state(run_dir)
        benchmark = manifest.benchmark
        if not manifest.eligibility.eligible or benchmark is None:
            raise ScoreEvidenceError(set(manifest.eligibility.reasons))
        pointer = json.loads(
            (
                run_dir
                / MEASUREMENT_ANALYSIS_DIR
                / CURRENT_POINTER_FILENAME
            ).read_bytes()
        )
        generation_id = pointer["generation_id"]
        evaluator_identities = {
            json.dumps(
                json.loads(payload)["interpreter"],
                sort_keys=True,
                separators=(",", ":"),
            )
            for path, payload in evidence.items()
            if path.endswith("/production_quality.json")
        }
        if len(evaluator_identities) > 1:
            raise ScoreEvidenceError({"measurement_environment_mismatch"})
        if evaluator_identities:
            raw_evaluator_identity = json.loads(
                next(iter(evaluator_identities))
            )
            evaluator_identity = {
                field: raw_evaluator_identity[field]
                for field in (
                    "implementation",
                    "cache_tag",
                    "executable_sha256",
                )
                if field in raw_evaluator_identity
            }
        else:
            evaluator_identity = None
    except (
        json.JSONDecodeError,
        KeyError,
        OSError,
        ScoreEvidenceError,
        TypeError,
        ValueError,
    ) as error:
        logger.info(
            "Canonical score generation unavailable for summary",
            run_directory=str(run_dir),
            error=str(error),
        )
        return None

    return {
        "benchmark_score": benchmark.benchmark_score,
        "correctness": benchmark.correctness,
        "inertia": benchmark.inertia,
        "cost_per_configured_checkpoint": (
            benchmark.cost_per_configured_checkpoint
        ),
        "generation_id": generation_id,
        "eligibility": manifest.eligibility.model_dump(mode="json"),
        "formula_id": manifest.formula_id,
        "evaluator_identity": evaluator_identity,
        "problems": {
            problem.problem_id: {
                "score": problem.score,
                "production_concision": problem.components.verbosity,
                "structural_quality": problem.components.erosion,
                "acyclic_architecture": problem.components.architecture,
                "rework_stability": problem.components.rework,
                "regression_resistance": problem.components.regression,
            }
            for problem in benchmark.problems
        },
        "report_additions": [
            addition.model_dump(mode="json")
            for addition in manifest.report_additions
            if (addition.problem_name, addition.checkpoint_id)
            in checkpoint_keys
        ],
    }


def _completion_projection(
    summary: RunSummary,
    config: dict[str, Any],
    checkpoint_data: list[dict[str, Any]],
    scoring: dict[str, object] | None,
) -> dict[str, object]:
    passed_tests = sum(int(row.get("passed_tests") or 0) for row in checkpoint_data)
    total_tests = sum(int(row.get("total_tests") or 0) for row in checkpoint_data)
    return {
        "model": summary.model,
        "assessment_policy": str(config.get("assessment_policy", "unknown")),
        "checkpoints_produced": summary.num_checkpoints,
        "checkpoints_configured": summary.expected_checkpoints,
        "tests_passed": passed_tests,
        "tests_total": total_tests,
        "strict_score": (
            scoring["benchmark_score"] if scoring is not None else None
        ),
        "total_cost": summary.costs.total,
        "duration_seconds": sum(
            float(row.get("duration") or 0) for row in checkpoint_data
        ),
        "steps": sum(int(row.get("steps") or 0) for row in checkpoint_data),
    }


def _identity_text(identity: object) -> str:
    if not isinstance(identity, Mapping):
        return "Not produced"
    identity_fields = cast("Mapping[str, object]", identity)
    implementation = identity_fields.get("implementation", "unknown")
    cache_tag = identity_fields.get("cache_tag", "unknown")
    executable_sha256 = identity_fields.get(
        "executable_sha256", "unknown"
    )
    return f"{implementation} {cache_tag}; executable SHA-256 {executable_sha256}"


def render_summary_tables(
    completion: dict[str, object],
    console: Console,
    scoring: dict[str, object] | None = None,
) -> None:
    """Render operational, scoring-quality, and publication summary tables."""
    completion_table = Table(
        title="Completion Summary",
        show_header=True,
        header_style="bold cyan",
        box=box.ROUNDED,
    )
    for heading in (
        "Model",
        "Policy",
        "Checkpoints",
        "Tests",
        "Strict score",
        "Cost",
        "Duration",
        "Steps",
    ):
        completion_table.add_column(
            heading,
            justify="right" if heading not in {"Model", "Policy"} else "left",
        )
    strict_score = completion["strict_score"]
    completion_table.add_row(
        str(completion["model"]),
        str(completion["assessment_policy"]),
        (
            f"{completion['checkpoints_produced']}/"
            f"{completion['checkpoints_configured']}"
        ),
        f"{completion['tests_passed']}/{completion['tests_total']}",
        "Unavailable" if strict_score is None else str(strict_score),
        f"${float(str(completion['total_cost'])):.4f}",
        f"{float(str(completion['duration_seconds'])):.1f}s",
        str(completion["steps"]),
    )

    console.print()
    console.print(completion_table)
    if scoring is None:
        return

    quality_table = Table(
        title="Scoring Quality",
        show_header=True,
        header_style="bold cyan",
        box=box.ROUNDED,
    )
    quality_table.add_column("Problem", overflow="fold")
    quality_table.add_column("Quality component", overflow="fold")
    quality_table.add_column("Value", justify="right")
    quality_table.add_row(
        "Benchmark", "Correctness", str(scoring["correctness"])
    )
    quality_table.add_row("Benchmark", "Inertia", str(scoring["inertia"]))
    problems = scoring["problems"]
    if isinstance(problems, Mapping):
        problem_rows = cast("Mapping[object, object]", problems)
        for problem_name, raw_components in problem_rows.items():
            if not isinstance(raw_components, Mapping):
                continue
            components = cast("Mapping[str, object]", raw_components)
            for label, key in (
                ("Score", "score"),
                ("Production concision", "production_concision"),
                ("Structural quality", "structural_quality"),
                ("Acyclic architecture", "acyclic_architecture"),
                ("Rework stability", "rework_stability"),
                ("Regression resistance", "regression_resistance"),
            ):
                quality_table.add_row(
                    str(problem_name), label, str(components[key])
                )

    eligibility = scoring["eligibility"]
    eligible = False
    if isinstance(eligibility, Mapping):
        eligibility_fields = cast("Mapping[str, object]", eligibility)
        eligible = eligibility_fields.get("eligible") is True
    takeaways = Table(
        title="Key Takeaways",
        show_header=False,
        box=box.ROUNDED,
    )
    takeaways.add_column("Field", style="cyan")
    takeaways.add_column("Value", overflow="fold")
    takeaways.add_row("Published generation", str(scoring["generation_id"]))
    takeaways.add_row("Eligibility", "Eligible" if eligible else "Ineligible")
    takeaways.add_row("Formula ID", str(scoring["formula_id"]))
    takeaways.add_row(
        "Evaluator identity", _identity_text(scoring["evaluator_identity"])
    )

    console.print()
    console.print(quality_table)
    console.print()
    console.print(takeaways)


def _save_experiment_summary(
    run_dir: Path,
    completion: dict[str, object],
    scoring: dict[str, object] | None,
) -> Path:
    recording = Console(
        record=True,
        width=180,
        force_terminal=False,
        color_system=None,
    )
    render_summary_tables(completion, recording, scoring)
    output_path = run_dir / EXPERIMENT_SUMMARY_FILENAME
    output_path.write_text(recording.export_text(styles=False), encoding="utf-8")
    logger.info("Saved human-facing experiment summary", path=str(output_path))
    return output_path


def count_expected_checkpoints(config: dict, problems_dir: Path) -> int:
    """Total checkpoints the run was configured to attempt.

    Resolves each problem in ``config['problems']`` against ``problems_dir``
    and sums ``len(problem.checkpoints)``. Skips problems that fail to load
    with a warning; the remaining sum is the denominator for solve rates.
    """
    problem_names = config.get("problems") or []
    total = 0
    for name in problem_names:
        problem_path = problems_dir / name
        try:
            problem_config = ProblemConfig.from_yaml(problem_path)
        except (
            ConfigError,
            OSError,
            TypeError,
            ValueError,
            yaml.YAMLError,
            ValidationError,
        ) as e:
            logger.warning(
                "Could not resolve problem for expected-checkpoint count",
                problem=name,
                problem_path=str(problem_path),
                error=str(e),
            )
            continue
        total += len(problem_config.checkpoints)
    return total


def display_and_save_summary(
    results_file: Path,
    run_dir: Path,
    config: dict,
    console: Console,
    expected_checkpoints: int,
) -> RunSummary | None:
    """Load, compute, display, and persist one completed-run summary."""
    if not results_file.exists():
        logger.debug(
            "Checkpoint results file not found, skipping summary",
            path=str(results_file),
        )
        return None

    try:
        checkpoint_data = load_checkpoint_data(results_file)
    except (OSError, json.JSONDecodeError) as error:
        logger.warning(
            "Failed to load checkpoint results data",
            path=str(results_file),
            error=str(error),
        )
        return None

    if not checkpoint_data:
        logger.debug(
            "No checkpoint data found, skipping summary",
            path=str(results_file),
        )
        return None

    checkpoint_keys = {
        (str(checkpoint.get("problem")), str(checkpoint.get("checkpoint")))
        for checkpoint in checkpoint_data
    }
    summary = compute_run_summary(config, checkpoint_data, expected_checkpoints)
    scoring = _verified_score_projection(run_dir, checkpoint_keys)
    completion = _completion_projection(
        summary, config, checkpoint_data, scoring
    )
    render_summary_tables(completion, console, scoring)
    save_summary_json(
        summary,
        run_dir,
        completion_projection=completion,
        score_projection=scoring,
    )
    _save_experiment_summary(run_dir, completion, scoring)
    return summary
