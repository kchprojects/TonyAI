import os
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

os.environ.setdefault("SLACK_BOT_TOKEN", "xoxb-test")
os.environ.setdefault("SLACK_APP_TOKEN", "xapp-test")

from tony_ai.agents.tony import TonyAgent


@pytest.mark.asyncio
async def test_send_creates_session_and_streams_until_idle() -> None:
    agent = TonyAgent()

    callbacks: list = []
    session = MagicMock()
    session.on = MagicMock(side_effect=lambda cb: callbacks.append(cb))

    async def send_side_effect(_text: str) -> None:
        cb = callbacks[-1]
        cb(
            SimpleNamespace(
                type=SimpleNamespace(value="assistant.message_delta"),
                data=SimpleNamespace(delta_content="Tony "),
            )
        )
        cb(
            SimpleNamespace(
                type=SimpleNamespace(value="assistant.message_delta"),
                data=SimpleNamespace(delta_content="here"),
            )
        )
        cb(SimpleNamespace(type=SimpleNamespace(value="session.idle"), data=SimpleNamespace()))

    session.send = AsyncMock(side_effect=send_side_effect)

    create_session = AsyncMock(return_value=session)
    client = MagicMock()
    client.create_session = create_session
    client.start = AsyncMock()
    client.stop = AsyncMock()

    agent._client = client
    agent._provider = MagicMock()
    agent._provider.copilot_session_kwargs.return_value = {"provider": {"type": "anthropic"}}

    deltas: list[str] = []
    result = await agent.send("thread-1", "hello", on_delta=deltas.append)

    assert result == "Tony here"
    assert deltas == ["Tony ", "here"]
    create_session.assert_awaited_once()
    kwargs = create_session.await_args.kwargs
    assert kwargs["streaming"] is True
    assert kwargs["infinite_sessions"] == {"enabled": True}
    assert kwargs["provider"]["type"] == "anthropic"


@pytest.mark.asyncio
async def test_send_reuses_session_per_thread() -> None:
    agent = TonyAgent()

    callbacks: list = []
    session = MagicMock()
    session.on = MagicMock(side_effect=lambda cb: callbacks.append(cb))

    async def send_side_effect(_text: str) -> None:
        cb = callbacks[-1]
        cb(
            SimpleNamespace(
                type=SimpleNamespace(value="assistant.message_delta"),
                data=SimpleNamespace(delta_content="ok"),
            )
        )
        cb(SimpleNamespace(type=SimpleNamespace(value="session.idle"), data=SimpleNamespace()))

    session.send = AsyncMock(side_effect=send_side_effect)

    create_session = AsyncMock(return_value=session)
    client = MagicMock()
    client.create_session = create_session
    client.start = AsyncMock()
    client.stop = AsyncMock()

    agent._client = client
    agent._provider = MagicMock()
    agent._provider.copilot_session_kwargs.return_value = {}

    first = await agent.send("thread-1", "hello")
    second = await agent.send("thread-1", "again")

    assert first == "ok"
    assert second == "ok"
    create_session.assert_awaited_once()
    assert session.send.await_count == 2


@pytest.mark.asyncio
async def test_send_handles_empty_delta_content() -> None:
    """Test when delta_content is present but empty string"""
    agent = TonyAgent()

    callbacks: list = []
    session = MagicMock()
    session.on = MagicMock(side_effect=lambda cb: callbacks.append(cb))

    async def send_side_effect(_text: str) -> None:
        cb = callbacks[-1]
        cb(
            SimpleNamespace(
                type=SimpleNamespace(value="assistant.message_delta"),
                data=SimpleNamespace(delta_content=""),
            )
        )
        cb(SimpleNamespace(type=SimpleNamespace(value="session.idle"), data=SimpleNamespace()))

    session.send = AsyncMock(side_effect=send_side_effect)

    create_session = AsyncMock(return_value=session)
    client = MagicMock()
    client.create_session = create_session
    client.start = AsyncMock()
    client.stop = AsyncMock()

    agent._client = client
    agent._provider = MagicMock()
    agent._provider.copilot_session_kwargs.return_value = {}

    result = await agent.send("thread-1", "hello")
    assert result == ""


@pytest.mark.asyncio
async def test_send_handles_missing_delta_content() -> None:
    """Test when delta_content is missing from data"""
    agent = TonyAgent()

    callbacks: list = []
    session = MagicMock()
    session.on = MagicMock(side_effect=lambda cb: callbacks.append(cb))

    async def send_side_effect(_text: str) -> None:
        cb = callbacks[-1]
        cb(
            SimpleNamespace(
                type=SimpleNamespace(value="assistant.message_delta"),
                data=SimpleNamespace(),  # No delta_content attribute
            )
        )
        cb(SimpleNamespace(type=SimpleNamespace(value="session.idle"), data=SimpleNamespace()))

    session.send = AsyncMock(side_effect=send_side_effect)

    create_session = AsyncMock(return_value=session)
    client = MagicMock()
    client.create_session = create_session
    client.start = AsyncMock()
    client.stop = AsyncMock()

    agent._client = client
    agent._provider = MagicMock()
    agent._provider.copilot_session_kwargs.return_value = {}

    result = await agent.send("thread-1", "hello")
    assert result == ""


