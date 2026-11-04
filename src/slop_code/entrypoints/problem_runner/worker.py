"""Agent execution wrapper for problem runner.

This module provides the function that executes an agent on a single problem.
"""

from __future__ import annotations

import queue
import shutil
from datetime import datetime
from pathlib import Path
from typing import Any

from slop_code import common
from slop_code import evaluation
from slop_code.agent_runner import AgentRunSpec
from slop_code.agent_runner import continuation
from slop_code.agent_runner import runner
from slop_code.agent_runner.agent import Agent
from slop_code.agent_runner.models import UsageTracker
from slop_code.agent_runner.reporting import MetricsTracker
from slop_code.agent_runner.resume import ResumeInfo
from slop_code.agent_runner.resume import detect_resume_point
from slop_code.agent_runner.resume import format_resume_summary
from slop_code.agent_runner.state import AgentStateEnum
from slop_code.common.constants import MEASUREMENT_ANALYSIS_DIR
from slop_code.common.llms import TokenUsage
from slop_code.entrypoints.problem_runner.models import RunTaskConfig
from slop_code.entrypoints.problem_runner.one_shot import apply_one_shot_mode
from slop_code.logging import get_logger
from slop_code.metrics.scoring.schema import problem_key

logger = get_logger(__name__)


def _send_completed_progress(
    problem_name: str,
    resume_info: ResumeInfo,
    output_path: Path,
    progress_queue: queue.Queue,
) -> None:
    """Send a progress update for a fully-completed problem so live stats are accurate."""
    now = datetime.now()
    metrics = MetricsTracker(
        state=AgentStateEnum.COMPLETED,
        current_checkpoint=resume_info.completed_checkpoints[-1]
        if resume_info.completed_checkpoints
        else "",
        usage=resume_info.prior_usage.model_copy(deep=True),
        started=now,
        checkpoint_started=now,
    )
    for checkpoint_name in resume_info.completed_checkpoints:
        checkpoint_dir = output_path / checkpoint_name
        eval_result = runner._load_eval_result(checkpoint_dir)
        metrics.record_checkpoint_result(checkpoint_name, eval_result)
    dummy_usage = UsageTracker(
        cost=0.0,
        steps=0,
        current_tokens=TokenUsage(),
        net_tokens=TokenUsage(),
    )
    progress_queue.put((problem_name, dummy_usage, metrics))


def _delete_invalidated_checkpoints(
    output_path: Path,
    problem_name: str,
    resume_info: ResumeInfo,
) -> None:
    """Delete checkpoint outputs and pending scoring evidence that will be re-run.

    When resuming with invalidated checkpoints (e.g., due to spec changes or
    errors), deletes the old checkpoint directories and their pending
    measurement evidence so the re-run commits fresh evidence.

    Args:
        output_path: Base output directory for the problem
        problem_name: Problem name used to key pending scoring evidence
        resume_info: Resume information with invalidated checkpoints
    """
    if not resume_info.invalidated_checkpoints:
        return

    logger.info(
        "Deleting invalidated checkpoint directories",
        checkpoints=resume_info.invalidated_checkpoints,
    )

    pending_root = (
        output_path.parent
        / MEASUREMENT_ANALYSIS_DIR
        / "pending"
        / problem_key(problem_name)
    )
    for checkpoint_name in resume_info.invalidated_checkpoints:
        for directory in (
            output_path / checkpoint_name,
            pending_root / checkpoint_name,
        ):
            if directory.exists():
                shutil.rmtree(directory)
                logger.debug(
                    "Deleted invalidated checkpoint output",
                    checkpoint=checkpoint_name,
                    path=str(directory),
                )


def _evaluate_seed_checkpoint(
    problem_config: evaluation.ProblemConfig,
    seed_name: str,
    config: RunTaskConfig,
    output_path: Path,
) -> None:
    """Run the standard evaluation on the materialised seed checkpoint."""
    seed_dir = output_path / seed_name
    if (
        config.disable_evaluation
        or (seed_dir / common.EVALUATION_FILENAME).exists()
    ):
        return
    runner.evaluate_agent_snapshot(
        checkpoint=problem_config.checkpoints[seed_name],
        save_dir=seed_dir,
        snapshot_dir=seed_dir / common.SNAPSHOT_DIR_NAME,
        problem=problem_config,
        environment=config.env_spec,
    )


