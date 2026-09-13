"""Tests for ty type checking integration."""

from __future__ import annotations

import json
from pathlib import Path
from textwrap import dedent
from unittest.mock import patch

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

        assert metrics.errors is not None
        assert metrics.errors >= 1
        assert "invalid-assignment" in metrics.counts

    def test_uv_not_available(self, tmp_path):
        """Unavailable checker is distinct from a clean result."""
        source = tmp_path / "test.py"
        source.write_text("x = 1\n")

        with patch(
            "slop_code.metrics.languages.python.type_check._resolve_uv_executable",
            return_value=None,
        ):
            metrics = calculate_type_check_metrics(source)

        assert metrics.errors is None
        assert metrics.warnings is None
        assert metrics.counts == {}
        assert metrics.available is False
        assert metrics.unavailable_reason == "checker_unavailable"

    def test_spawn_error_is_unavailable(self, tmp_path):
        """A failed process launch is not reported as zero type errors."""
        source = tmp_path / "test.py"
        source.write_text("x = 1\n")

        with (
            patch(
                "slop_code.metrics.languages.python.type_check._resolve_uv_executable",
                return_value=Path("/trusted/uv"),
            ),
            patch(
                "slop_code.metrics.languages.python.type_check._run_with_captured_output",
                side_effect=PermissionError,
            ),
        ):
            metrics = calculate_type_check_metrics(source)

        assert metrics.errors is None
        assert metrics.available is False
        assert metrics.unavailable_reason == "checker_launch_failed"

    def test_invalid_json_output_is_unavailable(self, tmp_path):
        """Malformed checker output is not reported as zero errors."""
        source = tmp_path / "test.py"
        source.write_text("x = 1\n")

        with (
            patch(
                "slop_code.metrics.languages.python.type_check._resolve_uv_executable",
                return_value=Path("/trusted/uv"),
            ),
            patch(
                "slop_code.metrics.languages.python.type_check._run_with_captured_output",
                return_value=(1, "not json at all", ""),
            ),
        ):
            metrics = calculate_type_check_metrics(source)

        assert metrics.errors is None
        assert metrics.warnings is None
        assert metrics.available is False
        assert metrics.unavailable_reason == "checker_malformed_output"

    def test_checker_findings_are_measured(self, tmp_path):
        """Checker-defined finding exits remain available measurements."""
        source = tmp_path / "test.py"
        source.write_text("x = 1\n")

        with (
            patch(
                "slop_code.metrics.languages.python.type_check._resolve_uv_executable",
                return_value=Path("/trusted/uv"),
            ),
            patch(
                "slop_code.metrics.languages.python.type_check._run_with_captured_output",
                return_value=(
                    1,
                    json.dumps(
                        [
                            {
                                "severity": "major",
                                "check_name": "invalid-assignment",
                            }
                        ]
                    ),
                    "",
                ),
            ),
        ):
            metrics = calculate_type_check_metrics(source)

        assert metrics.errors == 1
        assert metrics.warnings == 0
        assert metrics.available is True

    def test_operational_exit_is_unavailable(self, tmp_path):
        """Operational checker exits carry explicit unavailable evidence."""
        source = tmp_path / "test.py"
        source.write_text("x = 1\n")

        with (
            patch(
                "slop_code.metrics.languages.python.type_check._resolve_uv_executable",
                return_value=Path("/trusted/uv"),
            ),
            patch(
                "slop_code.metrics.languages.python.type_check._run_with_captured_output",
                return_value=(2, "", "invalid configuration"),
            ),
        ):
            metrics = calculate_type_check_metrics(source)

        assert metrics.errors is None
        assert metrics.available is False
        assert metrics.unavailable_reason == "checker_operational_failure"

    def test_empty_file(self, tmp_path):
        """Empty file returns zero metrics."""
        source = tmp_path / "empty.py"
        source.write_text("")

        metrics = calculate_type_check_metrics(source)

        assert metrics.errors == 0
        assert metrics.warnings == 0
