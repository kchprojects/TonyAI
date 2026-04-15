import asyncio
import logging

from slack_bolt import App

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

from src.agents.tony import TonyAgent
_agent = TonyAgent()
_loop = asyncio.new_event_loop()

def _handle_command(text: str) -> None:
    if text.startswith("$reset"):
        _agent.reset()
    return "ok"

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

    # Post a placeholder while generating the response
    placeholder = client.chat_postMessage(
        channel=channel,
        thread_ts=thread_ts,
        text="_Thinking..._",
    )
    placeholder_ts = placeholder["ts"]

    if text.startswith("$"):
        response = _handle_command(text)
    else:
        response = _loop.run_until_complete(_agent.send(thread_ts, text))
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