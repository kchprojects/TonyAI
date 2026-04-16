import os
from unittest.mock import AsyncMock, MagicMock, patch

os.environ.setdefault("SLACK_BOT_TOKEN", "xoxb-test")
os.environ.setdefault("SLACK_APP_TOKEN", "xapp-test")

from tony_ai.slack import handlers


class FakeApp:
    """Minimal Bolt App stub that captures handlers registered via app.event()."""

    def __init__(self) -> None:
        self.message_handler = None
        self.mention_handler = None

    def event(self, name):
        def decorator(func):
            if name == "message":
                self.message_handler = func
            elif name == "app_mention":
                self.mention_handler = func
            return func

        return decorator


def _make_client(placeholder_ts: str = "0.placeholder") -> MagicMock:
    """Return a mock Slack client whose chat_postMessage returns a fixed ts."""
    client = MagicMock()
    client.chat_postMessage.return_value = {"ts": placeholder_ts}
    return client


# ---------------------------------------------------------------------------
# Baseline: normal (non-$code) message uses agent and updates placeholder
# ---------------------------------------------------------------------------

def test_normal_message_uses_agent_and_updates_placeholder() -> None:
    app = FakeApp()
    handlers.register_handlers(app)
    client = _make_client("ph.001")

    with patch.object(handlers._agent, "send", AsyncMock(return_value="agent-reply")) as send_mock:
        app.message_handler(
            {"text": "hello world", "ts": "1.001", "channel": "C001"},
            None,  # say is not used by _handle_message
            client,
        )

    send_mock.assert_awaited_once()
    client.chat_update.assert_called_once_with(
        channel="C001", ts="ph.001", text="agent-reply"
    )


def test_app_mention_uses_agent_and_updates_placeholder() -> None:
    app = FakeApp()
    handlers.register_handlers(app)
    client = _make_client("ph.002")

    with patch.object(handlers._agent, "send", AsyncMock(return_value="mention-reply")) as send_mock:
        app.mention_handler(
            {"text": "@tony ping", "ts": "2.001", "channel": "C002"},
            None,
            client,
        )

    send_mock.assert_awaited_once()
    client.chat_update.assert_called_once_with(
        channel="C002", ts="ph.002", text="mention-reply"
    )


# ---------------------------------------------------------------------------
# $code happy path: start → send → commit → finish, PR URL in final message
# ---------------------------------------------------------------------------

def test_code_happy_path_call_order_and_pr_message() -> None:
    app = FakeApp()
    handlers.register_handlers(app)
    client = _make_client("ph.003")

    call_order: list[str] = []

    def fake_start(desc):
        call_order.append("start_request")
        return {"branch": "feat/test-branch"}

    def fake_commit(desc):
        call_order.append("commit_task")
        return {"sha": "abc123"}

    def fake_finish(desc, body):
        call_order.append("finish_request")
        return {"pr_url": "https://github.com/owner/repo/pull/99"}

    with (
        patch.object(handlers, "start_request", side_effect=fake_start),
        patch.object(handlers, "commit_task", side_effect=fake_commit),
        patch.object(handlers, "finish_request", side_effect=fake_finish),
        patch.object(handlers, "_load_state", return_value={}),
        patch.object(handlers, "_save_state"),
        patch.object(handlers._agent, "send", AsyncMock(return_value="done")) as send_mock,
    ):
        app.message_handler(
            {"text": "$code add logging", "ts": "3.001", "channel": "C003"},
            None,
            client,
        )

    assert call_order == ["start_request", "commit_task", "finish_request"]
    send_mock.assert_awaited_once()

    posted_texts = [c.kwargs.get("text", "") for c in client.chat_postMessage.call_args_list]
    assert any("PR created" in t and "https://github.com" in t for t in posted_texts)


# ---------------------------------------------------------------------------
# $code idempotent: active branch in state → start_request is NOT called
# ---------------------------------------------------------------------------

def test_code_idempotent_branch_skips_start_request() -> None:
    app = FakeApp()
    handlers.register_handlers(app)
    client = _make_client("ph.004")

    with (
        patch.object(handlers, "start_request") as start_mock,
        patch.object(handlers, "commit_task", return_value={"sha": "def456"}),
        patch.object(handlers, "finish_request", return_value={"pr_url": "https://github.com/owner/repo/pull/100"}),
        patch.object(handlers, "_load_state", return_value={"branch": "feat/existing-branch"}),
        patch.object(handlers, "_save_state"),
        patch.object(handlers._agent, "send", AsyncMock(return_value="done")),
    ):
        app.message_handler(
            {"text": "$code fix bug", "ts": "4.001", "channel": "C004"},
            None,
            client,
        )

    start_mock.assert_not_called()


# ---------------------------------------------------------------------------
# $code start failure: aborts agent send, commit, and finish
# ---------------------------------------------------------------------------

