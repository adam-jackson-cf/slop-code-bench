"""Broad executable contracts for production verbosity and erosion evidence."""

from __future__ import annotations

import json
import sys
from decimal import Decimal
from decimal import localcontext
from pathlib import Path
from types import SimpleNamespace

import pytest

from slop_code.metrics.scoring import production_quality
from slop_code.metrics.scoring.models import FileRole
from slop_code.metrics.scoring.production_quality import RUFF_RULES
from slop_code.metrics.scoring.production_quality import ProductionQualityError
from slop_code.metrics.scoring.production_quality import _ruff
from slop_code.metrics.scoring.production_quality import (
    produce_production_quality,
)

PYTHON = Path(sys.executable)


def inventory(*paths: str):
    return tuple({"path": path, "role": FileRole.PRODUCTION} for path in paths)


def rows(*paths: str):
    return tuple({"path": path, "success": True} for path in paths)


def produce(tmp_path: Path, source: str, symbols=(), *, path="src/a.py"):
    target = tmp_path / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(source, encoding="utf-8")
    return produce_production_quality(
        "checkpoint", tmp_path, inventory(path), rows(path), symbols, PYTHON
    )


def recompute(result):
    evidence = result.evidence
    source = sum(len(item.source_lines) for item in evidence.files)
    union = set(evidence.verbosity_lines) | set(evidence.clone_lines)
    assert evidence.source_loc_denominator == source
    assert evidence.union_numerator == len(union)
    with localcontext() as context:
        context.prec = 50
        verbosity = Decimal(1) - Decimal(len(union)) / Decimal(source)
        numerator = sum(
            (
                symbol.mass
                for symbol in evidence.eligible_symbols
                if symbol.high_complexity
            ),
            Decimal(0),
        )
        denominator = sum(
            (symbol.mass for symbol in evidence.eligible_symbols), Decimal(0)
        )
        erosion = (
            Decimal(1)
            if not denominator
            else Decimal(1) - numerator / denominator
        )
    assert result.verbosity == verbosity
    assert Decimal(evidence.erosion_numerator) == numerator
    assert Decimal(evidence.erosion_denominator) == denominator
    assert result.erosion == erosion


def test_docker_executor_isolates_measurement_in_saved_run(
    tmp_path, monkeypatch
):
    run_dir = tmp_path.resolve()
    snapshot = run_dir / "problem" / "checkpoint_1" / "snapshot"
    executable = (
        run_dir
        / "measurement_analysis"
        / "evaluator_environments"
        / "environment"
        / ".venv"
        / "bin"
        / "python"
    )
    captured = {}

    def execute(argv, *, cwd=None, stdin=None):
        captured.update(argv=tuple(argv), cwd=cwd, stdin=stdin)
        return SimpleNamespace(returncode=0, stdout="{}", stderr="")

    monkeypatch.setattr(production_quality, "_execute", execute)
    executor = production_quality.DockerProcessExecutor(
        image="locked-image",
        mount_root=run_dir,
        binary="docker-bin",
    )

    executor(
        (str(executable), "-c", "pass"),
        cwd=snapshot,
        stdin="input",
    )

    assert captured["cwd"] is None
    assert captured["stdin"] == "input"
    assert captured["argv"][:8] == (
        "docker-bin",
        "run",
        "--rm",
        "--interactive",
        "--pull=never",
        "--network=none",
        "--read-only",
        "--tmpfs",
    )
    assert (
        f"type=bind,source={run_dir},target={run_dir},readonly"
        in captured["argv"]
    )
    assert ("--workdir", str(snapshot)) == captured["argv"][-6:-4]
    assert captured["argv"][-4:] == (
        "locked-image",
        str(executable),
        "-c",
        "pass",
    )


def test_docker_executor_rejects_runtime_launch_failures(tmp_path, monkeypatch):
    executable = tmp_path.resolve() / "environment" / "python"
    executor = production_quality.DockerProcessExecutor(
        image="missing-image",
        mount_root=tmp_path,
    )
    monkeypatch.setattr(
        production_quality,
        "_execute",
        lambda *_args, **_kwargs: SimpleNamespace(
            returncode=125,
            stdout="",
            stderr="image unavailable",
        ),
    )

    with pytest.raises(
        ProductionQualityError, match="measurement_environment_mismatch"
    ):
        executor((str(executable), "-c", "pass"))


def test_locked_interpreter_hash_must_match_measurement_runtime(tmp_path):
    target = tmp_path / "src/a.py"
    target.parent.mkdir(parents=True)
    target.write_text("x = 1\n")
    with pytest.raises(
        ProductionQualityError, match="measurement_environment_mismatch"
    ):
        produce_production_quality(
            "checkpoint",
            tmp_path,
            inventory("src/a.py"),
            rows("src/a.py"),
            (),
            PYTHON,
            expected_executable_sha256="0" * 64,
        )


