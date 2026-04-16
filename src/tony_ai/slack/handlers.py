import asyncio
import logging
import os
import sys
from slack_bolt import App

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

from tony_ai.agents.tony import TonyAgent

_agent = TonyAgent()
_loop = asyncio.new_event_loop()
_pro_threads: set[str] = set()  # threads with pro model active

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

    # Post a placeholder while generating the response
    placeholder = client.chat_postMessage(
        channel=channel,
        thread_ts=thread_ts,
        text="_Thinking..._",
    )
    placeholder_ts = placeholder["ts"]

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

    response = _loop.run_until_complete(_agent.send(thread_ts, send_text, pro=thread_ts in _pro_threads))
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