from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated

import typer
import yaml

from slop_code.common import CONFIG_FILENAME
from slop_code.common.constants import CURRENT_POINTER_FILENAME
from slop_code.common.constants import GENERATIONS_DIR
from slop_code.common.constants import MANIFEST_FILENAME
from slop_code.common.constants import MEASUREMENT_ANALYSIS_DIR
from slop_code.entrypoints.commands import common
from slop_code.entrypoints.utils import discover_run_directories
from slop_code.evaluation import ProblemConfig
from slop_code.logging import setup_logging
from slop_code.metrics.scoring.finalization import finalize_benchmark_score
from slop_code.metrics.scoring.generation import finalize_lock
from slop_code.metrics.scoring.historical import capture_historical_provenance
from slop_code.metrics.scoring.models import Eligibility


def register(app: typer.Typer, name: str):
    app.command(
        name,
        help=(
            "Capture immutable historical provenance and publish canonical "
            "score state"
        ),
    )(backfill_reports)


def _problem_configs(
    problem_root: Path, run_dir: Path
) -> tuple[ProblemConfig, ...]:
    config = yaml.safe_load((run_dir / CONFIG_FILENAME).read_text())
    if not isinstance(config, dict) or not isinstance(
        config.get("problems"), list
    ):
        raise ValueError("run config must contain an ordered problems list")
    return tuple(
        common.load_problem_config(problem_root / name)
        for name in config["problems"]
    )


def _current_eligibility(run_dir: Path) -> Eligibility:
    analysis = run_dir / MEASUREMENT_ANALYSIS_DIR
    pointer = json.loads((analysis / CURRENT_POINTER_FILENAME).read_bytes())
    generation = analysis / GENERATIONS_DIR / pointer["generation_id"]
    manifest = json.loads((generation / MANIFEST_FILENAME).read_bytes())
    return Eligibility.model_validate(manifest["eligibility"])


def _process_historical_run(problem_root: Path, run_dir: Path) -> Eligibility:
    problems = _problem_configs(problem_root, run_dir)
    with finalize_lock(run_dir):
        capture_historical_provenance(run_dir, problems)
        finalize_benchmark_score(run_dir, problems, lock_held=True)
    return _current_eligibility(run_dir)


def backfill_reports(
    ctx: typer.Context,
    results_dir: Annotated[
        Path,
        typer.Argument(
            help="Path to the results directory or collection directory",
            exists=True,
            dir_okay=True,
            file_okay=False,
        ),
    ],
    path_type: Annotated[
        common.PathType,
        typer.Option(
            "--type",
            "-t",
            help=(
                "Type of path: 'run' for single run, 'collection' for "
                "multiple runs"
            ),
        ),
    ] = common.PathType.RUN,
) -> None:
    """Capture non-mutating provenance and publish historical score state."""
    logger = setup_logging(log_dir=None, verbosity=ctx.obj.verbosity)
    if logger is None:
        raise RuntimeError("backfill-reports requires standard logging")
    problem_root = common.resolve_problem_catalog_root(ctx)
    run_dirs = (
        discover_run_directories(results_dir)
        if path_type == common.PathType.COLLECTION
        else [results_dir]
    )
    if not run_dirs:
        typer.echo(f"No run directories found in {results_dir}", err=True)
        raise typer.Exit(1)
    failures = 0
    for run_dir in run_dirs:
        try:
            eligibility = _process_historical_run(problem_root, run_dir)
        except Exception as error:
            failures += 1
            logger.error(
                "Historical score finalization failed",
                run_dir=str(run_dir),
                error=str(error),
                exc_info=True,
            )
            typer.echo(f"{run_dir.name}: failed: {error}", err=True)
            continue
        state = "eligible" if eligibility.eligible else "ineligible"
        reasons = ",".join(eligibility.reasons)
        typer.echo(
            f"{run_dir.name}: {state}" + (f" ({reasons})" if reasons else "")
        )
    if failures:
        raise typer.Exit(1)
