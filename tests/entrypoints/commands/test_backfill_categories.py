from __future__ import annotations

import json
from pathlib import Path

import pytest

from slop_code.entrypoints.commands import backfill_categories as command


def test_save_grades_replaces_only_complete_parseable_grade_sets(tmp_path):
    rubric_file = tmp_path / "rubric.jsonl"
    rubric_file.write_bytes(b'{"old": true}\n')
    grades = [{"criteria": "first"}, {"criteria": "second"}]

    command._save_grades(rubric_file, grades)

    assert [
        json.loads(line) for line in rubric_file.read_text().splitlines()
    ] == grades


def test_save_grades_preserves_original_when_writing_fails(
    tmp_path, monkeypatch
):
    rubric_file = tmp_path / "rubric.jsonl"
    original = b'{"old": true}\n'
    rubric_file.write_bytes(original)

    def fail_dump(_grade: object) -> str:
        raise OSError("write failed")

    monkeypatch.setattr(command.json, "dumps", fail_dump)

    with pytest.raises(OSError, match="write failed"):
        command._save_grades(rubric_file, [{"criteria": "new"}])

    assert rubric_file.read_bytes() == original
    assert not list(tmp_path.glob(".rubric.jsonl.*.tmp"))


def test_save_grades_preserves_original_when_publish_fails(
    tmp_path, monkeypatch
):
    rubric_file = tmp_path / "rubric.jsonl"
    original = b'{"old": true}\n'
    rubric_file.write_bytes(original)

    def fail_replace(_self: Path, _target: Path) -> Path:
        raise OSError("publish failed")

    monkeypatch.setattr(Path, "replace", fail_replace)

    with pytest.raises(OSError, match="publish failed"):
        command._save_grades(rubric_file, [{"criteria": "new"}])

    assert rubric_file.read_bytes() == original
    assert not list(tmp_path.glob(".rubric.jsonl.*.tmp"))
