# TonyAI — Architecture & Module Reference

> Auto-generated documentation. Source: `src/tony_ai/`, `pyproject.toml`, `.github/agents/`.

---

## 1. Project Overview

**TonyAI** is a Slack-based personal AI assistant with the persona of J.A.R.V.I.S. (Iron Man). It connects a Slack workspace to the GitHub Copilot SDK, maintaining persistent, per-thread AI sessions enriched with a local MCP tool server that gives the AI filesystem access, shell execution, and a structured wiki memory system.

| Property | Value |
|---|---|
| Package | `tony-ai` v0.1.0 |
| Python | ≥ 3.11 |
| Entry point | `tony_ai.main:main` / CLI: `tony_ai` |
| Transport | Slack Socket Mode (WebSocket) |
| LLM Backend | GitHub Copilot SDK (default) or Anthropic BYOK |
| Tool Protocol | MCP (Model Context Protocol) via `FastMCP` |

---

## 2. High-Level Architecture

```
User (Slack DM / mention)
        │
        ▼
┌─────────────────────┐
│  Slack Socket Mode  │  ← slack_bolt SocketModeHandler
│  bot.py / handlers  │
└──────────┬──────────┘
           │  thread_ts + text
           ▼
┌─────────────────────┐
│     TonyAgent       │  ← agents/tony.py
│  (session manager)  │
│  _sessions[ts]      │  normal model (gpt-5-mini)
│  _pro_sessions[ts]  │  pro model (claude-sonnet-4.6)
└──────────┬──────────┘
           │  CopilotClient.create_session / send_and_wait
           ▼
┌─────────────────────┐
│  GitHub Copilot SDK │  ← github-copilot-sdk
│  (CopilotClient)    │
└──────────┬──────────┘
           │  MCP stdio subprocess
           ▼
┌─────────────────────┐
│  tony-desktop MCP   │  ← mcp/server.py (FastMCP)
│  Server             │
│  - Filesystem tools │
│  - Shell / Python   │
│  - Wiki tools       │
└─────────────────────┘
           │  projects/wiki/
           ▼
┌─────────────────────┐
│  Wiki (Markdown)    │  ← projects/wiki/*.md
│  Persistent Memory  │
└─────────────────────┘
```

---

## 3. Module Structure

```
src/tony_ai/
├── __init__.py          # Empty package marker
├── config.py            # Environment variable loading
├── main.py              # CLI entry point
├── agents/
│   ├── __init__.py
│   └── tony.py          # TonyAgent — core AI session manager
├── llm/
│   ├── __init__.py
│   └── provider.py      # LLMProvider abstraction + factory
├── mcp/
│   ├── __init__.py
│   └── server.py        # FastMCP tool server (tony-desktop)
└── slack/
    ├── __init__.py
    ├── bot.py            # Slack App + SocketModeHandler bootstrap
    └── handlers.py       # Slack event handlers + agent dispatch
```

---

## 4. Module Details

### 4.1 `config.py` — Configuration

Loads `.env` via `python-dotenv` and exports:

| Constant | Env Var | Default | Purpose |
|---|---|---|---|
| `SLACK_BOT_TOKEN` | `SLACK_BOT_TOKEN` | *(required)* | Slack bot OAuth token |
| `SLACK_APP_TOKEN` | `SLACK_APP_TOKEN` | *(required)* | Slack app-level token (Socket Mode) |
| `COPILOT_TOKEN` | `GITHUB_TOKEN` | *(required)* | GitHub PAT for Copilot SDK |
| `DEFAULT_MODEL` | `DEFAULT_MODEL` | `"gpt-5-mini"` | Standard session model |
| `DEFAULT_PRO_MODEL` | `DEFAULT_PRO_MODEL` | `"claude-sonnet-4.6"` | Pro session model |
| `MCP_SERVER_URL` | `MCP_SERVER_URL` | `"http://localhost:8000/mcp"` | (reserved, not currently used) |