def six_statements(prefix=""):
    return "".join(
        f"{prefix}value_{index} = (\n    {index}\n)\n" for index in range(6)
    )


def test_raw_evidence_recomputes_comments_docstrings_multiline_and_deterministically(
    tmp_path,
):
    source = '''"""module docstring"""
# ignored comment
value = (
    1 +
    2
)
text = """multiline
literal"""
sentinel = 1; match = sentinel
'''
    first = produce(tmp_path, source)
    second = produce(tmp_path, source)
    recompute(first)
    assert first.evidence.model_dump(mode="json") == second.evidence.model_dump(
        mode="json"
    )
    assert first.evidence.files[0].source_lines == (1, 3, 4, 5, 6, 7, 8, 9)
    assert first.evidence.interpreter.executable == str(PYTHON)
    assert first.evidence.parser_tokenizer_schema_id


@pytest.mark.parametrize(
    ("code", "source"),
    (
        ("SIM102", "if a:\n    if b:\n        x = 1\n"),
        (
            "SIM103",
            "def f(a):\n    if a:\n        return True\n    else:\n        return False\n",
        ),
        ("SIM108", "if a:\n    x = 1\nelse:\n    x = 2\n"),
        ("SIM109", "if a == x or a == y:\n    pass\n"),
        (
            "SIM110",
            "def f(xs):\n    for x in xs:\n        if x:\n            return True\n    return False\n",
        ),
        ("SIM114", "if a:\n    print('x')\nelif b:\n    print('x')\n"),
        (
            "SIM116",
            "def f(a):\n    if a == 1:\n        return 'a'\n    elif a == 2:\n        return 'b'\n    elif a == 3:\n        return 'c'\n    return 'd'\n",
        ),
        (
            "SIM401",
            "mapping = {}\nif 'key' in mapping:\n    value = mapping['key']\nelse:\n    value = default\n",
        ),
    ),
)
def test_every_observable_allowlisted_ruff_rule_uses_real_isolated_subprocess(
    tmp_path, code, source
):
    result = produce(tmp_path, source)
    diagnostics = result.evidence.ruff.diagnostics
    assert code in {diagnostic.code for diagnostic in diagnostics}
    assert result.evidence.ruff.invocation == (
        str(PYTHON),
        "-m",
        "ruff",
        "check",
        "--isolated",
        "--output-format",
        "json",
        "--select",
        "SIM102,SIM103,SIM108,SIM109,SIM110,SIM111,SIM114,SIM116,SIM401",
        "src/a.py",
    )
    assert result.evidence.ruff.rules == RUFF_RULES
    recompute(result)


def test_allowlist_includes_the_frozen_sim111_boundary(tmp_path):
    result = produce(tmp_path, "x = 1\n")
    assert RUFF_RULES == (
        "SIM102",
        "SIM103",
        "SIM108",
        "SIM109",
        "SIM110",
        "SIM111",
        "SIM114",
        "SIM116",
        "SIM401",
    )
    assert "SIM111" in result.evidence.ruff.rules
    assert any(
        "SIM111" in argument for argument in result.evidence.ruff.invocation
    )


def test_sim111_source_behavior_is_reported_as_sim110(tmp_path):
    result = produce(
        tmp_path,
        "def f(xs):\n    for x in xs:\n        if not x:\n            return False\n    return True\n",
    )
    assert "SIM110" in {
        diagnostic.code for diagnostic in result.evidence.ruff.diagnostics
    }
    recompute(result)


def test_repo_ruff_configuration_is_ignored(tmp_path):
    (tmp_path / "pyproject.toml").write_text(
        "[tool.ruff.lint]\nignore = ['SIM102']\n"
    )
    result = produce(tmp_path, "if a:\n    if b:\n        x = 1\n")
    assert {row.code for row in result.evidence.ruff.diagnostics} == {"SIM102"}


