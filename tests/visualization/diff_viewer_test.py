"""Regression tests for diff viewer HTML escaping."""

from __future__ import annotations

import html
import importlib.util
import sys
from contextlib import suppress
from pathlib import Path
from types import ModuleType
from types import SimpleNamespace

import pytest


class _StopRenderingError(Exception):
    """Stop the Streamlit entrypoint after utility functions load."""


def _load_diff_viewer(monkeypatch: pytest.MonkeyPatch) -> ModuleType:
    pytest.importorskip("pygments")
    streamlit = ModuleType("streamlit")
    streamlit.__path__ = []
    streamlit.__dict__["set_page_config"] = lambda **_: None
    streamlit.__dict__["sidebar"] = SimpleNamespace(
        title=lambda *_: None,
        text_input=lambda *_args, **_kwargs: "missing-run-directory",
    )
    streamlit.__dict__["error"] = lambda *_: None

    def stop() -> None:
        raise _StopRenderingError

    streamlit.__dict__["stop"] = stop
    components = ModuleType("streamlit.components")
    components.__path__ = []
    component_v1 = ModuleType("streamlit.components.v1")
    monkeypatch.setitem(sys.modules, "streamlit", streamlit)
    monkeypatch.setitem(sys.modules, "streamlit.components", components)
    monkeypatch.setitem(sys.modules, "streamlit.components.v1", component_v1)
    path = Path("src/slop_code/visualization/diff_viewer.py")
    spec = importlib.util.spec_from_file_location(
        "diff_viewer_under_test", path
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, spec.name, module)
    with suppress(_StopRenderingError):
        spec.loader.exec_module(module)
    return module


def test_generate_modern_diff_escapes_labels_and_preserves_highlighting(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    diff_viewer = _load_diff_viewer(monkeypatch)
    payload = "<img src=x onerror=\"alert('owned')\">"

    rendered = diff_viewer.generate_modern_diff(
        "value = 1\n",
        "value = 2\n",
        f"before {payload}",
        f"after {payload}",
        filename="example.py",
    )

    assert payload not in rendered
    assert html.escape(f"before {payload}") in rendered
    assert html.escape(f"after {payload}") in rendered
    assert "<span" in rendered


def test_get_highlighted_line_escapes_source_when_highlighting_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    diff_viewer = _load_diff_viewer(monkeypatch)
    payload = '<script onload="alert(1)">'

    def fail_highlighting(*_args: object, **_kwargs: object) -> str:
        raise ValueError("unhighlightable")

    monkeypatch.setattr(diff_viewer, "highlight", fail_highlighting)

    assert diff_viewer.get_highlighted_line(payload, object()) == html.escape(
        payload
    )
