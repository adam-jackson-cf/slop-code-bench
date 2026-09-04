"""Coverage-audit pytest plugin contract tests."""

from __future__ import annotations

import json
import os
import pty
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from slop_code.evaluation.coverage_plugin import LEDGER_RELATIVE_PATH
from slop_code.evaluation.coverage_plugin import CoverageAuditPlugin
from slop_code.evaluation.coverage_plugin import canonical_ledger_bytes


def test_canonical_ledger_bytes_are_sorted_and_compact() -> None:
    assert canonical_ledger_bytes({"z": 1, "a": ["x"]}) == b'{"a":["x"],"z":1}'


def test_plugin_records_exact_parameterized_id_and_phase_outcomes(
    tmp_path: Path,
) -> None:
    plugin = CoverageAuditPlugin(tmp_path)
    nodeid = "tests/test_example.py::test_value[one two]"
    plugin.pytest_collection_modifyitems([SimpleNamespace(nodeid=nodeid)])
    for phase, outcome in (
        ("setup", "passed"),
        ("call", "failed"),
        ("teardown", "passed"),
    ):
        plugin.pytest_runtest_logreport(
            SimpleNamespace(nodeid=nodeid, when=phase, outcome=outcome)
        )
    plugin.pytest_unconfigure(None)

    ledger = json.loads((tmp_path / LEDGER_RELATIVE_PATH).read_text())
    assert ledger["ledger"] == [
        {"node_id": nodeid, "phase": "collection", "outcome": "passed"},
        {"node_id": nodeid, "phase": "setup", "outcome": "passed"},
        {"node_id": nodeid, "phase": "call", "outcome": "failed"},
        {"node_id": nodeid, "phase": "teardown", "outcome": "passed"},
    ]

def test_plugin_ignores_external_dependencies_but_rejects_symlink_escapes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "source.py"
    source.write_text("value = 1\n")
    external = tmp_path.parent / "dependency.py"
    external.write_text("value = 2\n")
    escape = tmp_path / "escape.py"
    escape.symlink_to(external)

    class CoverageData:
        def measured_files(self) -> list[str]:
            return [str(source), str(external), str(escape)]

        def contexts_by_lineno(self, path: str) -> dict[int, list[str]]:
            return {1: ["test.py::test_value|call"]}

    active_coverage = SimpleNamespace(get_data=CoverageData)
    coverage_module = SimpleNamespace(
        Coverage=SimpleNamespace(current=lambda: active_coverage)
    )
    monkeypatch.setitem(sys.modules, "coverage", coverage_module)
    plugin = CoverageAuditPlugin(tmp_path)

    assert plugin._coverage_contexts() == [
        {
            "node_id": "test.py::test_value",
            "phase": "call",
            "path": "source.py",
            "executed_line": 1,
        }
    ]
    assert plugin._invalid_coverage_paths == 1


@pytest.mark.parametrize(
    ("owner", "attribute", "api"),
    [
        (subprocess, "Popen", "subprocess.Popen"),
        (os, "system", "os.system"),
        (os, "posix_spawn", "os.posix_spawn"),
        (os, "fork", "os.fork"),
        (pty, "spawn", "pty.spawn"),
    ],
)
def test_plugin_records_each_audited_process_api(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    owner: object,
    attribute: str,
    api: str,
) -> None:
    calls: list[tuple[object, ...]] = []

    def original(*args: object, **kwargs: object) -> int:
        calls.append(args)
        return 0

    monkeypatch.setattr(owner, attribute, original)
    plugin = CoverageAuditPlugin(tmp_path)
    plugin._install_process_audit()
    plugin.pytest_runtest_call(
        SimpleNamespace(nodeid="test.py::test_process[param]")
    )
    getattr(owner, attribute)("command")
    plugin.pytest_unconfigure(None)

    ledger = json.loads((tmp_path / LEDGER_RELATIVE_PATH).read_text())
    assert calls == [("command",)]
    assert ledger["process_events"] == [
        {
            "event": api,
            "node_id": "test.py::test_process[param]",
            "phase": "call",
        }
    ]


def test_plugin_records_collection_failure_and_passing_call(
    tmp_path: Path,
) -> None:
    plugin = CoverageAuditPlugin(tmp_path)
    plugin.pytest_collectreport(SimpleNamespace(failed=True, nodeid="bad.py"))
    plugin.pytest_collection_modifyitems(
        [SimpleNamespace(nodeid="ok.py::test_ok")]
    )
    plugin.pytest_runtest_logreport(
        SimpleNamespace(nodeid="ok.py::test_ok", when="call", outcome="passed")
    )
    plugin.pytest_unconfigure(None)

    ledger = json.loads((tmp_path / LEDGER_RELATIVE_PATH).read_text())
    assert ledger["ledger"] == [
        {"node_id": "bad.py", "phase": "collection", "outcome": "failed"},
        {
            "node_id": "ok.py::test_ok",
            "phase": "collection",
            "outcome": "passed",
        },
        {"node_id": "ok.py::test_ok", "phase": "call", "outcome": "passed"},
    ]


def test_plugin_preserves_exact_process_event_order(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []

    def system(command: str) -> int:
        calls.append(command)
        return 0

    def popen(command: str) -> int:
        calls.append(command)
        return 0

    monkeypatch.setattr(os, "system", system)
    monkeypatch.setattr(subprocess, "Popen", popen)
    plugin = CoverageAuditPlugin(tmp_path)
    plugin._install_process_audit()
    nodeid = "test.py::test_process_order[first value]"
    plugin.pytest_runtest_setup(SimpleNamespace(nodeid=nodeid))
    getattr(os, "system")("setup")
    plugin.pytest_runtest_call(SimpleNamespace(nodeid=nodeid))
    getattr(subprocess, "Popen")("call")
    plugin.pytest_runtest_teardown(SimpleNamespace(nodeid=nodeid))
    getattr(os, "system")("teardown")
    plugin.pytest_unconfigure(None)

    ledger = json.loads((tmp_path / LEDGER_RELATIVE_PATH).read_text())
    assert calls == ["setup", "call", "teardown"]
    assert ledger["process_events"] == [
        {"event": "os.system", "node_id": nodeid, "phase": "setup"},
        {"event": "subprocess.Popen", "node_id": nodeid, "phase": "call"},
        {"event": "os.system", "node_id": nodeid, "phase": "teardown"},
    ]
