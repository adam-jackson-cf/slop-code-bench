"""Agent implementations for running against checkpoints."""

from __future__ import annotations

from typing import Annotated

from pydantic import Field

# Import modules for their registration side-effects and public APIs.
from slop_code.agent_runner.agents.claude_code import ClaudeCodeAgent
from slop_code.agent_runner.agents.claude_code import ClaudeCodeConfig
from slop_code.agent_runner.agents.codex import CodexAgent
from slop_code.agent_runner.agents.codex import CodexConfig
from slop_code.agent_runner.agents.cursor_cli import CursorCliAgent
from slop_code.agent_runner.agents.cursor_cli import CursorCliConfig
from slop_code.agent_runner.agents.gemini import GeminiAgent
from slop_code.agent_runner.agents.gemini import GeminiConfig
from slop_code.agent_runner.agents.kimi_cli import KimiCliAgent
from slop_code.agent_runner.agents.kimi_cli import KimiCliConfig
from slop_code.agent_runner.agents.opencode import OpenCodeAgentConfig
from slop_code.agent_runner.agents.openhands import OpenHandsAgent
from slop_code.agent_runner.agents.openhands import OpenHandsConfig
from slop_code.agent_runner.agents.pi import PiAgent
from slop_code.agent_runner.agents.pi import PiConfig

type AgentConfigType = Annotated[
    ClaudeCodeConfig
    | CodexConfig
    | CursorCliConfig
    | GeminiConfig
    | KimiCliConfig
    | OpenCodeAgentConfig
    | OpenHandsConfig
    | PiConfig,
    Field(discriminator="type"),
]

__all__ = [
    "AgentConfigType",
    "ClaudeCodeAgent",
    "ClaudeCodeConfig",
    "CodexAgent",
    "CodexConfig",
    "CursorCliAgent",
    "CursorCliConfig",
    "GeminiAgent",
    "GeminiConfig",
    "KimiCliAgent",
    "KimiCliConfig",
    "OpenCodeAgentConfig",
    "OpenHandsAgent",
    "OpenHandsConfig",
    "PiAgent",
    "PiConfig",
]