---

### 4.2 `main.py` — Entry Point

```python
def main() -> None:
    start()  # delegates to slack.bot.start()
```

Registered as `[tool.poetry.scripts] tony_ai`. Simply bootstraps the Slack bot.

---

### 4.3 `agents/tony.py` — TonyAgent

The core AI orchestration layer.

**Module-level setup:**
- Resolves `_REPO_ROOT` (4 levels up from file)
- Derives `_VENV_PYTHON` path for MCP subprocess
- Reads `.github/agents/tony.agent.md` as `SYSTEM_PROMPT` — appended with a path-restriction notice
- Defines `_MCP_SERVERS` dict connecting the `tony-desktop` MCP server as a stdio subprocess

**Class: `TonyAgent`**

| Method | Signature | Description |
|---|---|---|
| `__init__` | `() → None` | Creates `CopilotClient=None`, empty session dicts, instantiates LLM provider |
| `start` | `async () → None` | Lazy-initializes `CopilotClient` with `SubprocessConfig(github_token=...)` |
| `stop` | `async () → None` | Stops client, clears all sessions |
| `send` | `async (thread_ts, text, on_delta?, pro?) → str` | Gets/creates session, subscribes to streaming deltas, calls `send_and_wait(timeout=12h)`, returns final content string |
| `_get_or_create_session` | `async (thread_ts, pro?) → Session` | Looks up session in `_sessions` or `_pro_sessions`; creates new one with system prompt + MCP servers if absent |
| `reset_session` | `async (thread_ts) → None` | Closes + removes a single thread's session |
| `reset` | `async () → None` | Resets all active sessions |

**Session creation parameters:**
```python
client.create_session(
    model=DEFAULT_MODEL | DEFAULT_PRO_MODEL,
    on_permission_request=PermissionHandler.approve_all,
    streaming=True,
    infinite_sessions={"enabled": True},
    system_message={"text": SYSTEM_PROMPT},
    mcp_servers=_MCP_SERVERS,
    **provider.copilot_session_kwargs(),  # optional BYOK overrides
)
```

**Streaming delta handling:**
- Subscribes via `session.on(callback)` before `send_and_wait`
- Fires `on_delta(chunk)` for every `SessionEventType.ASSISTANT_MESSAGE_DELTA` event
- Unsubscribes in `finally` block
- Returns full assembled content from `result_event.data.content`

---

### 4.4 `llm/provider.py` — LLM Provider

Plugin system for selecting the LLM backend.

**Abstract base:**
```python
class LLMProvider(ABC):
    @abstractmethod
    def copilot_session_kwargs(self) -> dict[str, Any]: ...
```

**Implementations:**

| Class | `LLM_PROVIDER` value | Behavior |
|---|---|---|
| `GitHubCopilotProvider` | `github_copilot` (default) | Returns `{}` — Copilot SDK uses `GITHUB_TOKEN` directly |
| `AnthropicProvider` | `anthropic` | Returns provider dict with `type`, `base_url`, `api_key` from `ANTHROPIC_API_KEY` |

**Factory:**
```python
def get_provider() -> LLMProvider:
    name = os.getenv("LLM_PROVIDER", "github_copilot").lower()
    if name == "anthropic":
        return AnthropicProvider(os.environ["ANTHROPIC_API_KEY"])
    return GitHubCopilotProvider()
```

---

### 4.5 `mcp/server.py` — tony-desktop MCP Server

A `FastMCP` server named `"tony-desktop"` run as a stdio subprocess by the Copilot SDK. Provides Tony with all filesystem/system capabilities.

**Constants:**
- `_REPO_ROOT` — project root (4 levels up)
- `_WIKI_ROOT` — `_REPO_ROOT / "projects" / "wiki"`
- `_VENV_PYTHON` — `.venv/Scripts/python.exe`

**Filesystem & Shell Tools:**

