from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any
from pathlib import Path as StdPath
from copilot import CopilotClient
from copilot.client import SubprocessConfig
from copilot.generated.session_events import SessionEventType
from copilot.session import MCPLocalServerConfig, PermissionHandler

from tony_ai.agents.copilot_agent import CopilotAgent
from tony_ai.config import COPILOT_TOKEN, DEFAULT_MODEL, DEFAULT_PRO_MODEL, REPO_ROOT,  TONY_WORKSPACE
from tony_ai.llm.provider import get_provider
from tony_ai.monitoring import StateTracker

logger = logging.getLogger(__name__)

# Module-level singleton — created once, shared across all TonyAgent instances.
_state = StateTracker()

def _build_tony_agent_md() -> str:
    agent_text = ""
    with open(REPO_ROOT / ".github" / "agents" / "tony.agent.md") as f:
        agent_text = f.read()

    agent_text += (
        f"\n\n<additional_instructions>\n\n"
        f"You CANNOT access files outside of {TONY_WORKSPACE}.\n"
        f"All your projects are located in {TONY_WORKSPACE}.\n"
        f"Before doing any destructive actions like deleting files, "
        f"always VERIFY with the user.\n\n"
        f"</additional_instructions>"
    )

    return agent_text

class TonyAgent(CopilotAgent):
    _agent_md: str = ""

    def __init__(self) -> None:
        super().__init__()
        if not self._agent_md:
            self._agent_md = _build_tony_agent_md()

