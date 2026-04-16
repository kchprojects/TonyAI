import asyncio
import json
import logging
import os
import re
import sys
import time
from slack_bolt import App

from tony_ai.mcp.git_workflow import (
    start_request,
    commit_task,
    finish_request,
    _load_state,
    _save_state,
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

from copilot.generated.session_events import SessionEventType
from tony_ai.agents.tony import TonyAgent

_agent = TonyAgent()
_loop = asyncio.new_event_loop()
_pro_threads: set[str] = set()  # threads with pro model active

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

        # tool_call_id -> message ts
        self._tool_ts: dict[str, str] = {}

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
            elif t == SessionEventType.TOOL_EXECUTION_PROGRESS:
                self._on_tool_progress(event.data)
            elif t == SessionEventType.TOOL_EXECUTION_COMPLETE:
                self._on_tool_complete(event.data)
        except Exception as exc:
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
        return # skip tool start messages for now to reduce noise; can re-enable if we want more feedback on tool calls
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
        text = f"🔧 *{tool_name}*{line2}"
        resp = self._post(text)
        if resp and tool_call_id:
            self._tool_ts[tool_call_id] = resp["ts"]

    def _on_tool_progress(self, data) -> None:
        return # skip progress updates for now to reduce noise; can re-enable if we want more feedback on long-running tools
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
        return # skip updates on completion for now to reduce noise; can re-enable if we want more feedback on tool results
        tool_call_id = getattr(data, "tool_call_id", None)
        ts = self._tool_ts.get(tool_call_id) if tool_call_id else None
        if not ts:
            return
        tool_name = (
            getattr(data, "mcp_tool_name", None)
            or getattr(data, "tool_name", None)
            or "tool"
        )
        result = getattr(data, "result", None)
        kind = str(getattr(result, "kind", "")) if result else ""
        icon = "✅" if "success" in kind.lower() or kind == "" else "❌"
        content = getattr(result, "content", None) if result else None
        snippet = f"\n`{content[:300]}`" if content else ""
        self._update(ts, f"{icon} *{tool_name}*{snippet}")

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

# ---------------------------------------------------------------------------
# Text-intent fallback: detect common code-change requests without $code prefix
# ---------------------------------------------------------------------------

_CODE_INTENT_RE = re.compile(
    r'\b(?:fix|add|implement|update|refactor|change|modify|create|delete|remove)\b',
    re.IGNORECASE,
)


def _is_code_change_intent(text: str) -> bool:
    """Return True when text looks like a code-change request (no $-command prefix)."""
    if text.startswith("$"):
        return False
    return bool(_CODE_INTENT_RE.search(text))


_TONY_AI_RE = re.compile(
    r'\b(?:TonyAI|tony[\s_]ai)\b|src/tony_ai|pyproject\.toml|README',
    re.IGNORECASE,
)


def _is_tony_ai_project(text: str) -> bool:
    """Return True when text refers to the TonyAI project by keyword or path heuristic."""
    return bool(_TONY_AI_RE.search(text))


def _handle_message(event, say, client) -> None:
    """Handle DMs and messages"""
    if event.get("bot_id"):
        return  # Ignore bot messages
    
    text = event.get("text", "")
    channel = event.get("channel", "")
    print(f"\n✅ MESSAGE EVENT: '{text}'")
    print(f"   Channel type: {channel}")
    logger.info(f"Message in {channel}: {text}")
    
    thread_ts = event.get("thread_ts") or event["ts"]

    # Handle $restart without showing a placeholder
    if text.startswith("$restart"):
        executable = sys.executable + ".exe"
        logger.info(f"Restarting process with: {executable} {' '.join(sys.argv)}")
        os.execv(executable, [executable] + sys.argv)

    # Handle $pro — toggle pro model for this thread (sticky)
    if text.strip() == "$pro":
        if thread_ts in _pro_threads:
            _pro_threads.discard(thread_ts)
            client.chat_postMessage(channel=channel, thread_ts=thread_ts, text="_Pro mode off._")
        else:
            _pro_threads.add(thread_ts)
            client.chat_postMessage(channel=channel, thread_ts=thread_ts, text="_Pro mode on._")
        return

    # Non-$code code-change intent targeting TonyAI → recommend $code instead of executing
    if _is_code_change_intent(text) and _is_tony_ai_project(text):
        client.chat_postMessage(
            channel=channel,
            thread_ts=thread_ts,
            text=f"💡 That looks like a TonyAI code change. Please prefix with `$code` to trigger the managed git workflow, e.g.:\n`$code {text}`",
        )
        return

    # Handle $code (explicit) — deterministic git workflow
    if text.startswith("$code"):
        parts = text.split(None, 1)
        description = parts[1].strip() if len(parts) > 1 else "code change"

        placeholder = client.chat_postMessage(
            channel=channel,
            thread_ts=thread_ts,
            text="_Thinking..._",
        )
        placeholder_ts = placeholder["ts"]
        stream = SlackEventStream(client, channel, thread_ts, placeholder_ts)

        # Idempotency: resume on active branch if one already exists
        state = _load_state()
        active_branch = state.get("branch")

        if not active_branch:
            client.chat_postMessage(
                channel=channel, thread_ts=thread_ts,
                text=f"_Starting branch for: {description}_",
            )
            start_result = start_request(description)
            if "error" in start_result:
                client.chat_postMessage(
                    channel=channel, thread_ts=thread_ts,
                    text=f"❌ Failed to start branch: {start_result['error']}",
                )
                return
            active_branch = start_result["branch"]
            client.chat_postMessage(
                channel=channel, thread_ts=thread_ts,
                text=f"_Branch `{active_branch}` created._",
            )
        else:
            client.chat_postMessage(
                channel=channel, thread_ts=thread_ts,
                text=f"_Resuming on existing branch `{active_branch}`._",
            )

        # Run the agent
        try:
            response = _loop.run_until_complete(
                _agent.send(thread_ts, description, on_event=stream.handle, pro=thread_ts in _pro_threads)
            )
        except Exception as exc:
            logger.error(f"$code agent error: {exc}", exc_info=True)
            client.chat_postMessage(
                channel=channel, thread_ts=thread_ts,
                text=f"❌ Agent failed: {exc}",
            )
            return

        try:
            client.chat_update(channel=channel, ts=placeholder_ts, text=response)
        except Exception as exc:
            logger.debug(f"chat_update failed: {exc}")

        # Commit
        client.chat_postMessage(
            channel=channel, thread_ts=thread_ts, text="_Committing changes..._"
        )
        commit_result = commit_task(description)
        if "error" in commit_result:
            client.chat_postMessage(
                channel=channel, thread_ts=thread_ts,
                text=f"❌ Commit failed: {commit_result['error']}",
            )
            return

        if commit_result.get("status") == "nothing_to_commit":
            client.chat_postMessage(
                channel=channel, thread_ts=thread_ts,
                text="_No changes to commit — skipping PR._",
            )
            _save_state({})
            return

        # Open PR
        client.chat_postMessage(
            channel=channel, thread_ts=thread_ts, text="_Opening PR..._"
        )
        pr_result = finish_request(description, f"Automated PR for: {description}")
        if "error" in pr_result:
            client.chat_postMessage(
                channel=channel, thread_ts=thread_ts,
                text=f"❌ PR creation failed: {pr_result['error']}",
            )
            return

        # Clear workflow state so the next $code starts fresh
        _save_state({})

        pr_url = pr_result.get("pr_url", "")
        client.chat_postMessage(
            channel=channel, thread_ts=thread_ts,
            text=f"✅ PR created: {pr_url}",
        )
        return

    # Post a placeholder while generating the response
    placeholder = client.chat_postMessage(
        channel=channel,
        thread_ts=thread_ts,
        text="_Thinking..._",
    )
    placeholder_ts = placeholder["ts"]
    stream = SlackEventStream(client, channel, thread_ts, placeholder_ts)

    if text.startswith("$file"):
        # Parse optional title: "$file My Title" → title = "My Title"
        parts = text.split(None, 1)
        title = parts[1].strip() if len(parts) > 1 else None
        title_clause = f" Title: «{title}»." if title else ""
        send_text = (
            f"$file command received.{title_clause} "
            "Summarize this conversation thread and file it to the wiki under conversations/. "
            "Use today's date for the filename (conversations/YYYY-MM-DD-title.md). "
            "Then confirm with the filename you used."
        )
    else:
        send_text = text

    response = _loop.run_until_complete(_agent.send(thread_ts, send_text, on_event=stream.handle, pro=thread_ts in _pro_threads))
    logger.info(f"Agent response: {response}")

    try:
        client.chat_update(
            channel=channel,
            ts=placeholder_ts,
            text=response,
        )
        print(f"   ✅ Response sent")
    except Exception as e:
        print(f"   ❌ Error sending response: {e}")
        logger.error(f"Error: {e}", exc_info=True)

def register_handlers(app: App) -> None:
    @app.event("message")
    def handle_message(event, say, client):
        _handle_message(event, say, client)

    @app.event("app_mention")
    def handle_mention(event, say, client):
        _handle_message(event, say, client)