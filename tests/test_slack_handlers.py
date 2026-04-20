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


def test_normal_message_uses_agent_and_updates_placeholder() -> None:
    app = FakeApp()
    handlers.register_handlers(app)
    client = _make_client("ph.001")

    with patch.object(handlers._agent, "send", AsyncMock(return_value="agent-reply")) as send_mock:
        app.message_handler(
            {"text": "hello world", "ts": "1.001", "channel": "C001"},
            None,
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


def test_code_happy_path_commits_and_posts_success_message() -> None:
    app = FakeApp()
    handlers.register_handlers(app)
    client = _make_client("ph.003")

    with (
        patch.object(handlers, "commit_task", return_value={"status": "committed", "branch": "dev"}),
        patch.object(handlers._agent, "send", AsyncMock(return_value="done")) as send_mock,
    ):
        app.message_handler(
            {"text": "$code add logging", "ts": "3.001", "channel": "C003"},
            None,
            client,
        )

    send_mock.assert_awaited_once()
    posted_texts = [c.kwargs.get("text", "") for c in client.chat_postMessage.call_args_list]
    assert any("Changes committed on `dev`." in t for t in posted_texts)


def test_code_commit_failure_stops_workflow() -> None:
    app = FakeApp()
    handlers.register_handlers(app)
    client = _make_client("ph.004")

    with (
        patch.object(handlers, "commit_task", return_value={"error": "push failed"}),
        patch.object(handlers._agent, "send", AsyncMock(return_value="done")) as send_mock,
    ):
        app.message_handler(
            {"text": "$code add tests", "ts": "4.001", "channel": "C004"},
            None,
            client,
        )

    send_mock.assert_awaited_once()
    posted_texts = [c.kwargs.get("text", "") for c in client.chat_postMessage.call_args_list]
    assert any("Commit failed" in t for t in posted_texts)
    assert not any("Changes committed on" in t for t in posted_texts)


def test_code_nothing_to_commit_posts_message() -> None:
    app = FakeApp()
    handlers.register_handlers(app)
    client = _make_client("ph.005")

    with (
        patch.object(handlers, "commit_task", return_value={"status": "nothing_to_commit"}),
        patch.object(handlers._agent, "send", AsyncMock(return_value="done")),
    ):
        app.message_handler(
            {"text": "$code refactor utils", "ts": "5.001", "channel": "C005"},
            None,
            client,
        )

    posted_texts = [c.kwargs.get("text", "") for c in client.chat_postMessage.call_args_list]
    assert any("No changes to commit." in t for t in posted_texts)


def test_non_code_message_no_git_calls() -> None:
    app = FakeApp()
    handlers.register_handlers(app)
    client = _make_client("ph.006")

    with (
        patch.object(handlers, "commit_task") as commit_mock,
        patch.object(handlers._agent, "send", AsyncMock(return_value="hi there")),
    ):
        app.message_handler(
            {"text": "hello, how are you?", "ts": "6.001", "channel": "C006"},
            None,
            client,
        )

    commit_mock.assert_not_called()
    client.chat_update.assert_called_once()
    _, kwargs = client.chat_update.call_args
    assert kwargs.get("text") == "hi there"


def test_tony_ai_code_intent_without_dollar_code_posts_recommendation() -> None:
    app = FakeApp()
    handlers.register_handlers(app)
    client = _make_client("ph.007")

    with (
        patch.object(handlers, "commit_task") as commit_mock,
        patch.object(handlers._agent, "send", AsyncMock(return_value="nope")) as send_mock,
    ):
        app.message_handler(
            {"text": "fix the bug in tony_ai config", "ts": "7.001", "channel": "C007"},
            None,
            client,
        )

    send_mock.assert_not_awaited()
    commit_mock.assert_not_called()

    posted_texts = [c.kwargs.get("text", "") for c in client.chat_postMessage.call_args_list]
    assert any("$code" in t for t in posted_texts), f"Expected $code recommendation, got: {posted_texts}"


def test_non_tony_ai_code_intent_proceeds_as_normal_chat() -> None:
    app = FakeApp()
    handlers.register_handlers(app)
    client = _make_client("ph.008")

    with (
        patch.object(handlers, "commit_task") as commit_mock,
        patch.object(handlers._agent, "send", AsyncMock(return_value="chat reply")) as send_mock,
    ):
        app.message_handler(
            {"text": "fix the bug in my Django app", "ts": "8.001", "channel": "C008"},
            None,
            client,
        )

    send_mock.assert_awaited_once()
    commit_mock.assert_not_called()

    client.chat_update.assert_called_once()
    _, kwargs = client.chat_update.call_args
    assert kwargs.get("text") == "chat reply"