def run_agent_on_problem(
    problem_config: evaluation.ProblemConfig,
    problem_name: str,
    config: RunTaskConfig,
    progress_queue: queue.Queue,
    output_path: Path,
) -> dict[str, Any]:
    """Execute an agent on a problem with progress reporting.

    Creates an AgentRunSpec from the config and runs the agent with
    progress updates sent to the queue.

    Args:
        problem_config: Problem configuration
        problem_name: Name of the problem
        config: Shared execution configuration
        progress_queue: Queue for progress updates
        output_path: Directory for output files

    Returns:
        Dictionary containing the run results including summary with state,
        passed_policy, and any error information.
    """
    problem_config = apply_one_shot_mode(
        problem_config=problem_config, one_shot=config.one_shot
    )

    # Seeded start: materialise and evaluate the seed checkpoint, then let the
    # normal resume machinery restore the agent session from its snapshot.
    seed = config.continuation_seed
    seed_name: str | None = None
    checkpoint_items = list(problem_config.iterate_checkpoint_items())
    if seed is not None:
        all_names = [name for name, _ in checkpoint_items]
        seed_name = continuation.seed_checkpoint_name(
            all_names, seed.start_checkpoint
        )
        continuation.materialize_seed(problem_config, seed, output_path)
        _evaluate_seed_checkpoint(
            problem_config, seed_name, config, output_path
        )
        present = set(continuation.names_from_seed(all_names, seed))
        checkpoint_items = [
            (name, cp) for name, cp in checkpoint_items if name in present
        ]

    # Detect resume point if resume mode is enabled
    resume_info: ResumeInfo | None = None
    if config.resume or seed is not None:
        checkpoint_names = [name for name, _ in checkpoint_items]
        checkpoints = [cp for _, cp in checkpoint_items]
        resume_info = detect_resume_point(
            output_path,
            checkpoint_names,
            problem_config=problem_config,
            prompt_template=config.prompt_template,
            environment=config.env_spec,
            entry_file=problem_config.entry_file,
            checkpoints=checkpoints,
            agent_type=config.agent_config.type,
            agent_version=config.agent_config.version,
            model_name=config.model_def.name,
        )
        if resume_info:
            # Check if all checkpoints are already completed
            if not resume_info.resume_from_checkpoint:
                logger.info(
                    "All checkpoints completed, skipping",
                    problem=problem_name,
                    completed=len(resume_info.completed_checkpoints),
                )
                _send_completed_progress(
                    problem_name, resume_info, output_path, progress_queue
                )
                evaluation_results = [
                    runner._load_eval_result(output_path / checkpoint_name)
                    for checkpoint_name in resume_info.completed_checkpoints
                    if checkpoint_name != seed_name
                ]
                passed_policy = config.disable_evaluation or all(
                    evaluation_result is not None
                    and config.assessment_policy.check(
                        evaluation_result.pass_counts,
                        evaluation_result.total_counts,
                    )
                    for evaluation_result in evaluation_results
                )
                return {
                    "summary": {
                        "state": "completed",
                        "passed_policy": passed_policy,
                        "usage": resume_info.prior_usage.model_dump()
                        if hasattr(resume_info.prior_usage, "model_dump")
                        else {},
                    }
                }

            # Log detailed resume summary
            summary = format_resume_summary(resume_info, problem_name)
            logger.info(
                "Resuming from checkpoint",
                problem=problem_name,
                checkpoint=resume_info.resume_from_checkpoint,
                completed=len(resume_info.completed_checkpoints),
                invalidated=resume_info.invalidated_checkpoints,
                summary=summary,
            )

            # Delete invalidated checkpoint directories
            _delete_invalidated_checkpoints(
                output_path, problem_name, resume_info
            )

    run_spec = AgentRunSpec(
        seed=config.seed,
        template=config.prompt_template,
        problem=problem_config,
        environment=config.env_spec,
        assessment_policy=config.assessment_policy,
        continue_after_test_failure=config.continue_after_test_failure,
        skip_evaluation=config.disable_evaluation,
        concurrent_evaluation=config.concurrent_evaluation,
        verbose=config.verbosity > 0,
        image=config.image,
        agent_type=config.agent_config.type,
        agent_version=config.agent_config.version,
        model_name=config.model_def.name,
        continuation_seed=config.continuation_seed,
    )

    return runner.run_agent(
        run_spec=run_spec,
        agent=Agent.from_config(
            config.agent_config,
            model=config.model_def,
            credential=config.credential,
            problem_name=problem_name,
            verbose=run_spec.verbose,
            image=config.image,
            thinking_preset=config.thinking_preset,
            thinking_max_tokens=config.thinking_max_tokens,
        ),
        output_path=output_path,
        progress_queue=progress_queue,
        resume_info=resume_info,
    )