def test_code_start_failure_aborts_workflow() -> None:
    app = FakeApp()
    handlers.register_handlers(app)
    client = _make_client("ph.005")

    with (
        patch.object(handlers, "start_request", return_value={"error": "git init failed"}),
        patch.object(handlers, "commit_task") as commit_mock,
        patch.object(handlers, "finish_request") as finish_mock,
        patch.object(handlers, "_load_state", return_value={}),
        patch.object(handlers, "_save_state"),
        patch.object(handlers._agent, "send", AsyncMock(return_value="done")) as send_mock,
    ):
        app.message_handler(
            {"text": "$code refactor", "ts": "5.001", "channel": "C005"},
            None,
            client,
        )

    send_mock.assert_not_awaited()
    commit_mock.assert_not_called()
    finish_mock.assert_not_called()

    posted_texts = [c.kwargs.get("text", "") for c in client.chat_postMessage.call_args_list]
    assert any("Failed to start branch" in t for t in posted_texts)


# ---------------------------------------------------------------------------
# $code commit failure: aborts finish_request
# ---------------------------------------------------------------------------

def test_code_commit_failure_aborts_finish_request() -> None:
    app = FakeApp()
    handlers.register_handlers(app)
    client = _make_client("ph.006")

    with (
        patch.object(handlers, "start_request", return_value={"branch": "feat/branch-x"}),
        patch.object(handlers, "commit_task", return_value={"error": "nothing to commit"}),
        patch.object(handlers, "finish_request") as finish_mock,
        patch.object(handlers, "_load_state", return_value={}),
        patch.object(handlers, "_save_state"),
        patch.object(handlers._agent, "send", AsyncMock(return_value="done")),
    ):
        app.message_handler(
            {"text": "$code add tests", "ts": "6.001", "channel": "C006"},
            None,
            client,
        )

    finish_mock.assert_not_called()

    posted_texts = [c.kwargs.get("text", "") for c in client.chat_postMessage.call_args_list]
    assert any("Commit failed" in t for t in posted_texts)


# ---------------------------------------------------------------------------
# $code nothing_to_commit: PR skipped, state cleared, no finish_request call
# ---------------------------------------------------------------------------

def test_code_nothing_to_commit_skips_pr() -> None:
    app = FakeApp()
    handlers.register_handlers(app)
    client = _make_client("ph.007")

    save_mock = MagicMock()

    with (
        patch.object(handlers, "start_request", return_value={"branch": "feat/branch-y"}),
        patch.object(handlers, "commit_task", return_value={"status": "nothing_to_commit"}),
        patch.object(handlers, "finish_request") as finish_mock,
        patch.object(handlers, "_load_state", return_value={}),
        patch.object(handlers, "_save_state", save_mock),
        patch.object(handlers._agent, "send", AsyncMock(return_value="done")),
    ):
        app.message_handler(
            {"text": "$code refactor utils", "ts": "7.001", "channel": "C007"},
            None,
            client,
        )

    finish_mock.assert_not_called()
    # State must be cleared even when there's nothing to commit
    save_mock.assert_called_with({})

    posted_texts = [c.kwargs.get("text", "") for c in client.chat_postMessage.call_args_list]
    assert any("skipping PR" in t for t in posted_texts)


# ---------------------------------------------------------------------------
# $code finish_request failure: error message posted, state NOT cleared
# ---------------------------------------------------------------------------

def test_code_finish_request_error_handling() -> None:
    app = FakeApp()
    handlers.register_handlers(app)
    client = _make_client("ph.008")

    save_mock = MagicMock()

    with (
        patch.object(handlers, "start_request", return_value={"branch": "feat/branch-z"}),
        patch.object(handlers, "commit_task", return_value={"sha": "ghi789"}),
        patch.object(handlers, "finish_request", return_value={"error": "gh CLI not found"}),
        patch.object(handlers, "_load_state", return_value={}),
        patch.object(handlers, "_save_state", save_mock),
        patch.object(handlers._agent, "send", AsyncMock(return_value="done")),
    ):
        app.message_handler(
            {"text": "$code add feature", "ts": "8.001", "channel": "C008"},
            None,
            client,
        )

    # State must NOT be wiped when the PR creation failed
    save_mock.assert_not_called()

    posted_texts = [c.kwargs.get("text", "") for c in client.chat_postMessage.call_args_list]
    assert any("PR creation failed" in t for t in posted_texts)


# ---------------------------------------------------------------------------
# Non-code message: no git workflow calls whatsoever
# ---------------------------------------------------------------------------

def test_non_code_message_no_git_calls() -> None:
    app = FakeApp()
    handlers.register_handlers(app)
    client = _make_client("ph.009")

    with (
        patch.object(handlers, "start_request") as start_mock,
        patch.object(handlers, "commit_task") as commit_mock,
        patch.object(handlers, "finish_request") as finish_mock,
        patch.object(handlers, "_save_state") as save_mock,
        patch.object(handlers._agent, "send", AsyncMock(return_value="hi there")),
    ):
        app.message_handler(
            {"text": "hello, how are you?", "ts": "9.001", "channel": "C009"},
            None,
            client,
        )

    start_mock.assert_not_called()
    commit_mock.assert_not_called()
    finish_mock.assert_not_called()
    save_mock.assert_not_called()

    # Agent reply must reach the placeholder update
    client.chat_update.assert_called_once()
    _, kwargs = client.chat_update.call_args
    assert kwargs.get("text") == "hi there"