@pytest.mark.asyncio
async def test_send_handles_none_delta_content() -> None:
    """Test when delta_content is None"""
    agent = TonyAgent()

    callbacks: list = []
    session = MagicMock()
    session.on = MagicMock(side_effect=lambda cb: callbacks.append(cb))

    async def send_side_effect(_text: str) -> None:
        cb = callbacks[-1]
        cb(
            SimpleNamespace(
                type=SimpleNamespace(value="assistant.message_delta"),
                data=SimpleNamespace(delta_content=None),
            )
        )
        cb(SimpleNamespace(type=SimpleNamespace(value="session.idle"), data=SimpleNamespace()))

    session.send = AsyncMock(side_effect=send_side_effect)

    create_session = AsyncMock(return_value=session)
    client = MagicMock()
    client.create_session = create_session
    client.start = AsyncMock()
    client.stop = AsyncMock()

    agent._client = client
    agent._provider = MagicMock()
    agent._provider.copilot_session_kwargs.return_value = {}

    result = await agent.send("thread-1", "hello")
    assert result == ""


@pytest.mark.asyncio
async def test_send_with_no_message_delta_events() -> None:
    """Test when only non-delta events are received"""
    agent = TonyAgent()

    callbacks: list = []
    session = MagicMock()
    session.on = MagicMock(side_effect=lambda cb: callbacks.append(cb))

    async def send_side_effect(_text: str) -> None:
        cb = callbacks[-1]
        cb(SimpleNamespace(type=SimpleNamespace(value="session.started"), data=SimpleNamespace()))
        cb(SimpleNamespace(type=SimpleNamespace(value="session.idle"), data=SimpleNamespace()))

    session.send = AsyncMock(side_effect=send_side_effect)

    create_session = AsyncMock(return_value=session)
    client = MagicMock()
    client.create_session = create_session
    client.start = AsyncMock()
    client.stop = AsyncMock()

    agent._client = client
    agent._provider = MagicMock()
    agent._provider.copilot_session_kwargs.return_value = {}

    result = await agent.send("thread-1", "hello")
    assert result == ""


@pytest.mark.asyncio
async def test_send_callback_never_called() -> None:
    """Test when session.on() callback is never invoked by send()"""
    agent = TonyAgent()

    callbacks: list = []
    session = MagicMock()
    session.on = MagicMock(side_effect=lambda cb: callbacks.append(cb))

    async def send_side_effect(_text: str) -> None:
        # Never call the callback, simulating hung request
        pass

    session.send = AsyncMock(side_effect=send_side_effect)

    create_session = AsyncMock(return_value=session)
    client = MagicMock()
    client.create_session = create_session
    client.start = AsyncMock()
    client.stop = AsyncMock()

    agent._client = client
    agent._provider = MagicMock()
    agent._provider.copilot_session_kwargs.return_value = {}

    # This test will timeout if waiting forever - needs a timeout mechanism
    import asyncio
    try:
        result = await asyncio.wait_for(agent.send("thread-1", "hello"), timeout=0.1)
        assert False, "Should have timed out"
    except asyncio.TimeoutError:
        pass  # Expected


@pytest.mark.asyncio
async def test_send_multiple_deltas_accumulate() -> None:
    """Test that multiple delta events accumulate correctly"""
    agent = TonyAgent()

    callbacks: list = []
    session = MagicMock()
    session.on = MagicMock(side_effect=lambda cb: callbacks.append(cb))

    async def send_side_effect(_text: str) -> None:
        cb = callbacks[-1]
        for chunk in ["Hello ", "there ", "Tony"]:
            cb(
                SimpleNamespace(
                    type=SimpleNamespace(value="assistant.message_delta"),
                    data=SimpleNamespace(delta_content=chunk),
                )
            )
        cb(SimpleNamespace(type=SimpleNamespace(value="session.idle"), data=SimpleNamespace()))

    session.send = AsyncMock(side_effect=send_side_effect)

    create_session = AsyncMock(return_value=session)
    client = MagicMock()
    client.create_session = create_session
    client.start = AsyncMock()
    client.stop = AsyncMock()

    agent._client = client
    agent._provider = MagicMock()
    agent._provider.copilot_session_kwargs.return_value = {}

    result = await agent.send("thread-1", "hello")
    assert result == "Hello there Tony"


@pytest.mark.asyncio
async def test_send_event_type_extraction() -> None:
    """Test different ways event.type.value might be structured"""
    agent = TonyAgent()

    callbacks: list = []
    session = MagicMock()
    session.on = MagicMock(side_effect=lambda cb: callbacks.append(cb))

    async def send_side_effect(_text: str) -> None:
        cb = callbacks[-1]
        # Valid event
        cb(
            SimpleNamespace(
                type=SimpleNamespace(value="assistant.message_delta"),
                data=SimpleNamespace(delta_content="test"),
            )
        )
        # Event with missing type.value
        cb(SimpleNamespace(type=SimpleNamespace(), data=SimpleNamespace()))
        # Event with missing type
        cb(SimpleNamespace(data=SimpleNamespace()))
        cb(SimpleNamespace(type=SimpleNamespace(value="session.idle"), data=SimpleNamespace()))

    session.send = AsyncMock(side_effect=send_side_effect)

    create_session = AsyncMock(return_value=session)
    client = MagicMock()
    client.create_session = create_session
    client.start = AsyncMock()
    client.stop = AsyncMock()

    agent._client = client
    agent._provider = MagicMock()
    agent._provider.copilot_session_kwargs.return_value = {}

    result = await agent.send("thread-1", "hello")
    assert result == "test"
