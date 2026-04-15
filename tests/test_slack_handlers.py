import os
from unittest.mock import AsyncMock, patch

os.environ.setdefault("SLACK_BOT_TOKEN", "xoxb-test")
os.environ.setdefault("SLACK_APP_TOKEN", "xapp-test")

from src.slack import handlers


class FakeApp:
    def __init__(self) -> None:
        self.dm_handler = None
        self.mention_handler = None

    def message(self, _pattern):
        def decorator(func):
            self.dm_handler = func
            return func

        return decorator

    def event(self, name):
        def decorator(func):
            if name == "app_mention":
                self.mention_handler = func
            return func

        return decorator


def test_dm_uses_tony_agent_and_replies_in_thread() -> None:
    app = FakeApp()
    handlers.register_handlers(app)
    say_calls: list[tuple[str, str]] = []

    def say(*, text: str, thread_ts: str) -> None:
        say_calls.append((text, thread_ts))

    with patch.object(handlers._agent, "send", AsyncMock(return_value="tony-reply")) as send_mock:
        app.dm_handler(
            {"text": "hello", "ts": "1.001", "thread_ts": "1.000"},
            say,
            None,
        )

    send_mock.assert_awaited_once_with("1.000", "hello")
    assert say_calls == [("tony-reply", "1.000")]


def test_app_mention_uses_tony_agent_and_defaults_thread_ts() -> None:
    app = FakeApp()
    handlers.register_handlers(app)
    say_calls: list[tuple[str, str]] = []

    def say(*, text: str, thread_ts: str) -> None:
        say_calls.append((text, thread_ts))

    with patch.object(handlers._agent, "send", AsyncMock(return_value="mention-reply")) as send_mock:
        app.mention_handler(
            {"text": "@tony ping", "ts": "2.001"},
            say,
        )

    send_mock.assert_awaited_once_with("2.001", "@tony ping")
    assert say_calls == [("mention-reply", "2.001")]
