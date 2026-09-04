"""Tests for ty type checking integration."""

from __future__ import annotations

from textwrap import dedent
from unittest.mock import patch

import pytest

from slop_code.metrics.languages.python.type_check import (
    calculate_type_check_metrics,
)


class TestCalculateTypeCheckMetrics:
    """Tests for calculate_type_check_metrics."""

    def test_clean_file(self, tmp_path):
        """File with no type errors returns zero metrics."""
        source = tmp_path / "clean.py"
        source.write_text(
            dedent("""
        x: int = 1
        y: str = "hello"
        """)
        )

        metrics = calculate_type_check_metrics(source)

        assert metrics.errors == 0
        assert metrics.warnings == 0

    def test_file_with_type_error(self, tmp_path):
        """File with a type error reports it."""
        source = tmp_path / "bad.py"
        source.write_text(
            dedent("""
        x: int = "hello"
        """)
        )

        metrics = calculate_type_check_metrics(source)

        assert metrics.errors >= 1
        assert "invalid-assignment" in metrics.counts

    def test_uv_not_available(self, tmp_path):
        """Returns empty metrics when the uv executable is unavailable."""
        source = tmp_path / "test.py"
        source.write_text("x = 1\n")

        with patch(
            "slop_code.metrics.languages.python.type_check._resolve_uv_executable",
            return_value=None,
        ):
            metrics = calculate_type_check_metrics(source)

        assert metrics.errors == 0
        assert metrics.warnings == 0
        assert metrics.counts == {}

    def test_spawn_error_propagates(self, tmp_path):
        """Does not mistake a failed process spawn for unavailable uv."""
        source = tmp_path / "test.py"
        source.write_text("x = 1\n")

        with (
            patch(
                "slop_code.metrics.languages.python.type_check._resolve_uv_executable",
            ),
            patch(
                "slop_code.metrics.languages.python.type_check._run_with_captured_output",
                side_effect=PermissionError,
            ),
            pytest.raises(PermissionError),
        ):
            calculate_type_check_metrics(source)

    def test_invalid_json_output(self, tmp_path):
        """Gracefully handles malformed ty output."""
        source = tmp_path / "test.py"
        source.write_text("x = 1\n")

        with patch(
            "slop_code.metrics.languages.python.type_check._run_with_captured_output",
            return_value=(1, "not json at all", ""),
        ):
            metrics = calculate_type_check_metrics(source)

        assert metrics.errors == 0
        assert metrics.warnings == 0

    def test_empty_file(self, tmp_path):
        """Empty file returns zero metrics."""
        source = tmp_path / "empty.py"
        source.write_text("")

        metrics = calculate_type_check_metrics(source)

        assert metrics.errors == 0
        assert metrics.warnings == 0
