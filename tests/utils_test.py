"""Tests for general-purpose utility functions."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier

from slop_code.utils import get_next_experiment_dir


def test_get_next_experiment_dir_reserves_unique_directories_concurrently(
    tmp_path: Path,
) -> None:
    """Concurrent callers reserve distinct directories rather than sharing one."""
    experiment_dir = tmp_path / "experiments"
    experiment_dir.mkdir()
    existing = {child.name for child in experiment_dir.iterdir()}
    allocator_count = 8
    barrier = Barrier(allocator_count)

    def allocate() -> Path:
        barrier.wait()
        return Path(get_next_experiment_dir(experiment_dir))

    with ThreadPoolExecutor(max_workers=allocator_count) as executor:
        allocated = list(
            executor.map(lambda _: allocate(), range(allocator_count))
        )

    assert len(set(allocated)) == allocator_count
    assert all(path.parent == experiment_dir for path in allocated)
    assert all(path.is_dir() for path in allocated)
    assert all(path.name not in existing for path in allocated)


def test_get_next_experiment_dir_uses_child_names_and_literal_prefixes(
    tmp_path: Path,
) -> None:
    """Only matching child directory names contribute to the next suffix."""
    experiment_dir = tmp_path / "exp_999" / "experiments"
    experiment_dir.mkdir(parents=True)
    prefix = "trial.+("
    (experiment_dir / f"{prefix}002").mkdir()
    (experiment_dir / f"{prefix}010").mkdir()
    (experiment_dir / f"other{prefix}999").mkdir()
    (experiment_dir / f"{prefix}003-extra").mkdir()

    allocated = Path(get_next_experiment_dir(experiment_dir, prefix))

    assert allocated == experiment_dir / f"{prefix}011"
    assert allocated.is_dir()
