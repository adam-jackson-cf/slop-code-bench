"""Controlled continuation: start an agent run from a fixed seed snapshot.

A seeded run begins at ``start_checkpoint``. The checkpoint immediately before
it (the seed checkpoint) is materialised in the run directory from a given
snapshot directory, then flows through the normal resume machinery so the agent
session starts from that snapshot exactly like a resumed run.
"""

from __future__ import annotations

import hashlib
import json
import shutil
from collections.abc import Sequence
from datetime import datetime
from pathlib import Path

from slop_code import common
from slop_code.agent_runner.models import ContinuationSeed
from slop_code.agent_runner.models import UsageTracker
from slop_code.evaluation.config import ProblemConfig
from slop_code.logging import get_logger

logger = get_logger(__name__)


class ContinuationSeedError(ValueError):
    """Raised when a seeded start cannot be constructed."""


def directory_digest(path: Path) -> str:
    """Return a sha256 digest of a directory's relative paths and contents."""
    digest = hashlib.sha256()
    for entry in sorted(path.rglob("*"), key=lambda p: p.as_posix()):
        relative = entry.relative_to(path).as_posix()
        if entry.is_symlink():
            digest.update(f"L:{relative}:{entry.readlink()}\0".encode())
        elif entry.is_file():
            digest.update(f"F:{relative}\0".encode())
            with entry.open("rb") as handle:
                for chunk in iter(lambda: handle.read(1 << 20), b""):
                    digest.update(chunk)
            digest.update(b"\0")
        elif entry.is_dir():
            digest.update(f"D:{relative}\0".encode())
    return f"sha256:{digest.hexdigest()}"


def seed_checkpoint_name(
    checkpoint_names: Sequence[str], start_checkpoint: str
) -> str:
    """Return the seed checkpoint (the one before ``start_checkpoint``)."""
    if start_checkpoint not in checkpoint_names:
        raise ContinuationSeedError(
            f"Unknown start checkpoint '{start_checkpoint}'; available: "
            f"{', '.join(checkpoint_names)}"
        )
    index = list(checkpoint_names).index(start_checkpoint)
    if index == 0:
        raise ContinuationSeedError(
            f"Start checkpoint '{start_checkpoint}' is the first checkpoint "
            "and has no seed checkpoint before it; run the problem normally."
        )
    return checkpoint_names[index - 1]


def names_from_seed(
    checkpoint_names: Sequence[str], seed: ContinuationSeed | None
) -> list[str]:
    """Checkpoint names present in a run: from the seed checkpoint onward."""
    names = list(checkpoint_names)
    if seed is None:
        return names
    seed_name = seed_checkpoint_name(names, seed.start_checkpoint)
    return names[names.index(seed_name) :]


def build_seed(
    problem_config: ProblemConfig, snapshot_path: Path, start_checkpoint: str
) -> ContinuationSeed:
    """Validate a seed against a problem and record its digest."""
    if not snapshot_path.is_dir():
        raise ContinuationSeedError(
            f"Start snapshot is not a directory: {snapshot_path}"
        )
    seed_checkpoint_name(
        [name for name, _ in problem_config.iterate_checkpoint_items()],
        start_checkpoint,
    )
    return ContinuationSeed(
        source_path=str(snapshot_path.resolve()),
        start_checkpoint=start_checkpoint,
        digest=directory_digest(snapshot_path),
    )


def materialize_seed(
    problem_config: ProblemConfig,
    seed: ContinuationSeed,
    output_path: Path,
) -> Path:
    """Create the seed checkpoint directory; no-op if already materialised.

    The directory looks like a normal checkpoint directory (checkpoint config,
    ``snapshot/`` copy, ``inference_result.json``) with zero usage and
    ``is_seed`` recorded, so resume detection and reporting need no special
    casing beyond treating it as completed.
    """
    items = dict(problem_config.iterate_checkpoint_items())
    seed_name = seed_checkpoint_name(list(items), seed.start_checkpoint)
    from slop_code.agent_runner import reporting  # noqa: PLC0415 - import cycle

    checkpoint_dir = reporting.setup_checkpoint_output_directory(
        items[seed_name], output_path
    )
    result_path = checkpoint_dir / common.INFERENCE_RESULT_FILENAME
    if result_path.exists():
        return checkpoint_dir

    source = Path(seed.source_path)
    if not source.is_dir():
        raise ContinuationSeedError(
            f"Start snapshot is not a directory: {source}"
        )
    snapshot_dir = checkpoint_dir / common.SNAPSHOT_DIR_NAME
    if snapshot_dir.exists():
        shutil.rmtree(snapshot_dir)
    shutil.copytree(source, snapshot_dir, symlinks=True)

    now = datetime.now()
    record = {
        "started": now.isoformat(),
        "completed": now.isoformat(),
        "elapsed": 0.0,
        "usage": UsageTracker().model_dump(mode="json"),  # type: ignore[call-arg]
        "had_error": False,
        "error_message": None,
        "is_seed": True,
        "seed_source_path": seed.source_path,
        "seed_digest": seed.digest,
        "checkpoint_path": common.to_relative_path(checkpoint_dir),
        "snapshot_dir": common.SNAPSHOT_DIR_NAME,
        "artifacts_dir": None,
    }
    # Written last: its presence marks the seed as fully materialised.
    result_path.write_text(
        json.dumps(record, indent=2, sort_keys=True), encoding="utf-8"
    )
    logger.info(
        "Materialised seed checkpoint",
        checkpoint=seed_name,
        source=seed.source_path,
        digest=seed.digest,
    )
    return checkpoint_dir
