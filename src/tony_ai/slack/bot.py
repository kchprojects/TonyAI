import asyncio
from enum import Enum
import json
import logging
import os
import sys
from typing import Any, Union

from slack_bolt import App
from slack_bolt.adapter.socket_mode import SocketModeHandler

from tony_ai.agents.semantic_analyzer import SemanticAnalyzer
from tony_ai.config import SLACK_APP_TOKEN, SLACK_BOT_TOKEN


from tony_ai.agents.tony import TonyAgent

from tony_ai.slack.slack_streamer import SlackEventStream


# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class SlackBot:
    def __init__(self) -> None:
        self.app = App(token=SLACK_BOT_TOKEN)
        self.register_handlers()

        self._agent = TonyAgent()
        self._loop = asyncio.new_event_loop()
        self._pro_threads: set[str] = set()  # threads with pro model active

    def register_handlers(self) -> None:
        @self.app.event("message")
        def handle_message(event, say, client):
            self._handle_message(event, say, client)

        @self.app.event("app_mention")
        def handle_mention(event, say, client):
            self._handle_mention(event, say, client)

    def start(self) -> None:
        handler = SocketModeHandler(self.app, SLACK_APP_TOKEN)
        handler.start()
    
    def _toggle_pro_mode(self, thread_ts: str) -> None:
        if thread_ts in self._pro_threads:
            self._pro_threads.discard(thread_ts)
        else:
            self._pro_threads.add(thread_ts)

    def _handle_command(self, text: str, channel: str, thread_ts: str, client) -> bool:
        # Handle $restart without showing a placeholder
        if text.startswith("$restart"):
            executable = sys.executable + ".exe"
            logger.info(f"Restarting process with: {executable} {' '.join(sys.argv)}")
            os.execv(executable, [executable] + sys.argv)
            return True, "Restarting..."
        if text.strip() == "$pro":
            self._toggle_pro_mode(thread_ts)
            return True, f"_Pro mode {'on' if thread_ts in self._pro_threads else 'off'}._"

        return False, ""
    def _handle_message(self, event, say, client) -> None:
        """Handle DMs and messages"""
        if event.get("bot_id"):
            return  # Ignore bot messages
        

        text = event.get("text", "")
        channel = event.get("channel", "")
        thread_ts = event.get("thread_ts") or event["ts"]

        logger.info(f"Message in {channel}:{thread_ts}: {text}")
        
        handled, message = self._handle_command(text, channel, thread_ts, client)
        if handled:
            client.chat_postMessage(channel=channel, thread_ts=thread_ts, text=message)
            return 
        
        context = SemanticAnalyzer().analyze(text)
        stream = SlackEventStream(client, channel, thread_ts, placeholder_ts=placeholder_ts)

        placeholder = client.chat_postMessage(
            channel=channel,
            thread_ts=thread_ts,
            text=f"{json.dumps(context.__dict__)}\n_Thinking..._",
        )
        placeholder_ts = placeholder["ts"]
        stream = SlackEventStream(client, channel, thread_ts, placeholder_ts=placeholder_ts)        

        send_text = text # TODO: Might want to change
        response = self._loop.run_until_complete(self._agent.send(thread_ts, send_text, on_event=stream.handle, pro=thread_ts in _pro_threads))
        logger.info(f"Agent response: {response}")

        try:
            client.chat_update(
                channel=channel,
                ts=placeholder_ts,
                text=response,
            )
            print("   ✅ Response sent")
        except Exception as e:
            print(f"   ❌ Error sending response: {e}")
            logger.error(f"Error: {e}", exc_info=True)


    def _handle_mention(self, event, say, client) -> None:
        pass