def test_ruff_end_row_at_column_one_is_excluded_from_verbosity(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(
        production_quality,
        "_ruff",
        lambda *_: (
            "ruff 0.8.6",
            (
                {
                    "code": "SIM102",
                    "path": "src/a.py",
                    "start": (1, 1),
                    "end": (2, 1),
                },
            ),
            (),
        ),
    )
    result = produce(tmp_path, "x = 1\ny = 2\n")
    assert result.evidence.verbosity_lines == (("src/a.py", 1),)


def test_ruff_retains_lexical_symlink_identity(tmp_path, monkeypatch):
    source = tmp_path / "src/real.py"
    source.parent.mkdir()
    source.write_text("x = 1\n", encoding="utf-8")
    alias = tmp_path / "src/alias.py"
    alias.symlink_to(source.name)

    def fake_run(command, **_):
        if command[-1] == "--version":
            return SimpleNamespace(
                returncode=0, stdout="ruff 0.8.6\n", stderr=""
            )
        return SimpleNamespace(
            returncode=1,
            stdout=json.dumps(
                [
                    {
                        "code": "SIM102",
                        "filename": "src/alias.py",
                        "location": {"row": 1, "column": 1},
                        "end_location": {"row": 1, "column": 2},
                    }
                ]
            ),
            stderr="",
        )

    monkeypatch.setattr(production_quality, "_execute", fake_run)
    _, diagnostics, _ = _ruff(PYTHON, tmp_path, ("src/alias.py",))
    assert diagnostics[0]["path"] == "src/alias.py"


@pytest.mark.parametrize(
    ("version", "returncode", "message"),
    (
        ("ruff 0.14.1", 0, "Ruff version mismatch"),
        ("ruff 0.8.5", 0, "Ruff version mismatch"),
        ("ruff 0.8.6", 2, "canonical Ruff rule unavailable"),
    ),
)
def test_ruff_rejects_wrong_version_and_unsupported_rules(
    tmp_path, monkeypatch, version, returncode, message
):
    def fake_run(command, **_):
        if command[-1] == "--version":
            return SimpleNamespace(
                returncode=0, stdout=f"{version}\n", stderr=""
            )
        return SimpleNamespace(
            returncode=returncode, stdout="", stderr="unknown rule"
        )

    monkeypatch.setattr(production_quality, "_execute", fake_run)
    with pytest.raises(ProductionQualityError, match=message):
        _ruff(PYTHON, tmp_path, ("src/a.py",))


def test_clone_boundaries_nested_maximal_overlap_literals_and_renames(tmp_path):
    source = (
        six_statements("a_")
        + "\n"
        + six_statements("a_")
        + "\n"
        + "def nested():\n"
        + "    "
        + six_statements("n_").replace("\n", "\n    ").rstrip()
        + "\n"
        + "    "
        + six_statements("n_").replace("\n", "\n    ").rstrip()
        + "\n"
        + "\n"
        + six_statements("different_")
    )
    result = produce(tmp_path, source)
    recompute(result)
    assert len(result.evidence.clones) == 2
    assert all(len(group.vector) == 6 for group in result.evidence.clones)
    twelve = produce(
        tmp_path / "twelve",
        ("".join(f"x{i} = (\n    0\n)\n" for i in range(6)) + "\n") * 2,
    )
    assert len(twelve.evidence.clones) == 1
    eleven = produce(
        tmp_path / "eleven",
        (
            "".join(f"x{i} = 0\n" for i in range(5))
            + "x5 = (\n    0 +\n    0 +\n    0 +\n    0\n)\n"
        )
        * 2,
    )
    assert eleven.evidence.clones == ()


def test_diagnostic_clone_overlap_counts_once_and_cross_root_process_is_stable(
    tmp_path,
):
    block = "if a:\n    if b:\n        x = 1\n" + six_statements()
    result = produce(tmp_path, block + "\n" + block)
    recompute(result)
    assert set(result.evidence.verbosity_lines) & set(
        result.evidence.clone_lines
    )
    other = tmp_path / "other"
    other.mkdir()
    repeat = produce(other, block + "\n" + block)
    assert (
        result.evidence.model_dump(mode="json")["clones"]
        == repeat.evidence.model_dump(mode="json")["clones"]
    )


def test_syntax_and_token_failures_are_rejected(tmp_path):
    for source in ("def broken(:\n", b"\xff"):
        target = tmp_path / "src/a.py"
        target.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(source, bytes):
            target.write_bytes(source)
        else:
            target.write_text(source)
        with pytest.raises(
            ProductionQualityError, match="evaluator parser failed"
        ):
            produce_production_quality(
                "checkpoint",
                tmp_path,
                inventory("src/a.py"),
                rows("src/a.py"),
                (),
                PYTHON,
            )


def test_symbol_universe_boundaries_and_exact_erosion_mass(tmp_path):
    symbols = (
        {
            "path": "src/a.py",
            "kind": "function",
            "qualified_name": "f",
            "start_line": 1,
            "end_line": 2,
            "cc": 10,
            "sloc": 4,
        },
        {
            "path": "src/a.py",
            "kind": "method",
            "qualified_name": "C.m",
            "start_line": 3,
            "end_line": 4,
            "cc": 11,
            "sloc": 2,
        },
        {
            "path": "src/a.py",
            "kind": "function",
            "qualified_name": "outer.inner",
            "start_line": 5,
            "end_line": 6,
            "cc": "0",
            "sloc": 3,
        },
        {
            "path": "src/a.py",
            "kind": "class",
            "qualified_name": "C",
            "start_line": 1,
            "end_line": 6,
            "cc": 100,
            "sloc": 6,
        },
    )
    result = produce(tmp_path, "x = 1\n", symbols)
    recompute(result)
    eligible_symbols = {
        symbol.identity[1]: symbol
        for symbol in result.evidence.eligible_symbols
    }
    assert {
        qualified_name: symbol.high_complexity
        for qualified_name, symbol in eligible_symbols.items()
    } == {"C.m": True, "f": False, "outer.inner": False}
    with localcontext() as context:
        context.prec = 50
        expected_mass = Decimal(11) * Decimal(2).sqrt()
    assert eligible_symbols["C.m"].mass == expected_mass
    assert produce(tmp_path / "empty", "x = 1\n").erosion == Decimal(1)


@pytest.mark.parametrize(
    "symbol",
    (
        {
            "kind": "function",
            "qualified_name": "f",
            "start_line": 1,
            "end_line": 1,
            "cc": -1,
            "sloc": 1,
        },
        {
            "kind": "function",
            "qualified_name": "f",
            "start_line": 1,
            "end_line": 1,
            "cc": "NaN",
            "sloc": 1,
        },
        {
            "kind": "function",
            "qualified_name": "f",
            "start_line": 1,
            "end_line": 1,
            "cc": 1,
            "sloc": 0,
        },
        {
            "kind": "function",
            "qualified_name": "",
            "start_line": 1,
            "end_line": 1,
            "cc": 1,
            "sloc": 1,
        },
    ),
)
def test_malformed_nonpositive_and_duplicate_symbol_evidence_is_rejected(
    tmp_path, symbol
):
    row = {"path": "src/a.py", **symbol}
    with pytest.raises(
        ProductionQualityError, match="production_symbol_evidence_invalid"
    ):
        produce(tmp_path, "x = 1\n", (row,))
    duplicate = {
        "path": "src/a.py",
        "kind": "function",
        "qualified_name": "f",
        "start_line": 1,
        "end_line": 1,
        "cc": 1,
        "sloc": 1,
    }
    with pytest.raises(
        ProductionQualityError, match="production_symbol_evidence_invalid"
    ):
        produce(tmp_path / "duplicate", "x = 1\n", (duplicate, duplicate))


@pytest.mark.parametrize(
    "symbol",
    (
        {
            "kind": "function",
            "qualified_name": "f",
            "start_line": True,
            "end_line": 1,
            "cc": 1,
            "sloc": 1,
        },
        {
            "kind": "function",
            "qualified_name": "f",
            "start_line": 1,
            "end_line": "1",
            "cc": 1,
            "sloc": 1,
        },
        {
            "kind": "function",
            "qualified_name": "f",
            "start_line": 2,
            "end_line": 1,
            "cc": 1,
            "sloc": 1,
        },
    ),
)
def test_symbol_ranges_require_ordered_non_boolean_integers(tmp_path, symbol):
    row = {"path": "src/a.py", **symbol}

    with pytest.raises(
        ProductionQualityError, match="production_symbol_evidence_invalid"
    ):
        produce(tmp_path, "x = 1\n", (row,))


def test_non_string_evidence_mapping_keys_are_rejected(tmp_path):
    target = tmp_path / "src/a.py"
    target.parent.mkdir(parents=True)
    target.write_text("x = 1\n")

    with pytest.raises(
        ProductionQualityError, match="evidence mapping keys must be strings"
    ):
        produce_production_quality(
            "checkpoint",
            tmp_path,
            ({"path": "src/a.py", "role": "production", 1: "invalid"},),
            rows("src/a.py"),
            (),
            PYTHON,
        )


def test_missing_and_duplicate_file_joins_and_zero_production_loc_are_rejected(
    tmp_path,
):
    target = tmp_path / "src/a.py"
    target.parent.mkdir(parents=True)
    target.write_text("# comment only\n")
    with pytest.raises(
        ProductionQualityError, match="missing production file row"
    ):
        produce_production_quality(
            "checkpoint", tmp_path, inventory("src/a.py"), (), (), PYTHON
        )
    with pytest.raises(ProductionQualityError, match="duplicate file row"):
        produce_production_quality(
            "checkpoint",
            tmp_path,
            inventory("src/a.py"),
            rows("src/a.py", "src/a.py"),
            (),
            PYTHON,
        )
    for file_rows in (
        ({"path": "src/a.py"},),
        ({"path": "src/a.py", "success": False},),
        ({"path": "src/a.py", "success": 1},),
    ):
        with pytest.raises(
            ProductionQualityError, match="unsuccessful file row"
        ):
            produce_production_quality(
                "checkpoint",
                tmp_path,
                inventory("src/a.py"),
                file_rows,
                (),
                PYTHON,
            )
    with pytest.raises(
        ProductionQualityError, match="production_source_loc_zero"
    ):
        produce_production_quality(
            "checkpoint",
            tmp_path,
            inventory("src/a.py"),
            rows("src/a.py"),
            (),
            PYTHON,
        )
