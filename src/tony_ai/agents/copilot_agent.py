from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any
from pathlib import Path as StdPath
from copilot import CopilotClient
from copilot.client import SubprocessConfig
from copilot.generated.session_events import SessionEventType
from copilot.session import MCPLocalServerConfig, PermissionHandler

from tony_ai.config import COPILOT_TOKEN, DEFAULT_MODEL, DEFAULT_PRO_MODEL
from tony_ai.llm.provider import get_provider
from tony_ai.mcp.server import get_mcp_servers
logger = logging.getLogger(__name__)


class CopilotAgent:
    def __init__(self) -> None:
        self._client: CopilotClient | None = None
        self._sessions: dict[str, Any] = {}
        self._pro_sessions: dict[str, Any] = {}
        self._provider = get_provider()
        self._agent_md = ""
        self._additional_instructions = ""

        self._pro_model = DEFAULT_PRO_MODEL
        self._base_model = DEFAULT_MODEL
    
    @property
    def pro_model(self) -> str:
        return self._pro_model
    @pro_model.setter
    def pro_model(self, value: str) -> None:
        self._pro_model = value
    
    @property
    def base_model(self) -> str:
        return self._base_model
    @base_model.setter
    def base_model(self, value: str) -> None:
        self._base_model = value

    @property
    def name(self) -> str:
        return str(self.__class__.__name__)
    
    async def start(self) -> None:
        if self._client is None:
            logger.info(f"starting {self.name}")
            self._client = CopilotClient(SubprocessConfig(github_token=COPILOT_TOKEN))
            await self._client.start()
            logger.info(f"{self.name} started successfully")

    async def stop(self) -> None:
        if self._client is not None:
            logger.info(f"stopping {self.name}")
            await self._client.stop()
            self._client = None
            self._sessions.clear()
            logger.info(f"{self.name} stopped")

    async def send(
        self,
        thread_ts: str,
        text: str,
        on_delta: Callable[[str], None] | None = None,
        on_event: Callable[[Any], None] | None = None,
        pro: bool = False,
    ) -> str:
        logger.info(f"send() called: thread_ts={thread_ts}, text={text[:50]}..., pro={pro}")
        session = await self._get_or_create_session(thread_ts, pro=pro)
        logger.debug(f"got session for thread {thread_ts}")

        unsubs: list[Callable[[], None]] = []

        if on_delta is not None:
            def delta_handler(event: Any) -> None:
                if event.type == SessionEventType.ASSISTANT_MESSAGE_DELTA:
                    delta = getattr(event.data, "delta_content", None)
                    if delta:
                        on_delta(delta)
            unsubs.append(session.on(delta_handler))

        if on_event is not None:
            unsubs.append(session.on(on_event))

        try:
            logger.debug("sending message via send_and_wait")
            result_event = await session.send_and_wait(text, timeout=60*60*12) # 12 hour timeout for long-running tasks
            content = ""
            if result_event is not None:
                raw = getattr(result_event.data, "content", None)
                if isinstance(raw, str):
                    content = raw
                elif raw is not None:
                    content = str(raw)
            logger.info(f"send() complete: response length={len(content)}")
            return content
        finally:
            for unsub in unsubs:
                unsub()
        
    def set_agent_md(self, agent_md: str) -> None:
        # This is a no-op for CopilotAgent since the system prompt is fixed.
        logger.warning(f"set_agent_md() called on {self.name}, but this agent uses a fixed system prompt. Ignoring.")
        self._agent_md = agent_md        
    
    def set_additional_instructions(self, instructions: str) -> None:
        # This is a no-op for CopilotAgent since the system prompt is fixed.
        logger.warning(f"set_additional_instructions() called on {self.name}, but this agent uses a fixed system prompt. Ignoring.")
        self._additional_instructions = instructions

    def get_system_prompt(self) -> str:
        return f"{self._agent_md}\n\n{self._additional_instructions}"
    
    async def _get_or_create_session(self, thread_ts: str, pro: bool = False) -> Any:
        await self.start()
        store = self._pro_sessions if pro else self._sessions
        model = self._pro_model if pro else self._base_model
        if thread_ts not in store:
            logger.info(f"creating new {'pro ' if pro else ''} session for thread {thread_ts} with model={model}")
            if self._client is None:
                raise RuntimeError("Copilot client failed to initialize")
            extra = self._provider.copilot_session_kwargs()
            logger.debug(f"provider extra kwargs: {extra}")
            store[thread_ts] = await self._client.create_session(
                model=model,
                on_permission_request=PermissionHandler.approve_all,
                streaming=True,
                infinite_sessions={"enabled": True},
                system_message={"mode": "replace", "content": self.get_system_prompt()},
                mcp_servers=get_mcp_servers(),
                **extra,
            )
            logger.info(f"session created for thread {thread_ts}")
        else:
            logger.debug(f"using existing {'pro ' if pro else ''}session for thread {thread_ts}")
        return store[thread_ts]

