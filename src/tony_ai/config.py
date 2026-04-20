import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

SLACK_BOT_TOKEN = os.environ["SLACK_BOT_TOKEN"]
SLACK_APP_TOKEN = os.environ["SLACK_APP_TOKEN"]
COPILOT_TOKEN = os.environ["GITHUB_TOKEN"]

DEFAULT_MODEL = os.getenv("DEFAULT_MODEL", "gpt-5-mini")
DEFAULT_PRO_MODEL = os.getenv("DEFAULT_PRO_MODEL", "claude-sonnet-4.6")


MCP_SERVER_URL = os.getenv("MCP_SERVER_URL", "http://localhost:8000/mcp")


REPO_ROOT = Path(__file__).parent.parent.parent
TONY_WORKSPACE = os.getenv("TONY_WORKSPACE", REPO_ROOT.parent / "tony_workspace")