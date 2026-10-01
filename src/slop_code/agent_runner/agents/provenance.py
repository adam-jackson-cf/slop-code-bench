"""Explicit artifact provenance markers.

Some agents emit an event stream identical to another agent's, so the
format alone cannot identify the producer. Those agents write a small
JSON marker next to their artifacts and their parsers key off it.
"""

from __future__ import annotations

import json
from pathlib import Path

MARKER_FILENAME = "agent.json"


def write_marker(path: Path, agent_type: str, version: str | None) -> None:
    """Write the provenance marker into an artifact directory."""
    (path / MARKER_FILENAME).write_text(
        json.dumps({"agent_type": agent_type, "version": version}) + "\n"
    )


def read_marker_agent_type(artifact_dir: Path) -> str | None:
    """Return the agent type declared by the marker, if one is present."""
    marker = artifact_dir / MARKER_FILENAME
    try:
        payload = json.loads(marker.read_text())
    except (OSError, ValueError):
        return None
    if not isinstance(payload, dict):
        return None
    agent_type = payload.get("agent_type")
    return agent_type if isinstance(agent_type, str) else None
