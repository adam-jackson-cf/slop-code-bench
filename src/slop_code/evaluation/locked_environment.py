"""Immutable, content-addressed evaluator Python environments."""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
import shutil
import stat
import tomllib
from collections.abc import Callable
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from slop_code.common.constants import EVALUATOR_ENVIRONMENTS_DIR
from slop_code.common.constants import EVALUATOR_INSTALLED_FILES_FILENAME
from slop_code.common.constants import EVALUATOR_METADATA_FILENAME
from slop_code.common.constants import EVALUATOR_READY_FILENAME
from slop_code.evaluation.config import ProblemConfig


class LockedEnvironmentError(RuntimeError):
    """Raised when an evaluator environment cannot be safely used."""


@dataclass(frozen=True)
class LockedEvaluatorEnvironment:
    """A fully verified, immutable evaluator environment."""

    environment_id: str
    root: Path
    python: Path
    metadata: dict[str, Any]


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _canonical_json(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode()


def _read_required(path: Path) -> bytes:
    try:
        return path.read_bytes()
    except OSError as exc:
        raise LockedEnvironmentError(
            f"missing required evaluator input: {path}"
        ) from exc


def _project_inputs(
    problem_config: ProblemConfig,
) -> tuple[Path, bytes, bytes, bytes]:
    project = problem_config.path.resolve()
    pyproject = _read_required(project / "pyproject.toml")
    lock = _read_required(project / "uv.lock")
    try:
        document = tomllib.loads(pyproject.decode("utf-8"))
        project_dependencies = document["project"].get("dependencies", [])
    except (
        KeyError,
        TypeError,
        UnicodeDecodeError,
        tomllib.TOMLDecodeError,
    ) as exc:
        raise LockedEnvironmentError(
            "invalid evaluator pyproject dependency declaration"
        ) from exc
    declared = tuple(problem_config.test_dependencies)
    if (
        not isinstance(project_dependencies, list)
        or any(not isinstance(item, str) for item in project_dependencies)
        or any(item not in project_dependencies for item in declared)
    ):
        raise LockedEnvironmentError(
            "test_dependencies must be locked in project dependencies"
        )
    dependencies = _canonical_json(list(declared))
    return project, pyproject, lock, dependencies


def _environment_inputs(
    problem_config: ProblemConfig, plugin_bytes: bytes, interpreter_spec: bytes
) -> tuple[Path, dict[str, bytes], str]:
    project, pyproject, lock, dependencies = _project_inputs(problem_config)
    inputs = {
        "pyproject.toml": pyproject,
        "uv.lock": lock,
        "test_dependencies.json": dependencies,
        "coverage_plugin.py": plugin_bytes,
        "interpreter": interpreter_spec,
    }
    environment_id = _sha256(
        b"".join(
            name.encode() + b"\0" + inputs[name] + b"\0"
            for name in sorted(inputs)
        )
    )
    return project, inputs, environment_id


def _inventory(root: Path) -> list[dict[str, str]]:
    """Return hashes and final modes for every immutable payload entry."""
    excluded = {
        EVALUATOR_READY_FILENAME,
        EVALUATOR_METADATA_FILENAME,
        EVALUATOR_INSTALLED_FILES_FILENAME,
    }
    entries: list[dict[str, str]] = []
    for path in sorted(root.rglob("*")):
        relative = path.relative_to(root).as_posix()
        if relative in excluded:
            continue
        mode = format(
            stat.S_IMODE(path.lstat().st_mode)
            if path.is_symlink()
            else 0o555
            if path.is_dir() or path.stat().st_mode & stat.S_IXUSR
            else 0o444,
            "04o",
        )
        if path.is_symlink():
            target = path.readlink()
            entries.append(
                {
                    "path": relative,
                    "type": "symlink",
                    "sha256": _sha256(str(target).encode()),
                    "mode": mode,
                }
            )
        elif path.is_file():
            entries.append(
                {
                    "path": relative,
                    "type": "file",
                    "sha256": _sha256(path.read_bytes()),
                    "mode": mode,
                }
            )
        elif path.is_dir():
            entries.append(
                {
                    "path": relative,
                    "type": "directory",
                    "sha256": "",
                    "mode": mode,
                }
            )
    return entries


def _fsync_file(path: Path) -> None:
    with path.open("rb") as handle:
        os.fsync(handle.fileno())


def _fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _write_bytes(path: Path, content: bytes) -> None:
    with path.open("wb") as handle:
        handle.write(content)
        handle.flush()
        os.fsync(handle.fileno())


def _publish_ready(parent: Path, target: Path, payload: dict[str, str]) -> None:
    temporary = parent / f".{target.name}.{EVALUATOR_READY_FILENAME}.tmp"
    _write_bytes(temporary, _canonical_json(payload))
    temporary.chmod(0o444)
    _fsync_file(temporary)
    temporary.replace(target / EVALUATOR_READY_FILENAME)
    _fsync_directory(target)


def _normalize_permissions(root: Path) -> None:
    for path in sorted(
        root.rglob("*"), key=lambda item: len(item.parts), reverse=True
    ):
        if path.is_symlink():
            continue
        path.chmod(
            0o555
            if path.is_dir() or path.stat().st_mode & stat.S_IXUSR
            else 0o444
        )
    # The root remains writable until READY is atomically installed.


def _remove_incomplete(path: Path) -> None:
    if not path.exists() or (path / EVALUATOR_READY_FILENAME).exists():
        return
    for entry in sorted(
        path.rglob("*"), key=lambda item: len(item.parts), reverse=True
    ):
        if not entry.is_symlink():
            entry.chmod(0o755 if entry.is_dir() else 0o644)
    path.chmod(0o755)
    shutil.rmtree(path)


def _contains_forbidden_cache(root: Path) -> bool:
    cache_directories = {
        ".cache",
        ".mypy_cache",
        ".pytest_cache",
        ".ruff_cache",
        ".uv-cache",
        "__pycache__",
    }
    for path in root.rglob("*"):
        if path.is_dir() and path.name in cache_directories:
            return True
        if path.is_file() and (
            path.suffix in {".pyc", ".pyo"}
            or path.name == ".coverage"
            or path.name.startswith(".coverage.")
        ):
            return True
    return False


@contextmanager
def _id_lock(parent: Path, environment_id: str) -> Iterator[None]:
    locks = parent / "locks"
    locks.mkdir(mode=0o755, exist_ok=True)
    lock_path = locks / f"{environment_id}.lock"
    with lock_path.open("a+b") as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(lock.fileno(), fcntl.LOCK_UN)


def _resolve_uv_executable() -> Path:
    executable = shutil.which("uv")
    if executable is None:
        raise LockedEnvironmentError("uv executable is unavailable")
    path = Path(executable).resolve()
    if not path.is_file() or not os.access(path, os.X_OK):
        raise LockedEnvironmentError("uv executable is unavailable")
    return path


def _sync_frozen_environment(uv: Path, target: Path) -> None:
    command = [
        str(uv),
        "--directory",
        str(target),
        "sync",
        "--frozen",
        "--no-install-project",
    ]
    try:
        process_id = os.posix_spawn(
            str(uv),
            command,
            {
                **os.environ,
                "UV_PROJECT_ENVIRONMENT": str(target / ".venv"),
            },
        )
        _, status = os.waitpid(process_id, 0)
    except OSError as exc:
        raise LockedEnvironmentError(
            "frozen evaluator environment sync failed"
        ) from exc
    if os.waitstatus_to_exitcode(status) != 0:
        raise LockedEnvironmentError("frozen evaluator environment sync failed")


def verify_locked_evaluator_environment(
    path: Path, expected_environment_id: str
) -> LockedEvaluatorEnvironment:
    """Return ``path`` only if every published environment byte verifies."""
    ready = path / EVALUATOR_READY_FILENAME
    metadata_path = path / EVALUATOR_METADATA_FILENAME
    inventory_path = path / EVALUATOR_INSTALLED_FILES_FILENAME
    if (
        not ready.is_file()
        or not metadata_path.is_file()
        or not inventory_path.is_file()
    ):
        raise LockedEnvironmentError(
            f"evaluator environment is not published: {path}"
        )
    try:
        metadata_bytes = metadata_path.read_bytes()
        inventory_bytes = inventory_path.read_bytes()
        ready_payload = json.loads(ready.read_bytes())
        metadata = json.loads(metadata_bytes)
        inventory = json.loads(inventory_bytes)
    except (OSError, json.JSONDecodeError) as exc:
        raise LockedEnvironmentError(
            f"invalid evaluator metadata: {path}"
        ) from exc
    expected_ready = {
        "environment_id": expected_environment_id,
        "environment_sha256": _sha256(metadata_bytes),
        "installed_files_sha256": _sha256(inventory_bytes),
        "pyproject_sha256": metadata.get("input_sha256", {}).get(
            "pyproject.toml"
        ),
        "uv_lock_sha256": metadata.get("input_sha256", {}).get("uv.lock"),
    }
    if ready_payload != expected_ready:
        raise LockedEnvironmentError("evaluator READY marker does not match")
    if metadata.get("environment_id") != expected_environment_id:
        raise LockedEnvironmentError("evaluator environment ID does not match")
    if metadata.get("metadata_sha256") != _sha256(
        _canonical_json(
            {
                key: value
                for key, value in metadata.items()
                if key != "metadata_sha256"
            }
        )
    ):
        raise LockedEnvironmentError("evaluator metadata hash does not match")
    if metadata.get("installed_files_sha256") != _sha256(inventory_bytes):
        raise LockedEnvironmentError("evaluator inventory hash does not match")
    if inventory != _inventory(path):
        raise LockedEnvironmentError(
            "evaluator environment files do not match inventory"
        )
    if _contains_forbidden_cache(path):
        raise LockedEnvironmentError(
            "evaluator environment contains a forbidden cache"
        )
    python = path / ".venv" / "bin" / "python"
    if not python.is_file() or not os.access(python, os.X_OK):
        raise LockedEnvironmentError("evaluator interpreter is unavailable")
    if stat.S_IMODE(path.stat().st_mode) != 0o555:
        raise LockedEnvironmentError("evaluator root is mutable")
    for entry in path.rglob("*"):
        if entry.is_symlink():
            continue
        mode = stat.S_IMODE(entry.stat().st_mode)
        if entry.is_dir() and mode != 0o555:
            raise LockedEnvironmentError("evaluator directory is mutable")
        if entry.is_file() and mode not in {0o444, 0o555}:
            raise LockedEnvironmentError("evaluator file is mutable")
    declared_modes = {item["path"]: int(item["mode"], 8) for item in inventory}
    for entry in path.rglob("*"):
        relative = entry.relative_to(path).as_posix()
        if (
            relative in declared_modes
            and stat.S_IMODE(entry.lstat().st_mode) != declared_modes[relative]
        ):
            raise LockedEnvironmentError(
                "evaluator file mode does not match inventory"
            )
    return LockedEvaluatorEnvironment(
        expected_environment_id, path, python, metadata
    )


def ensure_locked_evaluator_environment(
    parent: Path,
    problem_config: ProblemConfig,
    plugin_bytes: bytes,
    interpreter_spec: bytes,
    failure_observer: Callable[[str], None] | None = None,
    sync_environment: Callable[[Path], None] | None = None,
) -> LockedEvaluatorEnvironment:
    """Build or reuse the immutable evaluator environment for exact inputs."""
    parent = (parent / EVALUATOR_ENVIRONMENTS_DIR).resolve()
    parent.mkdir(parents=True, exist_ok=True)
    _, inputs, environment_id = _environment_inputs(
        problem_config, plugin_bytes, interpreter_spec
    )
    target = parent / environment_id
    with _id_lock(parent, environment_id):
        try:
            return verify_locked_evaluator_environment(target, environment_id)
        except LockedEnvironmentError:
            if (target / EVALUATOR_READY_FILENAME).exists():
                raise
            _remove_incomplete(target)
        target.mkdir(mode=0o755)
        for name, content in inputs.items():
            if name != "interpreter":
                _write_bytes(target / name, content)
        if failure_observer is not None:
            failure_observer("before_sync")
        if sync_environment is None:
            _sync_frozen_environment(_resolve_uv_executable(), target)
        else:
            sync_environment(target)
        if failure_observer is not None:
            failure_observer("after_sync")
        metadata: dict[str, Any] = {
            "environment_id": environment_id,
            "input_sha256": {
                name: _sha256(content) for name, content in inputs.items()
            },
            "project_sha256": _sha256(inputs["pyproject.toml"]),
            "interpreter": interpreter_spec.decode(
                "utf-8", errors="surrogateescape"
            ),
        }
        _normalize_permissions(target)
        inventory = _inventory(target)
        inventory_bytes = _canonical_json(inventory)
        metadata["installed_files_sha256"] = _sha256(inventory_bytes)
        metadata["metadata_sha256"] = _sha256(_canonical_json(metadata))
        metadata_bytes = _canonical_json(metadata)
        installed_path = target / EVALUATOR_INSTALLED_FILES_FILENAME
        metadata_path = target / EVALUATOR_METADATA_FILENAME
        _write_bytes(installed_path, inventory_bytes)
        _write_bytes(metadata_path, metadata_bytes)
        installed_path.chmod(0o444)
        metadata_path.chmod(0o444)
        _fsync_file(installed_path)
        _fsync_file(metadata_path)
        _fsync_directory(target)
        _publish_ready(
            parent,
            target,
            {
                "environment_id": environment_id,
                "environment_sha256": _sha256(metadata_bytes),
                "installed_files_sha256": _sha256(inventory_bytes),
                "pyproject_sha256": metadata["input_sha256"]["pyproject.toml"],
                "uv_lock_sha256": metadata["input_sha256"]["uv.lock"],
            },
        )
        target.chmod(0o555)
        _fsync_directory(parent)
        if failure_observer is not None:
            failure_observer("published")
        return verify_locked_evaluator_environment(target, environment_id)
