"""Tests for checkpoint 2: extended word stats with lines and stopwords."""

import contextlib
import io
import runpy
import sys

import pytest

MAIN_SCRIPT = "main.py"


def run_main(input_text: str, args: list[str] | None = None) -> str:
    """Run main.py directly with the given input and return stdout."""
    stdout = io.StringIO()
    original_argv, original_stdin = sys.argv, sys.stdin
    try:
        sys.argv = [MAIN_SCRIPT, *(args or [])]
        sys.stdin = io.StringIO(input_text)
        with contextlib.redirect_stdout(stdout):
            runpy.run_path(MAIN_SCRIPT, run_name="__main__")
    finally:
        sys.argv, sys.stdin = original_argv, original_stdin
    return stdout.getvalue().strip()


class TestLineCount:
    """Core tests for line counting functionality."""

    def test_lines_single_line(self):
        """Test line count with single line."""
        output = run_main("hello world", args=["--lines"])
        assert output == "words: 2, lines: 1"

    def test_lines_multiple(self):
        """Test line count with multiple lines."""
        output = run_main("hello world\nfoo bar\nbaz", args=["--lines"])
        assert output == "words: 5, lines: 3"

    def test_lines_empty(self):
        """Test line count with empty input."""
        output = run_main("", args=["--lines"])
        assert output == "words: 0, lines: 0"


class TestStopwordFiltering:
    """Tests for stopword filtering functionality."""

    def test_filter_stopwords(self, static_assets):
        """Test filtering stopwords."""
        stopwords_path = static_assets.get("stopwords")
        if not stopwords_path:
            pytest.skip("stopwords static asset not available")

        output = run_main(
            "the quick brown fox",
            args=["--filter-stopwords", stopwords_path],
        )
        # "the" is a stopword, so only 3 words should be counted
        assert output == "3"

    def test_filter_all_stopwords(self, static_assets):
        """Test input that is all stopwords."""
        stopwords_path = static_assets.get("stopwords")
        if not stopwords_path:
            pytest.skip("stopwords static asset not available")

        output = run_main(
            "the a an is are",
            args=["--filter-stopwords", stopwords_path],
        )
        assert output == "0"

    @pytest.mark.functionality
    def test_filter_case_insensitive(self, static_assets):
        """Test that stopword filtering is case-insensitive."""
        stopwords_path = static_assets.get("stopwords")
        if not stopwords_path:
            pytest.skip("stopwords static asset not available")

        output = run_main(
            "THE Quick BROWN Fox",
            args=["--filter-stopwords", stopwords_path],
        )
        # "THE" should be filtered (case-insensitive)
        assert output == "3"


class TestCombined:
    """Tests for combined functionality."""

    @pytest.mark.functionality
    def test_lines_and_stopwords(self, static_assets):
        """Test combining --lines and --filter-stopwords."""
        stopwords_path = static_assets.get("stopwords")
        if not stopwords_path:
            pytest.skip("stopwords static asset not available")

        output = run_main(
            "the quick fox\njumps over",
            args=["--lines", "--filter-stopwords", stopwords_path],
        )
        # "the" and "over" are stopwords -> 3 words, 2 lines
        assert output == "words: 3, lines: 2"
