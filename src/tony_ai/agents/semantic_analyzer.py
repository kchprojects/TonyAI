import asyncio
import json
import re
from enum import Enum
from pathlib import Path
import time
from typing import Any

from copilot import CopilotClient
from copilot.client import SubprocessConfig
from copilot.session import PermissionHandler

from tony_ai.config import COPILOT_TOKEN, DEFAULT_MODEL, DEFAULT_PRO_MODEL

from logging import getLogger
logger = getLogger(__name__)
logger.setLevel("INFO")

_AGENT_FILE = Path(__file__).parent.parent.parent.parent / ".github" / "agents" / "sem_anal.md"

def _load_agent_prompt() -> str:
    content = _AGENT_FILE.read_text(encoding="utf-8").strip()
    # Strip YAML frontmatter (VS Code parses it separately; we only want the body)
    if content.startswith("---"):
        end = content.find("---", 3)
        if end != -1:
            content = content[end + 3:].strip()
    return content


_PRO_ACTIVITIES = {"CODING", "DOCUMENTATION", "DESIGN", "TESTING", "RESEARCH", "PLANNING"}

class ActivityType(Enum):
    CODING = "CODING"
    DOCUMENTATION = "DOCUMENTATION"
    DESIGN = "DESIGN"
    TESTING = "TESTING"
    RESEARCH = "RESEARCH"
    PLANNING = "PLANNING"
    CHATTING = "CHATTING"
    OTHER = "OTHER"


class MessageContext:
    def __init__(
        self,
        project_name: str | None,
        activities: list[ActivityType],
        actions: list[str],
        goal: str,
    ):
        self.project_name = project_name
        self.activities = activities
        self.actions = actions
        self.goal = goal

    @property
    def activity_type(self) -> ActivityType:
        """Primary activity — first in the list. Kept for backward compatibility."""
        return self.activities[0] if self.activities else ActivityType.OTHER

    def get_best_model(self) -> str:
        for act in self.activities:
            if act.value in _PRO_ACTIVITIES:
                return DEFAULT_PRO_MODEL
        return DEFAULT_MODEL

    @staticmethod
    def from_dict(d: dict[str, Any]) -> "MessageContext":
        raw_activities = d.get("activities") or [d.get("activity_type", "OTHER")]
        activities = []
        for a in raw_activities:
            try:
                activities.append(ActivityType(str(a).upper()))
            except ValueError:
                activities.append(ActivityType.OTHER)
        if not activities:
            activities = [ActivityType.OTHER]

        return MessageContext(
            project_name=d.get("project_name") or None,
            activities=activities,
            actions=[str(a) for a in (d.get("actions") or [])],
            goal=d.get("goal", ""),
        )

    @staticmethod
    def fallback() -> "MessageContext":
        return MessageContext(project_name=None, activities=[ActivityType.OTHER], actions=[], goal="")


def _strip_fences(text: str) -> str:
    """Remove markdown code fences that models sometimes add despite instructions."""
    text = text.strip()
    text = re.sub(r"^```[a-zA-Z]*\n?", "", text)
    text = re.sub(r"\n?```$", "", text)
    return text.strip()


class SemanticAnalyzer:
    def __init__(self, loop: asyncio.AbstractEventLoop | None = None) -> None:
        super().__init__()
        self._loop = loop or asyncio.new_event_loop()
        self.base_model = DEFAULT_MODEL
        self._client: CopilotClient | None = None

    def analyze(self, text: str) -> MessageContext:
        return self._loop.run_until_complete(self._analyze_async(text))

    async def _analyze_async(self, text: str) -> MessageContext:
        if self._client is None:
            self._client = CopilotClient(SubprocessConfig(github_token=COPILOT_TOKEN))
            await self._client.start()

        # Fresh session per call — matches VS Code stateless agent invocation behavior.
        # system_message replace mode injects the agent prompt directly, bypassing the CLI's
        # default system prompt entirely. available_tools=[] prevents any tool execution.
        session = await self._client.create_session(
            model=self.base_model,
            on_permission_request=PermissionHandler.approve_all,
            streaming=True,
            mcp_servers=None,
            available_tools=[],
            reasoning_effort="low",
            system_message={"mode": "replace", "content": _load_agent_prompt()},
        )

        result_event = await session.send_and_wait(
            f"<message>{text}</message>",
            timeout=120,
        )
        content = ""
        if result_event is not None:
            raw = getattr(result_event.data, "content", None)
            if isinstance(raw, str):
                content = raw
            elif raw is not None:
                content = str(raw)

        try:
            data = json.loads(_strip_fences(content))
            return MessageContext.from_dict(data)
        except Exception:
            logger.warning(f"SemanticAnalyzer failed to parse response: {content!r}")
            return MessageContext.fallback()


if __name__ == "__main__":
    analyzer = SemanticAnalyzer()
    for _ in range(5):
        context = analyzer.analyze("Budu pracovat na projektu tony_ai a chci abys udelal research aktualnich zmen")
        print(f"Project:    {context.project_name}")
        print(f"Activities: {[a.value for a in context.activities]}")
        print(f"Actions:    {context.actions}")
        print(f"Goal:       {context.goal}")
        print(f"Best model: {context.get_best_model()}")
    time.sleep(1)