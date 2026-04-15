import os

from dotenv import load_dotenv

load_dotenv()

SLACK_BOT_TOKEN = os.environ["SLACK_BOT_TOKEN"]
SLACK_APP_TOKEN = os.environ["SLACK_APP_TOKEN"]
COPILOT_TOKEN = os.environ["GITHUB_TOKEN"]
DEFAULT_MODEL = os.getenv("DEFAULT_MODEL", "gpt-5-mini")
DEFAULT_PRO_MODEL = os.getenv("DEFAULT_PRO_MODEL", "claude-sonnet-4.6")

MCP_SERVER_URL = os.getenv("MCP_SERVER_URL", "http://localhost:8000/mcp")
# LLM provider selection is handled via src/llm/provider.py.
# GITHUB_TOKEN is read by the Copilot SDK from the environment.
