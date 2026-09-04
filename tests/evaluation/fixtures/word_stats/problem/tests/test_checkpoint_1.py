"""Tests for checkpoint 1: basic word counting."""

import contextlib
import io
import runpy
import sys

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


class TestBasicWordCount:
    """Core tests for basic word counting functionality."""

    def test_simple_words(self):
        """Test counting simple space-separated words."""
        output = run_main("hello world")
        assert output == "2"

    def test_multiple_words(self):
        """Test counting multiple words."""
        output = run_main("the quick brown fox jumps")
        assert output == "5"

    def test_empty_input(self):
        """Test empty input returns 0."""
        output = run_main("")
        assert output == "0"

    def test_single_word(self):
        """Test single word."""
        output = run_main("hello")
        assert output == "1"

    def test_whitespace_only(self):
        """Test whitespace-only input."""
        output = run_main("   \t\n  ")
        assert output == "0"

    def test_multiline(self):
        """Test multiline input."""
        output = run_main("hello world\nfoo bar baz")
        assert output == "5"
