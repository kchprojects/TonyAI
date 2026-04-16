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
from tony_ai.monitoring import StateTracker

logger = logging.getLogger(__name__)

# Module-level singleton — created once, shared across all TonyAgent instances.
_state = StateTracker()

_REPO_ROOT = StdPath(__file__).parent.parent.parent.parent
_VENV_PYTHON = str(_REPO_ROOT / ".venv" / "Scripts" / "python.exe")

with open(_REPO_ROOT / ".github" / "agents" / "tony.agent.md") as f:
    SYSTEM_PROMPT = f.read()

SYSTEM_PROMPT += "\n\n ***Additional Instructions*** \n\n" + f"You CANNOT access files outside of {_REPO_ROOT}. \nAll file paths are relative to {_REPO_ROOT}. \n Before doing any destructive actions like deleting files, always VERIFY with the user."

_MCP_SERVERS: dict[str, MCPLocalServerConfig] = {
    "tony-desktop": MCPLocalServerConfig(
        type="stdio",
        command=_VENV_PYTHON,
        args=[str(_REPO_ROOT / "src" / "tony_ai" / "mcp" / "server.py")],
        tools=["*"],
        cwd=str(_REPO_ROOT),
    )
}

class TonyAgent:
    def __init__(self) -> None:
        self._client: CopilotClient | None = None
        self._sessions: dict[str, Any] = {}
        self._pro_sessions: dict[str, Any] = {}
        self._provider = get_provider()

    async def start(self) -> None:
        if self._client is None:
            logger.info("starting TonyAgent")
            self._client = CopilotClient(SubprocessConfig(github_token=COPILOT_TOKEN))
            await self._client.start()
            _state.mark_started()
            logger.info("TonyAgent started successfully")

    async def stop(self) -> None:
        if self._client is not None:
            logger.info("stopping TonyAgent")
            await self._client.stop()
            self._client = None
            self._sessions.clear()
            logger.info("TonyAgent stopped")

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
            _state.session_busy(thread_ts, text[:60])
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
            _state.session_idle(thread_ts)
            for unsub in unsubs:
                unsub()

    async def _get_or_create_session(self, thread_ts: str, pro: bool = False) -> Any:
        await self.start()
        store = self._pro_sessions if pro else self._sessions
        model = DEFAULT_PRO_MODEL if pro else DEFAULT_MODEL
        if thread_ts not in store:
            logger.info(f"creating new {'pro ' if pro else ''}session for thread {thread_ts} with model={model}")
            if self._client is None:
                raise RuntimeError("Copilot client failed to initialize")
            extra = self._provider.copilot_session_kwargs()
            logger.debug(f"provider extra kwargs: {extra}")
            store[thread_ts] = await self._client.create_session(
                model=model,
                on_permission_request=PermissionHandler.approve_all,
                streaming=True,
                infinite_sessions={"enabled": True},
                system_message={"text": SYSTEM_PROMPT},
                mcp_servers=_MCP_SERVERS,
                **extra,
            )
            _state.session_created(thread_ts, model, pro)
            logger.info(f"session created for thread {thread_ts}")
        else:
            logger.debug(f"using existing {'pro ' if pro else ''}session for thread {thread_ts}")
        return store[thread_ts]

    async def reset_session(self, thread_ts: str) -> None:
        """Drop the session for a single thread so the next message starts fresh."""
        for store in (self._sessions, self._pro_sessions):
            session = store.pop(thread_ts, None)
            if session is not None:
                try:
                    await session.close()
                except Exception:
                    logger.debug(f"error closing session {thread_ts}", exc_info=True)
        _state.session_removed(thread_ts)
        logger.info(f"session reset for thread {thread_ts}")

    async def reset(self) -> None:
        """Drop all active sessions so every thread starts from scratch."""
        for thread_ts in list(self._sessions):
            await self.reset_session(thread_ts)
        logger.info("all sessions reset")

