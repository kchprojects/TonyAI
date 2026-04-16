from __future__ import annotations

import os
import re
import subprocess
from datetime import date, datetime
from pathlib import Path

from mcp.server.fastmcp import FastMCP

from tony_ai.mcp import git_workflow


_REPO_ROOT = Path(__file__).parent.parent.parent.parent
_WIKI_ROOT = _REPO_ROOT / "projects" / "wiki"
_VENV_PYTHON = str(_REPO_ROOT / ".venv" / "Scripts" / "python.exe")

_STREAMS_DIR = Path.home() / ".tony_ai" / "streams"

mcp = FastMCP("tony-desktop")


def _sanitize_cmd(command: str, max_len: int = 40) -> str:
    """Convert *command* to a safe filename stem (alphanumeric + underscores)."""
    sanitized = re.sub(r"[^a-zA-Z0-9]", "_", command)
    return sanitized[:max_len]


@mcp.tool()
def run_shell(command: str, cwd: str | None = None, stream: bool = False) -> str:
    """Run a shell command. Returns stdout and stderr.

    Args:
        command: Shell command to execute.
        cwd:     Working directory (defaults to repo root).
        stream:  When True, write output lines to
                 ~/.tony_ai/streams/<sanitized_cmd>.log in real-time
                 (append mode) *and* return the full output as usual.
    """
    if not stream:
        result = subprocess.run(
            command,
            shell=True,
            cwd=cwd or str(_REPO_ROOT),
            capture_output=True,
            text=True,
            timeout=300,
        )
        return result.stdout + result.stderr

    # ------------------------------------------------------------------
    # Streaming mode — write timestamped lines to a log file in real-time.
    # ------------------------------------------------------------------
    _STREAMS_DIR.mkdir(parents=True, exist_ok=True)
    log_path = _STREAMS_DIR / f"{_sanitize_cmd(command)}.log"

    output_lines: list[str] = []

    with open(log_path, "a", encoding="utf-8") as log_fh:
        log_fh.write(f"[STREAM START: {command}]\n")
        log_fh.flush()

        proc = subprocess.Popen(
            command,
            shell=True,
            cwd=cwd or str(_REPO_ROOT),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )

        if proc.stdout is not None:
            for line in proc.stdout:
                ts = datetime.now().isoformat(timespec="seconds")
                log_fh.write(f"[{ts}] {line}")
                log_fh.flush()
                output_lines.append(line)

        proc.wait()
        log_fh.write(f"[STREAM END: {proc.returncode}]\n")
        log_fh.flush()

    return "".join(output_lines)


@mcp.tool()
def run_python(script: str, args: list[str] | None = None, cwd: str | None = None) -> str:
    """Run a Python script or inline code using the project .venv interpreter.
    Pass a file path as script, or prefix with '-c ' to run inline code."""
    cmd = [_VENV_PYTHON]
    if script.startswith("-c "):
        cmd += ["-c", script[3:]]
    else:
        cmd.append(script)
    if args:
        cmd.extend(args)
    result = subprocess.run(
        cmd,
        cwd=cwd or str(_REPO_ROOT),
        capture_output=True,
        text=True,
        timeout=120,
    )
    return result.stdout + result.stderr


@mcp.tool()
def read_file(path: str) -> str:
    """Read a file from the desktop filesystem."""
    with open(path, "r", encoding="utf-8") as file:
        return file.read()


@mcp.tool()
def write_file(path: str, content: str) -> str:
    """Write content to a file on the desktop filesystem."""
    with open(path, "w", encoding="utf-8") as file:
        file.write(content)
    return f"Written: {path}"


@mcp.tool()
def list_dir(path: str = ".") -> list[str]:
    """List directory contents."""
    return os.listdir(path)


# ---------------------------------------------------------------------------
# Wiki tools — always operate relative to projects/wiki/
# ---------------------------------------------------------------------------

@mcp.tool()
def wiki_read(page: str) -> str:
    """Read a wiki page. page is relative to projects/wiki/ e.g. 'personal/profile.md' or 'index.md'."""
    target = _WIKI_ROOT / page
    if not target.exists():
        return f"Page not found: {page}"
    return target.read_text(encoding="utf-8")


@mcp.tool()
def wiki_write(page: str, content: str, index_entry: str | None = None) -> str:
    """Write a wiki page and handle all housekeeping automatically.

    Args:
        page: Path relative to projects/wiki/, e.g. 'personal/goals.md' or 'projects/tony-ai.md'
        content: Full markdown content to write.
        index_entry: One-line summary for index.md (e.g. 'User goals — short and long-term').
                     Pass None to skip index update (use for log/index/schema themselves).
    """
    target = _WIKI_ROOT / page
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")

    today = date.today().isoformat()

    # Update index.md unless caller opted out
    if index_entry is not None:
        _wiki_update_index(page, index_entry, today)

    # Always append to log.md
    _wiki_append_log(page, today)

    return f"Wiki: wrote {page}, log updated" + (", index updated" if index_entry is not None else "")


@mcp.tool()
def wiki_search(query: str) -> str:
    """Search all wiki pages for a keyword. Returns matching file:line:text results."""
    result = subprocess.run(
        ["grep", "-rni", "--include=*.md", query, str(_WIKI_ROOT)],
        capture_output=True, text=True, timeout=15,
    )
    return result.stdout or "No matches found."


@mcp.tool()
def wiki_list() -> list[str]:
    """List all pages in the wiki as paths relative to projects/wiki/."""
    pages = []
    for p in _WIKI_ROOT.rglob("*.md"):
        pages.append(str(p.relative_to(_WIKI_ROOT)).replace("\\", "/"))
    return sorted(pages)


