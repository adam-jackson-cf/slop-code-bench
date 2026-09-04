"""Boundary tests for deterministic production inventory classification."""

import os
import stat
from pathlib import Path
from types import SimpleNamespace

import pytest

from slop_code.metrics.scoring import inventory
from slop_code.metrics.scoring.inventory import _matches_glob
from slop_code.metrics.scoring.inventory import build_inventory


@pytest.mark.parametrize(
    ("pattern", "path", "matched"),
    (
        ("src/*.py", "src/a.py", True),
        ("src/*.py", "src/nested/a.py", False),
        ("src/a?.py", "src/ab.py", True),
        ("src/**/a.py", "src/a.py", True),
        ("src/**/a.py", "src/x/a.py", True),
        ("**/*.py", "a/b.py", True),
        ("**/*.py", "a/b.PY", False),
    ),
)
def test_anchored_glob_operators(pattern, path, matched):
    assert _matches_glob(path, pattern) is matched


def test_inventory_roles_evidence_and_precedence(tmp_path: Path):
    files = {
        "generated.py": "# @generated\n",
        "line_five.py": "\n\n\n\n# Code generated\n",
        "line_six.py": "\n\n\n\n\n# @generated\n",
        "false.py": "# generated\n",
        "tests/test_sample.py": "pass\n",
        "testing/a.js": "x\n",
        "__tests__/a.ts": "x\n",
        "test/a.go": "x\n",
        "conftest.py": "pass\n",
        "unit_test.py": "pass\n",
        "widget.spec.rs": "x\n",
        "widget.test.java": "x\n",
        "overlap.js": "// @generated\n",
        "production.py": "pass\n",
        "unsupported.ts": "x\n",
        "unknown.txt": "x\n",
        "extensionless": "x\n",
        "mixed.PY": "x\n",
    }
    for name, content in files.items():
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)
    result = build_inventory(
        tmp_path,
        generated_globs=("line_six.py", "overlap.js"),
        test_globs=("overlap.js",),
    )
    by_path = {entry.path: entry for entry in result.files}
    assert by_path["generated.py"].role.value == "generated"
    assert by_path["line_five.py"].role.value == "generated"
    assert by_path["line_six.py"].role.value == "generated"
    assert by_path["false.py"].role.value == "production"
    for name in (
        "tests/test_sample.py",
        "testing/a.js",
        "__tests__/a.ts",
        "test/a.go",
        "conftest.py",
        "unit_test.py",
        "widget.spec.rs",
        "widget.test.java",
    ):
        assert by_path[name].role.value == "test"
    assert by_path["overlap.js"].role.value == "generated"
    assert by_path["overlap.js"].matched_rules == (
        "generated_glob:overlap.js",
        "generated_marker",
        "test_glob:overlap.js",
    )
    assert by_path["unknown.txt"].ignored_reason == "unrecognized_extension"
    assert by_path["extensionless"].ignored_reason == "extensionless"
    assert by_path["mixed.PY"].ignored_reason == "unrecognized_extension"
    assert result.unsupported_paths == ("unsupported.ts",)
    assert result.eligibility_codes == ("production_language_unsupported",)


def test_inventory_is_lexical_ordered_and_root_independent(tmp_path: Path):
    for root in (tmp_path / "one", tmp_path / "two"):
        root.mkdir()
        for name in ("Z.py", "a.py"):
            (root / name).write_text("pass\n")
    first = build_inventory(tmp_path / "one")
    second = build_inventory(tmp_path / "two")
    assert [entry.path for entry in first.files] == [
        entry.path for entry in second.files
    ]


def test_inventory_preserves_case_and_unicode_lexical_identities(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
):
    class ByteEntry:
        def __init__(self, name: bytes) -> None:
            self.name = name
            self.path = os.fsencode(tmp_path) + b"/" + name

        def stat(self, *, follow_symlinks: bool) -> SimpleNamespace:
            assert follow_symlinks is False
            return SimpleNamespace(st_mode=stat.S_IFREG)

    entries = [
        ByteEntry(name)
        for name in (b"\xc3\xa9.py", b"a.py", b"e\xcc\x81.py", b"Z.py")
    ]

    def scandir(directory: bytes) -> list[ByteEntry]:
        assert directory == os.fsencode(tmp_path)
        return entries

    monkeypatch.setattr(inventory.os, "scandir", scandir)

    identities = [path for path, _, _ in inventory._iter_entries(tmp_path)]
    assert identities == ["Z.py", "a.py", "e\u0301.py", "\u00e9.py"]
    assert identities[2] != identities[3]
    assert identities[0] != identities[1]


def test_inventory_symlink_boundaries_and_invalid_content(tmp_path: Path):
    (tmp_path / "inside.py").write_text("pass\n")
    (tmp_path / "invalid.py").write_bytes(b"\xff")
    (tmp_path / "link.py").symlink_to(tmp_path / "inside.py")
    (tmp_path / "broken.py").symlink_to(tmp_path / "missing.py")
    outside = tmp_path.parent / "outside.py"
    outside.write_text("pass\n")
    (tmp_path / "escape.py").symlink_to(outside)
    (tmp_path / "directory").mkdir()
    (tmp_path / "directory_link").symlink_to(
        tmp_path / "directory", target_is_directory=True
    )
    result = build_inventory(tmp_path)
    by_path = {entry.path: entry for entry in result.files}
    assert by_path["link.py"].is_symlink is True
    assert by_path["link.py"].resolved_path == "inside.py"
    assert by_path["link.py"].source_hash == by_path["inside.py"].source_hash
    assert "directory_link" not in by_path
    assert (
        by_path["invalid.py"].ignored_reason == "source_unreadable_or_non_utf8"
    )
    assert result.invalid_codes == ("score_evidence_invalid",)