| Tool | Signature | Description |
|---|---|---|
| `run_shell` | `(command, cwd?) → str` | `subprocess.run` with `shell=True`, timeout 120s, returns stdout+stderr |
| `run_python` | `(script, args?, cwd?) → str` | Runs `.venv` Python; prefix `-c ` for inline code, otherwise file path |
| `read_file` | `(path) → str` | UTF-8 file read |
| `write_file` | `(path, content) → str` | UTF-8 file write, returns confirmation |
| `list_dir` | `(path?) → list[str]` | `os.listdir` |

**Wiki Tools** (all paths relative to `projects/wiki/`):

| Tool | Signature | Description |
|---|---|---|
| `wiki_read` | `(page) → str` | Reads page; returns "Page not found" if absent |
| `wiki_write` | `(page, content, index_entry?) → str` | Writes page; auto-calls `_wiki_update_index` + `_wiki_append_log` |
| `wiki_search` | `(query) → str` | `grep -rni` across all `.md` files |
| `wiki_list` | `() → list[str]` | `rglob("*.md")` sorted, paths relative to wiki root |
| `wiki_lint` | `() → str` | Health report: orphan pages, link-free pages, stale pages (>30 days) |

**Private helpers:**
- `_wiki_update_index(page, summary, today)` — inserts/updates entry under correct `## Section` in `index.md`, bumps `updated:` frontmatter
- `_wiki_append_log(page, today)` — appends `## [date] update | page` to `log.md`

**MCP Resource:**
- `desktop://cwd` → `os.getcwd()`

**Execution:** `if __name__ == "__main__": mcp.run()` — stdio transport for Copilot SDK subprocess mode.

---

### 4.6 `slack/bot.py` — Slack Bot Bootstrap

```python
app = App(token=SLACK_BOT_TOKEN)
register_handlers(app)

def start() -> None:
    handler = SocketModeHandler(app, SLACK_APP_TOKEN)
    handler.start()
```

Configures logging (`INFO`, timestamped format), creates the `slack_bolt.App`, registers all handlers, then starts the Socket Mode WebSocket connection.

---

### 4.7 `slack/handlers.py` — Event Handlers

**Module-level globals:**
- `_agent = TonyAgent()` — singleton agent instance
- `_loop = asyncio.new_event_loop()` — dedicated event loop for sync→async bridging
- `_pro_threads: set[str]` — set of thread timestamps with pro mode active

**`_handle_message(event, say, client)`** — core handler logic:

1. Ignores bot messages (`bot_id` present)
2. Determines `thread_ts` (falls back to `event["ts"]` for new threads)
3. **`$restart`** — re-execs the Python process (`os.execv`)
4. **`$pro`** — toggles `thread_ts` in `_pro_threads`, posts confirmation
5. Posts `_Thinking..._` placeholder message, captures `placeholder_ts`
6. **`$file [title]`** — constructs a wiki-filing prompt with today's date instruction
7. Calls `_loop.run_until_complete(_agent.send(thread_ts, text, pro=...))` (sync bridge)
8. Updates placeholder message with response via `client.chat_update`

**`register_handlers(app)`:**
- `@app.event("message")` → `_handle_message`
- `@app.event("app_mention")` → `_handle_message`

---

## 5. Agent Fleet (`.github/agents/`)

Tony operates within a multi-agent system. Agent personas are `.agent.md` files loaded by GitHub Copilot:

| Agent | Model | Role |
|---|---|---|
| **Tony** | GPT-5 mini | Personal assistant, wiki memory, orchestrator, user interface |
| **Team Leader** | GPT-5.3-Codex | Decomposes projects into 3-7 subtasks, sequential coder delegation |
| **Coder** | Claude Sonnet 4.6 | Autonomous implementation, zero-confirmation policy |
| **Planner** | — | Planning specialist |
| **Researcher** | — | Web research, primary sources, wiki-ready findings |

**Delegation flow:** User → Tony → (if complex task) → Team Leader → Coder(s) → result back to Tony → User