@mcp.tool()
def wiki_lint() -> str:
    """Run a health check on the wiki. Returns a report of:
    - Orphan pages (not referenced in index.md)
    - Pages with no outbound wikilinks
    - Pages not updated in 30+ days (based on 'updated:' frontmatter)
    """
    import re as _re
    from datetime import date as _date

    today = _date.today()
    all_pages = wiki_list()

    index_content = (_WIKI_ROOT / "index.md").read_text(encoding="utf-8") if (_WIKI_ROOT / "index.md").exists() else ""
    # Collect pages referenced in index.md via wikilinks [[...]]
    indexed_stems = set(_re.findall(r"\[\[([^\]|]+)(?:\|[^\]]*)?\]\]", index_content))

    orphans: list[str] = []
    no_links: list[str] = []
    stale: list[str] = []

    skip = {"index.md", "log.md", "schema.md"}

    for page in all_pages:
        if page in skip:
            continue

        path = _WIKI_ROOT / page
        content = path.read_text(encoding="utf-8")
        stem = page.replace(".md", "")

        # Orphan: no entry in index.md
        if stem not in indexed_stems:
            orphans.append(page)

        # No outbound wikilinks
        if not _re.search(r"\[\[", content):
            no_links.append(page)

        # Stale: updated date older than 30 days
        m = _re.search(r"^updated:\s*(\d{4}-\d{2}-\d{2})", content, _re.MULTILINE)
        if m:
            updated = _date.fromisoformat(m.group(1))
            if (today - updated).days > 30:
                stale.append(f"{page} (last updated {m.group(1)})")

    lines = ["# Wiki Health Report", f"_Generated: {today}_", ""]
    lines.append(f"**Total pages**: {len(all_pages)}")
    lines.append("")

    lines.append("## Orphans (not in index.md)")
    lines += [f"- {p}" for p in orphans] if orphans else ["*(none)*"]
    lines.append("")

    lines.append("## No outbound links")
    lines += [f"- {p}" for p in no_links] if no_links else ["*(none)*"]
    lines.append("")

    lines.append("## Stale pages (>30 days since update)")
    lines += [f"- {p}" for p in stale] if stale else ["*(none)*"]

    return "\n".join(lines)


def _wiki_update_index(page: str, summary: str, today: str) -> None:
    """Insert or update the entry for `page` in index.md."""
    index_path = _WIKI_ROOT / "index.md"
    if not index_path.exists():
        return

    # Determine section header from top-level folder
    parts = page.split("/")
    section_map = {
        "projects": "Projects",
        "research": "Research",
        "decisions": "Decisions",
        "conversations": "Conversations",
        "open-threads": "Open Threads",
        "personal": "Personal",
        "tony": "Tony",
    }
    folder = parts[0] if len(parts) > 1 else ""
    section = section_map.get(folder, "Other")

    stem = "/".join(parts).replace(".md", "")
    link = f"[[{stem}]]"
    new_entry = f"- {link} — {summary}"

    content = index_path.read_text(encoding="utf-8")

    # Remove existing entry for this page if present
    content = re.sub(rf"^- \[\[{re.escape(stem)}\]\].*\n?", "", content, flags=re.MULTILINE)

    # Replace *(none yet)* placeholder or append under section
    section_pattern = rf"(## {re.escape(section)}\n)(\*\(none yet\)\*)"
    if re.search(section_pattern, content):
        content = re.sub(section_pattern, rf"\1{new_entry}", content)
    else:
        section_header = f"## {section}\n"
        if section_header in content:
            content = content.replace(section_header, f"{section_header}{new_entry}\n", 1)
        else:
            content += f"\n## {section}\n{new_entry}\n"

    # Bump updated date
    content = re.sub(r"^updated:.*$", f"updated: {today}", content, flags=re.MULTILINE)
    index_path.write_text(content, encoding="utf-8")


def _wiki_append_log(page: str, today: str) -> None:
    """Append one entry to log.md."""
    log_path = _WIKI_ROOT / "log.md"
    if not log_path.exists():
        return
    entry = f"\n## [{today}] update | {page}\n"
    with open(log_path, "a", encoding="utf-8") as f:
        f.write(entry)


@mcp.resource("desktop://cwd")
def get_cwd() -> str:
    """Current working directory."""
    return os.getcwd()


# ---------------------------------------------------------------------------
# Git workflow tools
# ---------------------------------------------------------------------------

@mcp.tool()
def start_request(description: str) -> dict:
    """Start a new development request.

    Creates branch tony/<timestamp>_<slug>, pushes to origin.
    Call this before making any changes to the TonyAI project.
    """
    return git_workflow.start_request(description)


@mcp.tool()
def commit_task(message: str) -> dict:
    """Stage all changes and commit them to the active request branch, then push.

    Call after each meaningful unit of work.
    """
    return git_workflow.commit_task(message)


@mcp.tool()
def finish_request(pr_title: str, pr_body: str) -> dict:
    """Push the branch and open a PR against dev via the gh CLI.

    Call when the full request is done. Do NOT merge manually.
    """
    return git_workflow.finish_request(pr_title, pr_body)


@mcp.tool()
def check_pr_reviews(pr_number: int | None = None) -> dict:
    """Fetch review and comment data for a PR from GitHub.

    If pr_number is omitted, uses the PR from the active request state.
    """
    return git_workflow.check_pr_reviews(pr_number)


@mcp.tool()
def get_workflow_status() -> dict:
    """Return a snapshot of the current git workflow state.

    Call at session start to check for any in-progress request to resume.
    """
    return git_workflow.get_workflow_status()


if __name__ == "__main__":
    # stdio transport for Copilot SDK subprocess mode
    mcp.run()
