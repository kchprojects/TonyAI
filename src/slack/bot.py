import logging

from slack_bolt import App
from slack_bolt.adapter.socket_mode import SocketModeHandler

from src.config import SLACK_APP_TOKEN, SLACK_BOT_TOKEN
from src.slack.handlers import register_handlers

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)

app = App(token=SLACK_BOT_TOKEN)
register_handlers(app)


def start() -> None:
    handler = SocketModeHandler(app, SLACK_APP_TOKEN)
    handler.start()