---

## 6. Data Flow

### Normal Message Flow
```
Slack message
  → handlers._handle_message()
    → post "Thinking..." placeholder
    → _loop.run_until_complete(
        _agent.send(thread_ts, text)
          → _get_or_create_session(thread_ts)
            → CopilotClient.create_session(model, system_prompt, mcp_servers)
          → session.send_and_wait(text, timeout=12h)
            ↕ streaming deltas → on_delta callback (optional)
            ↕ MCP tool calls → tony-desktop server subprocess
              → run_shell / read_file / wiki_read / etc.
          → returns final content string
      )
    → client.chat_update(placeholder → response)
```

### Wiki Write Flow
```
Tony (LLM) decides to file info
  → calls wiki_write(page, content, index_entry) via MCP
    → writes projects/wiki/<page>.md
    → _wiki_update_index() → updates projects/wiki/index.md
    → _wiki_append_log() → appends to projects/wiki/log.md
```

---

## 7. Configuration Reference

### Required Environment Variables

| Variable | Purpose |
|---|---|
| `SLACK_BOT_TOKEN` | `xoxb-...` Slack bot token |
| `SLACK_APP_TOKEN` | `xapp-...` Slack app token (Socket Mode) |
| `GITHUB_TOKEN` | GitHub PAT with Copilot access |

### Optional Environment Variables

| Variable | Default | Purpose |
|---|---|---|
| `DEFAULT_MODEL` | `gpt-5-mini` | Standard session model |
| `DEFAULT_PRO_MODEL` | `claude-sonnet-4.6` | Pro session model (`$pro` toggle) |
| `LLM_PROVIDER` | `github_copilot` | Set to `anthropic` for BYOK |
| `ANTHROPIC_API_KEY` | — | Required if `LLM_PROVIDER=anthropic` |
| `MCP_SERVER_URL` | `http://localhost:8000/mcp` | Reserved (not currently used) |

---

## 8. Dependencies

### Runtime
| Package | Version | Purpose |
|---|---|---|
| `slack-bolt` | `^1.21` | Slack SDK + Socket Mode |
| `github-copilot-sdk` | `^0.2` | Copilot session management |
| `mcp[cli]` | `^1.27` | FastMCP server framework |
| `python-dotenv` | `^1.0` | `.env` loading |

### Development
| Package | Purpose |
|---|---|
| `ruff` | Linting + formatting |
| `pytest` | Test runner |
| `pytest-asyncio` | Async test support |

---

## 9. Test Coverage

| Test File | Covers |
|---|---|
| `test_agents.py` | TonyAgent: session creation, reuse, delta streaming, edge cases |
| `test_llm_provider.py` | Provider factory, GitHubCopilot/Anthropic selection, missing key error |
| `test_mcp_server.py` | `list_dir`, `write_file`/`read_file` roundtrip, `run_shell` |
| `test_slack_handlers.py` | DM handling, mention handling, agent dispatch, thread_ts logic |

---

## 10. Key Design Decisions

1. **Per-thread session persistence** — each Slack thread gets its own Copilot session, enabling true conversational memory within a thread without re-sending history.
2. **Sync/async bridge** — Slack Bolt is synchronous; a dedicated `asyncio` event loop bridges to the async Copilot SDK via `run_until_complete`.
3. **MCP as local subprocess** — the MCP server runs as a child process of the Copilot SDK (not HTTP), enabling direct filesystem access without network overhead.
4. **Wiki as persistent memory** — the `projects/wiki/` directory is Tony's long-term memory store, structured with `index.md`, `log.md`, and domain sections, all managed atomically by MCP tools.
5. **Pluggable LLM providers** — the `LLMProvider` ABC allows future BYOK backends without changing agent/session logic.
6. **Pro mode** — per-thread `$pro` toggle switches to a higher-capability model (claude-sonnet-4.6) for the lifetime of that thread.
