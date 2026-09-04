"""Behavioral tests for Python lint metrics."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from slop_code.metrics.languages.python import calculate_lint_metrics
from slop_code.metrics.languages.python import lint_metrics


@pytest.fixture
def lint_execution(monkeypatch):
    """Replace only the internal trusted-process execution boundary."""
    calls: list[list[str]] = []

    def configure(
        stdout: str = "",
        *,
        exit_status: int = 1,
        stderr: str = "",
        error: OSError | None = None,
    ) -> list[list[str]]:
        def execute(command: list[str]) -> tuple[int, str, str]:
            calls.append(command)
            if error is not None:
                raise error
            return exit_status, stdout, stderr

        monkeypatch.setattr(lint_metrics, "_run_with_captured_output", execute)
        return calls

    monkeypatch.setattr(
        lint_metrics, "_resolve_uv_executable", lambda: Path("/trusted/uv")
    )
    return configure


class TestCalculateLintMetrics:
    """Tests for parsing Ruff statistics and execution failures."""

    def test_calculate_lint_metrics_with_errors(self, tmp_path, lint_execution):
        test_file = tmp_path / "test.py"
        test_file.write_text("def func():\n    x=1\n")
        calls = lint_execution(
            json.dumps(
                [
                    {"code": "E501", "count": 3, "fixable": True},
                    {"code": "E302", "count": 2, "fixable": False},
                    {"code": "W503", "count": 1, "fixable": True},
                ]
            )
        )

        metrics = calculate_lint_metrics(test_file)

        assert metrics.errors == 6
        assert metrics.fixable == 4
        assert metrics.counts == {"E501": 3, "E302": 2, "W503": 1}
        assert calls == [
            [
                "/trusted/uv",
                "run",
                "ruff",
                "check",
                "--statistics",
                "--output-format",
                "json",
                "--isolated",
                "--preview",
                *lint_metrics.RUFF_SELECT_FLAGS,
                str(test_file.resolve()),
            ]
        ]

    @pytest.mark.parametrize("stdout", ["", "[]"])
    def test_calculate_lint_metrics_without_errors(
        self, tmp_path, lint_execution, stdout
    ):
        test_file = tmp_path / "clean.py"
        test_file.write_text("def func():\n    pass\n")
        lint_execution(stdout, exit_status=0)

        metrics = calculate_lint_metrics(test_file)

        assert metrics.errors == 0
        assert metrics.fixable == 0
        assert metrics.counts == {}

    def test_calculate_lint_metrics_malformed_json(
        self, tmp_path, lint_execution
    ):
        test_file = tmp_path / "test.py"
        test_file.write_text("code")
        lint_execution("invalid json line 1\ninvalid json line 2\n")

        metrics = calculate_lint_metrics(test_file)

        assert metrics.errors == 0
        assert metrics.fixable == 0
        assert metrics.counts == {}

    def test_calculate_lint_metrics_with_prefix(self, tmp_path, lint_execution):
        test_file = tmp_path / "test.py"
        test_file.write_text("code")
        lint_execution(
            'Warning: something\n[{"code": "E501", "count": 1, "fixable": true}]'
        )

        metrics = calculate_lint_metrics(test_file)

        assert metrics.errors == 1
        assert metrics.fixable == 1
        assert metrics.counts == {"E501": 1}

    def test_calculate_lint_metrics_execution_error(
        self, tmp_path, lint_execution
    ):
        test_file = tmp_path / "test.py"
        test_file.write_text("code")
        lint_execution(error=OSError("cannot execute ruff"))

        metrics = calculate_lint_metrics(test_file)

        assert metrics.errors == 0
        assert metrics.fixable == 0
        assert metrics.counts == {}


class TestErrorCodes:
    """Tests for aggregation of Ruff diagnostic categories."""

    @pytest.mark.parametrize(
        ("stats", "expected_errors", "expected_fixable", "expected_counts"),
        [
            (
                [{"code": "E501", "count": 5, "fixable": True}],
                5,
                5,
                {"E501": 5},
            ),
            (
                [
                    {"code": "E501", "count": 2, "fixable": True},
                    {"code": "E302", "count": 3, "fixable": True},
                    {"code": "W503", "count": 1, "fixable": False},
                    {"code": "F401", "count": 4, "fixable": True},
                ],
                10,
                9,
                {"E501": 2, "E302": 3, "W503": 1, "F401": 4},
            ),
            (
                [
                    {"code": "E999", "count": 1, "fixable": False},
                    {"code": "E501", "count": 2, "fixable": False},
                ],
                3,
                0,
                {"E999": 1, "E501": 2},
            ),
        ],
    )
    def test_error_code_aggregation(
        self,
        tmp_path,
        lint_execution,
        stats,
        expected_errors,
        expected_fixable,
        expected_counts,
    ):
        test_file = tmp_path / "test.py"
        test_file.write_text("code")
        lint_execution(json.dumps(stats))

        metrics = calculate_lint_metrics(test_file)

        assert metrics.errors == expected_errors
        assert metrics.fixable == expected_fixable
        assert metrics.counts == expected_counts


class TestLintMetricsEdgeCases:
    """Tests for parser boundaries and required Ruff fields."""

    def test_whitespace_in_output(self, tmp_path, lint_execution):
        test_file = tmp_path / "test.py"
        test_file.write_text("code")
        lint_execution(
            '  \n  [{"code": "E501", "count": 1, "fixable": true}]  \n'
        )

        metrics = calculate_lint_metrics(test_file)

        assert metrics.errors == 1
        assert metrics.fixable == 1
        assert metrics.counts == {"E501": 1}

    @pytest.mark.parametrize(
        "stat",
        [
            {"code": "E501", "fixable": True},
            {"code": "E501", "count": 1},
        ],
    )
    def test_missing_required_fields_raise_key_error(
        self, tmp_path, lint_execution, stat
    ):
        test_file = tmp_path / "test.py"
        test_file.write_text("code")
        lint_execution(json.dumps([stat]))

        with pytest.raises(KeyError):
            calculate_lint_metrics(test_file)

    def test_extra_fields_are_ignored(self, tmp_path, lint_execution):
        test_file = tmp_path / "test.py"
        test_file.write_text("code")
        lint_execution(
            json.dumps(
                [
                    {
                        "code": "E501",
                        "count": 1,
                        "fixable": True,
                        "extra_field": "ignored",
                        "another": 123,
                    }
                ]
            )
        )

        metrics = calculate_lint_metrics(test_file)

        assert metrics.errors == 1
        assert metrics.fixable == 1
        assert metrics.counts == {"E501": 1}

    def test_zero_count(self, tmp_path, lint_execution):
        test_file = tmp_path / "test.py"
        test_file.write_text("code")
        lint_execution(
            json.dumps([{"code": "E501", "count": 0, "fixable": True}])
        )

        metrics = calculate_lint_metrics(test_file)

        assert metrics.errors == 0
        assert metrics.fixable == 0
        assert metrics.counts == {"E501": 0}


class TestLintMetricsModel:
    """Tests for LintMetrics serialization."""

    def test_lint_metrics_serialization(self, tmp_path, lint_execution):
        test_file = tmp_path / "test.py"
        test_file.write_text("code")
        lint_execution(
            json.dumps(
                [
                    {"code": "E501", "count": 2, "fixable": True},
                    {"code": "W503", "count": 1, "fixable": False},
                ]
            )
        )

        data = calculate_lint_metrics(test_file).model_dump()

        assert data == {
            "errors": 3,
            "fixable": 2,
            "counts": {"E501": 2, "W503": 1},
        }
