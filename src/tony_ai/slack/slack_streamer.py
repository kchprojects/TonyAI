import json
import time
from copilot.generated.session_events import SessionEventType
from tony_ai.mcp.git_workflow import (
    commit_task,
)

from logging import getLogger
logger = getLogger(__name__)
logger.setLevel("INFO")


_REASONING_THROTTLE_S = 3.0   # min seconds between reasoning message updates
_REASONING_MAX_CHARS  = 2800  # max chars shown in reasoning block

class SlackEventStream:
    """Streams chain-of-thought, intent and tool events to a Slack thread."""

    def __init__(self, client, channel: str, thread_ts: str, placeholder_ts: str) -> None:
        self._client = client
        self._channel = channel
        self._thread_ts = thread_ts
        self._placeholder_ts = placeholder_ts

        self._reasoning_buf = ""
        self._reasoning_ts: str | None = None
        self._reasoning_last_flush: float = 0.0

        # tool_call_id -> message ts; _tool_post_ts is the shared reused post
        self._tool_ts: dict[str, str] = {}
        self._tool_post_ts: str | None = None
        self._agent_ts = {}

    # ------------------------------------------------------------------
    # Public handler — registered with session.on()
    # ------------------------------------------------------------------

    def handle(self, event) -> None:
        t = event.type
        try:
            if t == SessionEventType.ASSISTANT_INTENT:
                self._on_intent(event.data)
            elif t == SessionEventType.ASSISTANT_REASONING_DELTA:
                self._on_reasoning_delta(event.data)
            elif t == SessionEventType.ASSISTANT_REASONING:
                self._on_reasoning_complete(event.data)
            elif t == SessionEventType.TOOL_EXECUTION_START:
                self._on_tool_start(event.data)
            # elif t == SessionEventType.TOOL_EXECUTION_PROGRESS:
            #     self._on_tool_progress(event.data)
            elif t == SessionEventType.TOOL_EXECUTION_COMPLETE:
                self._on_tool_complete(event.data)
            elif t == SessionEventType.SUBAGENT_SELECTED:
                self._on_subagent_selected(event.data)
            elif t == SessionEventType.SUBAGENT_STARTED:
                self._on_subagent_started(event.data)
            elif t == SessionEventType.SUBAGENT_COMPLETED:
                self._on_subagent_completed(event.data)
            elif t == SessionEventType.SUBAGENT_FAILED:
                self._on_subagent_failed(event.data)
        except Exception as exc:
            print(f"Error in SlackEventStream.handle for event type {t}: {exc}")
            logger.debug(f"SlackEventStream.handle error: {exc}", exc_info=True)

    # ------------------------------------------------------------------
    # Internal handlers
    # ------------------------------------------------------------------

    def _on_intent(self, data) -> None:
        intent = getattr(data, "intent", None)
        if intent:
            self._update(self._placeholder_ts, f"💭 _{intent}_")

    def _on_reasoning_delta(self, data) -> None:
        delta = getattr(data, "reasoning_text", None) or getattr(data, "delta_content", None)
        if not delta:
            return
        self._reasoning_buf += delta
        if time.monotonic() - self._reasoning_last_flush >= _REASONING_THROTTLE_S:
            self._flush_reasoning()

    def _on_reasoning_complete(self, data) -> None:
        text = getattr(data, "reasoning_text", None)
        if text:
            self._reasoning_buf = text
        self._flush_reasoning(force=True)

    def _flush_reasoning(self, *, force: bool = False) -> None:
        if not self._reasoning_buf:
            return
        snippet = self._reasoning_buf[-_REASONING_MAX_CHARS:]
        truncated = len(self._reasoning_buf) > _REASONING_MAX_CHARS
        prefix = "…" if truncated else ""
        slack_text = f"🧠 *Chain of thought*\n```{prefix}{snippet}```"

        if self._reasoning_ts is None:
            resp = self._post(slack_text)
            if resp:
                self._reasoning_ts = resp["ts"]
        else:
            self._update(self._reasoning_ts, slack_text)
        self._reasoning_last_flush = time.monotonic()

    def _on_tool_start(self, data) -> None:
        tool_call_id = getattr(data, "tool_call_id", None)
        tool_name = (
            getattr(data, "mcp_tool_name", None)
            or getattr(data, "tool_name", None)
            or "tool"
        )
        args = getattr(data, "arguments", None)
        args_str = ""
        if args is not None:
            try:
                raw = json.dumps(args) if not isinstance(args, str) else args
                args_str = raw[:200]
            except Exception:
                args_str = str(args)[:200]

        line2 = f"\n`{args_str}`" if args_str else ""
        text = f"🔧 *{tool_name}* _(running…)_{line2}"

        if self._tool_post_ts:
            self._update(self._tool_post_ts, text)
            ts = self._tool_post_ts
        else:
            resp = self._post(text)
            ts = resp["ts"] if resp else None
            if ts:
                self._tool_post_ts = ts

        if tool_call_id and ts:
            self._tool_ts[tool_call_id] = ts

    def _on_tool_progress(self, data) -> None:
        tool_call_id = getattr(data, "tool_call_id", None)
        msg = getattr(data, "progress_message", None)
        if not (tool_call_id and msg and tool_call_id in self._tool_ts):
            return
        tool_name = (
            getattr(data, "mcp_tool_name", None)
            or getattr(data, "tool_name", None)
            or "tool"
        )
        self._update(self._tool_ts[tool_call_id], f"🔧 *{tool_name}* _(running…)_\n`{msg[:300]}`")

    def _on_tool_complete(self, data) -> None:
        tool_call_id = getattr(data, "tool_call_id", None)
        ts = self._tool_ts.get(tool_call_id) if tool_call_id else None

        tool_name = (
            getattr(data, "mcp_tool_name", None)
            or getattr(data, "tool_name", None)
            or "tool"
        )
        result = getattr(data, "result", None)
        success = getattr(data, "success", None)
        error = getattr(data, "error", None) or getattr(data, "error_reason", None)
        duration_ms = getattr(data, "duration_ms", None)

        # Determine icon: prefer explicit success flag on data, fall back to absence of error
        if success is True or (success is None and not error):
            icon = "✅"
        else:
            icon = "❌"

        # Build descriptive snippet from result
        content = getattr(result, "content", None) if result else None
        detailed = getattr(result, "detailed_content", None) if result else None
        kind = getattr(result, "kind", None) if result else None

        parts = []
        if content:
            parts.append(f"`{str(content)[:300]}`")
        if detailed and detailed != content:
            parts.append(f"_{str(detailed)[:200]}_")
        if kind:
            parts.append(f"kind: `{kind}`")
        if error:
            parts.append(f"⚠️ `{str(error)[:200]}`")
        if duration_ms is not None:
            parts.append(f"_{duration_ms}ms_")

        snippet = "\n" + " · ".join(parts) if parts else ""
        msg = f"{icon} *{tool_name}*{snippet}"

        logger.info(f"Tool complete: {tool_name} {icon} success={success} duration={duration_ms}ms error={error}")

        if ts:
            self._update(ts, msg)
            self._tool_post_ts = ts  # keep for next tool to reuse
        else:
            # No prior start message — post a new one and save for reuse
            resp = self._post(msg)
            if resp:
                self._tool_post_ts = resp["ts"]

    def _on_subagent_selected(self, data) -> None:
        name = getattr(data, "agent_display_name", None) or getattr(data, "agent_name", None) or "agent"
        resp = self._post(f"🤖 *{name}* _(selected…)_")
        logger.info(f"Subagent selected: {name}, response: {resp}")
        if resp:
            self._agent_ts[name] = resp["ts"]

    def _on_subagent_started(self, data) -> None:
        name = getattr(data, "agent_display_name", None) or getattr(data, "agent_name", None) or "agent"
        ts = self._agent_ts.get(name)
        logger.info(f"Subagent started: {name}, ts={ts}")
        if ts:
            self._update(ts, f"🤖 *{name}* _(running…)_")

    def _on_subagent_completed(self, data) -> None:
        name = getattr(data, "agent_display_name", None) or getattr(data, "agent_name", None) or "agent"
        ts = self._agent_ts.pop(name, None)
        duration = getattr(data, "duration_ms", None)
        calls = getattr(data, "total_tool_calls", None)
        detail = f" _{duration}ms, {calls} tool calls_" if duration is not None else ""
        text = f"✅ *{name}*{detail}"
        logger.info(f"Subagent completed: {text}")
        if ts:
            self._update(ts, text)
        else:
            self._post(text)

    def _on_subagent_failed(self, data) -> None:
        name = getattr(data, "agent_display_name", None) or getattr(data, "agent_name", None) or "agent"
        ts = self._agent_ts.pop(name, None)
        reason = getattr(data, "error_reason", None) or ""
        snippet = f"\n`{reason[:200]}`" if reason else ""
        text = f"❌ *{name}* failed{snippet}"
        logger.info(f"Subagent failed: {text}")
        if ts:
            self._update(ts, text)
        else:
            self._post(text)

    # ------------------------------------------------------------------
    # Slack helpers (never raise)
    # ------------------------------------------------------------------

    def _post(self, text: str):
        try:
            return self._client.chat_postMessage(
                channel=self._channel,
                thread_ts=self._thread_ts,
                text=text,
            )
        except Exception as exc:
            logger.debug(f"chat_postMessage failed: {exc}")
            return None

    def _update(self, ts: str, text: str) -> None:
        try:
            self._client.chat_update(channel=self._channel, ts=ts, text=text)
        except Exception as exc:
            logger.debug(f"chat_update failed: {exc}")

