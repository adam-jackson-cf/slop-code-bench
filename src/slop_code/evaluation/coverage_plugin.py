"""Internal pytest plugin for canonical coverage and process audit evidence."""

from __future__ import annotations

import importlib
import json
import os
import pty
import subprocess
from pathlib import Path
from typing import Any, cast

LEDGER_RELATIVE_PATH = ".scbench/coverage-ledger.json"
PLUGIN_ID = "slop-code-coverage-audit-v1"


def canonical_ledger_bytes(ledger: dict[str, object]) -> bytes:
    """Serialize evaluator evidence deterministically."""
    return json.dumps(
        ledger, ensure_ascii=True, separators=(",", ":"), sort_keys=True
    ).encode("utf-8")


class CoverageAuditPlugin:
    """Capture per-node pytest phases and process-creation audit events."""

    def __init__(self, root: Path) -> None:
        self._root = root
        self._nodes: dict[str, dict[str, str]] = {}
        self._process_events: list[dict[str, str]] = []
        self._active_nodeid: str | None = None
        self._active_phase: str | None = None
        self._invalid_coverage_paths = 0
        self._originals: list[tuple[object, str, Any]] = []

    def pytest_configure(self, config: Any) -> None:
        self._install_process_audit()
        self._switch_coverage_context("collection")

    def pytest_unconfigure(self, config: Any) -> None:
        self._restore_process_audit()
        outcomes = [
            {"node_id": nodeid, "phase": phase, "outcome": node[phase]}
            for nodeid, node in sorted(self._nodes.items())
            for phase in ("collection", "setup", "call", "teardown")
            if phase in node
        ]
        ledger = {
            "plugin_id": PLUGIN_ID,
            "ledger": outcomes,
            "coverage": self._coverage_contexts(),
            "process_events": self._process_events,
            "invalid_coverage_paths": self._invalid_coverage_paths,
        }
        path = self._root / LEDGER_RELATIVE_PATH
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("wb") as handle:
            handle.write(canonical_ledger_bytes(ledger))
            handle.flush()
            os.fsync(handle.fileno())

    def pytest_collection_modifyitems(self, items: list[Any]) -> None:
        for item in items:
            self._nodes.setdefault(item.nodeid, {})["collection"] = "passed"

    def pytest_collectstart(self, collector: Any) -> None:
        node_id = collector.nodeid or "<session>"
        self._activate(node_id, "collection")

    def pytest_collectreport(self, report: Any) -> None:
        if report.failed:
            self._nodes.setdefault(report.nodeid, {})["collection"] = "failed"
        self._active_nodeid = None
        self._active_phase = "collection"

    def pytest_runtest_logreport(self, report: Any) -> None:
        if report.when not in {"setup", "call", "teardown"}:
            return
        self._nodes.setdefault(report.nodeid, {})[report.when] = report.outcome

    def pytest_runtest_setup(self, item: Any) -> None:
        self._activate(item.nodeid, "setup")

    def pytest_runtest_call(self, item: Any) -> None:
        self._activate(item.nodeid, "call")

    def pytest_runtest_teardown(self, item: Any) -> None:
        self._activate(item.nodeid, "teardown")

    def _activate(self, nodeid: str, phase: str) -> None:
        self._active_nodeid, self._active_phase = nodeid, phase
        self._switch_coverage_context(f"{nodeid}|{phase}")

    def _switch_coverage_context(self, context: str) -> None:
        try:
            coverage_module = importlib.import_module("coverage")
        except ModuleNotFoundError:
            return
        coverage = coverage_module.Coverage.current()
        if coverage is not None:
            coverage.switch_context(context)

    def _coverage_contexts(self) -> list[dict[str, object]]:
        try:
            coverage_module = importlib.import_module("coverage")
        except ModuleNotFoundError:
            return []
        coverage = coverage_module.Coverage.current()
        if coverage is None:
            return []
        rows: list[dict[str, object]] = []
        root = self._root.resolve()
        for path in coverage.get_data().measured_files():
            candidate = Path(path)
            if not candidate.is_absolute():
                candidate = root / candidate
            try:
                candidate.relative_to(root)
            except ValueError:
                # Dependencies and interpreter files outside the submission are
                # irrelevant to production attribution.
                continue
            try:
                relative = candidate.resolve().relative_to(root).as_posix()
            except ValueError:
                # A path located inside the submission that resolves outside it
                # is an invalid symlink escape, not an external dependency.
                self._invalid_coverage_paths += 1
                continue
            first = relative.partition("/")[0]
            if first in {
                ".evaluation_tests",
                ".scbench",
                ".scbench-evaluator-cache",
            }:
                continue
            for line, contexts in (
                coverage.get_data().contexts_by_lineno(path).items()
            ):
                if not isinstance(line, int):
                    continue
                for context in contexts:
                    node_id, separator, phase = context.rpartition("|")
                    if not separator or phase not in {
                        "setup",
                        "call",
                        "teardown",
                    }:
                        continue
                    rows.append(
                        {
                            "node_id": node_id,
                            "phase": phase,
                            "path": relative,
                            "executed_line": line,
                        }
                    )
        return sorted(
            rows,
            key=lambda row: (
                str(row["node_id"]),
                str(row["phase"]),
                str(row["path"]),
                cast(int, row["executed_line"]),
            ),
        )

    def _install_process_audit(self) -> None:
        self._patch(subprocess, "Popen", "subprocess.Popen")
        self._patch(os, "system", "os.system")
        if hasattr(os, "posix_spawn"):
            self._patch(os, "posix_spawn", "os.posix_spawn")
        if hasattr(os, "fork"):
            self._patch(os, "fork", "os.fork")
        self._patch(pty, "spawn", "pty.spawn")

    def _patch(self, owner: object, attribute: str, api: str) -> None:
        original = getattr(owner, attribute)

        def audited(*args: Any, **kwargs: Any) -> Any:
            self._record_process_event(api)
            return original(*args, **kwargs)

        self._originals.append((owner, attribute, original))
        setattr(owner, attribute, audited)

    def _restore_process_audit(self) -> None:
        for owner, attribute, original in reversed(self._originals):
            setattr(owner, attribute, original)
        self._originals.clear()

    def _record_process_event(self, api: str) -> None:
        if self._active_nodeid is None or self._active_phase is None:
            return
        self._process_events.append(
            {
                "event": api,
                "node_id": self._active_nodeid,
                "phase": self._active_phase,
            }
        )


def pytest_configure(config: Any) -> None:
    """Register the plugin when loaded with ``-p coverage_plugin``."""
    config.pluginmanager.register(
        CoverageAuditPlugin(Path.cwd()), "coverage-audit"
    )
