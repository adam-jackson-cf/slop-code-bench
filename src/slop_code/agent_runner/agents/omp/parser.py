"""OMP trajectory parser.

OMP's JSON event stream is identical to Pi's, so event handling is
inherited from ``PiParser``. OMP artifacts are identified only by the
explicit provenance marker written by ``OmpAgent.save_artifacts``.
"""

from __future__ import annotations

from pathlib import Path

from slop_code.agent_runner.agents.pi.parser import PiParser
from slop_code.agent_runner.agents.provenance import read_marker_agent_type
from slop_code.agent_runner.trajectory import Trajectory


class OmpParser(PiParser):
    """Parser for marker-tagged OMP JSON event trajectories."""

    agent_type = "omp"

    def can_parse(self, artifact_dir: Path) -> bool:
        if read_marker_agent_type(artifact_dir) != self.agent_type:
            return False
        return self._has_pi_events(artifact_dir)

    def parse(self, artifact_dir: Path) -> Trajectory:
        trajectory = super().parse(artifact_dir)
        return trajectory.model_copy(update={"agent_type": self.agent_type})
