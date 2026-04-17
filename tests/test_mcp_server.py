from __future__ import annotations

import subprocess
from pathlib import Path

import tony_ai.mcp.server as server_mod
from tony_ai.mcp.server import list_dir, read_file, run_shell, write_file


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

class _CP:
    """Minimal fake subprocess.CompletedProcess."""

    def __init__(self, stdout: str = "", stderr: str = "", returncode: int = 0) -> None:
        self.stdout = stdout
        self.stderr = stderr
        self.returncode = returncode


def _minimal_wiki(tmp_path: Path) -> Path:
    """Populate *tmp_path* with the minimum files wiki tools expect."""
    (tmp_path / "INDEX.md").write_text(
        "updated: 2026-01-01\n## Personal\n*(none yet)*\n", encoding="utf-8"
    )
    (tmp_path / "log.md").write_text("# Log\n", encoding="utf-8")
    return tmp_path


# ---------------------------------------------------------------------------
# Existing tests (unchanged)
# ---------------------------------------------------------------------------

def test_list_dir_returns_list(tmp_path) -> None:
    result = list_dir(str(tmp_path))
    assert isinstance(result, list)


def test_write_then_read_file(tmp_path) -> None:
    target = str(tmp_path / "test.txt")
    write_file(target, "hello")
    assert read_file(target) == "hello"


def test_run_shell_returns_output() -> None:
    output = run_shell("echo hello")
    assert "hello" in output.lower()


# ---------------------------------------------------------------------------
# _wiki_git_commit — unit tests via subprocess.run stubbing
# ---------------------------------------------------------------------------

def test_wiki_git_commit_no_git_dir(tmp_path, monkeypatch) -> None:
    """Returns skipped/wiki_repo_not_found when the wiki .git directory is absent."""
    monkeypatch.setattr(server_mod, "_WIKI_ROOT", tmp_path)
    result = server_mod._wiki_git_commit("any message")
    assert result == {"status": "skipped", "reason": "wiki_repo_not_found"}


def test_wiki_git_commit_no_changes(tmp_path, monkeypatch) -> None:
    """Returns skipped/no_changes when git status --porcelain is empty."""
    (tmp_path / ".git").mkdir()
    monkeypatch.setattr(server_mod, "_WIKI_ROOT", tmp_path)
    monkeypatch.setattr(subprocess, "run", lambda *a, **kw: _CP(stdout=""))
    result = server_mod._wiki_git_commit("any message")
    assert result == {"status": "skipped", "reason": "no_changes"}


def test_wiki_git_commit_committed(tmp_path, monkeypatch) -> None:
    """Returns committed when status has output and add+commit both succeed."""
    (tmp_path / ".git").mkdir()
    monkeypatch.setattr(server_mod, "_WIKI_ROOT", tmp_path)

    calls: list[list[str]] = []

    def fake_run(cmd: list[str], **kw):
        calls.append(list(cmd))
        if "status" in cmd:
            return _CP(stdout=" M personal/goals.md")
        return _CP()

    monkeypatch.setattr(subprocess, "run", fake_run)
    result = server_mod._wiki_git_commit("wiki: update personal/goals.md")

    assert result["status"] == "committed"
    assert result["message"] == "wiki: update personal/goals.md"
    # Exactly three subprocess calls: status, add, commit
    assert len(calls) == 3


def test_wiki_git_commit_add_fails(tmp_path, monkeypatch) -> None:
    """Returns error when git add exits non-zero."""
    (tmp_path / ".git").mkdir()
    monkeypatch.setattr(server_mod, "_WIKI_ROOT", tmp_path)

    def fake_run(cmd: list[str], **kw):
        if "status" in cmd:
            return _CP(stdout=" M file.md")
        if "add" in cmd:
            return _CP(returncode=1, stderr="add error detail")
        return _CP()

    monkeypatch.setattr(subprocess, "run", fake_run)
    result = server_mod._wiki_git_commit("msg")
    assert result["status"] == "error"
    assert "add error detail" in result["error"]


def test_wiki_git_commit_commit_fails(tmp_path, monkeypatch) -> None:
    """Returns error when git commit exits non-zero."""
    (tmp_path / ".git").mkdir()
    monkeypatch.setattr(server_mod, "_WIKI_ROOT", tmp_path)

    def fake_run(cmd: list[str], **kw):
        if "status" in cmd:
            return _CP(stdout=" M file.md")
        if "add" in cmd:
            return _CP()
        # commit step
        return _CP(returncode=1, stderr="commit error detail")

    monkeypatch.setattr(subprocess, "run", fake_run)
    result = server_mod._wiki_git_commit("msg")
    assert result["status"] == "error"
    assert "commit error detail" in result["error"]


# ---------------------------------------------------------------------------
# wiki_write tests
# ---------------------------------------------------------------------------

def test_wiki_write_calls_commit_with_page_path(tmp_path, monkeypatch) -> None:
    """Commit helper is called with a message that contains the page path."""
    wiki = _minimal_wiki(tmp_path)
    monkeypatch.setattr(server_mod, "_WIKI_ROOT", wiki)

    captured: list[str] = []
    monkeypatch.setattr(server_mod, "_wiki_git_commit", lambda msg: captured.append(msg) or {"status": "committed"})

    server_mod.wiki_write("personal/goals.md", "# Goals\n")

    assert captured, "commit helper was never called"
    assert "personal/goals.md" in captured[0]


def test_wiki_write_return_includes_commit_status_bracket(tmp_path, monkeypatch) -> None:
    """Return string includes the commit status inside square brackets."""
    wiki = _minimal_wiki(tmp_path)
    monkeypatch.setattr(server_mod, "_WIKI_ROOT", wiki)
    monkeypatch.setattr(server_mod, "_wiki_git_commit", lambda msg: {"status": "committed"})

    result = server_mod.wiki_write("personal/goals.md", "# Goals\n")
    assert "[committed]" in result


def test_wiki_write_skipped_status_in_return(tmp_path, monkeypatch) -> None:
    """Return string reflects a skipped commit status correctly."""
    wiki = _minimal_wiki(tmp_path)
    monkeypatch.setattr(server_mod, "_WIKI_ROOT", wiki)
    monkeypatch.setattr(server_mod, "_wiki_git_commit", lambda msg: {"status": "skipped"})

    result = server_mod.wiki_write("personal/goals.md", "# Goals\n")
    assert "[skipped]" in result


# ---------------------------------------------------------------------------
# wiki_lint tests
# ---------------------------------------------------------------------------

def test_wiki_lint_contains_health_report_header(tmp_path, monkeypatch) -> None:
    """Report always begins with the canonical header line."""
    wiki = _minimal_wiki(tmp_path)
    monkeypatch.setattr(server_mod, "_WIKI_ROOT", wiki)
    monkeypatch.setattr(server_mod, "_wiki_git_commit", lambda msg: {"status": "skipped"})

    report = server_mod.wiki_lint()
    assert "# Wiki Health Report" in report


def test_wiki_lint_trailing_commit_line(tmp_path, monkeypatch) -> None:
    """Report ends with an italicised _Commit: <status>_ line."""
    wiki = _minimal_wiki(tmp_path)
    monkeypatch.setattr(server_mod, "_WIKI_ROOT", wiki)
    monkeypatch.setattr(server_mod, "_wiki_git_commit", lambda msg: {"status": "committed"})

    report = server_mod.wiki_lint()
    assert "_Commit: committed_" in report


def test_wiki_lint_logs_operation_to_log_file(tmp_path, monkeypatch) -> None:
    """wiki_lint appends an entry with operation 'lint' and target 'health-check' to log.md."""
    wiki = _minimal_wiki(tmp_path)
    monkeypatch.setattr(server_mod, "_WIKI_ROOT", wiki)
    monkeypatch.setattr(server_mod, "_wiki_git_commit", lambda msg: {"status": "skipped"})

    server_mod.wiki_lint()

    log_content = (wiki / "log.md").read_text(encoding="utf-8")
    assert "lint | health-check" in log_content


# ---------------------------------------------------------------------------
# New integration tests
# ---------------------------------------------------------------------------

def test_wiki_write_auto_commit_integration(tmp_path, monkeypatch) -> None:
    """Full integration: page written, log appended, commit called with page in message."""
    wiki = _minimal_wiki(tmp_path)
    monkeypatch.setattr(server_mod, "_WIKI_ROOT", wiki)

    captured: list[str] = []

    def fake_commit(msg: str) -> dict:
        captured.append(msg)
        return {"status": "committed"}

    monkeypatch.setattr(server_mod, "_wiki_git_commit", fake_commit)

    result = server_mod.wiki_write("personal/goals.md", "# Goals\ncontent\n")

    # Page written
    assert (wiki / "personal" / "goals.md").read_text(encoding="utf-8") == "# Goals\ncontent\n"
    # Log appended
    log_content = (wiki / "log.md").read_text(encoding="utf-8")
    assert "personal/goals.md" in log_content
    # Commit called with page path in message
    assert captured, "commit helper was never called"
    assert "personal/goals.md" in captured[0]
    # Return includes commit status
    assert "[committed]" in result


def test_wiki_lint_log_and_commit_status(tmp_path, monkeypatch) -> None:
    """wiki_lint logs 'lint | health-check' and report contains commit status."""
    wiki = _minimal_wiki(tmp_path)
    monkeypatch.setattr(server_mod, "_WIKI_ROOT", wiki)
    monkeypatch.setattr(server_mod, "_wiki_git_commit", lambda msg: {"status": "committed"})

    report = server_mod.wiki_lint()

    log_content = (wiki / "log.md").read_text(encoding="utf-8")
    assert "lint | health-check" in log_content
    assert "_Commit: committed_" in report


def test_wiki_git_commit_no_repo_returns_skipped(tmp_path, monkeypatch) -> None:
    """Returns skipped/wiki_repo_not_found when wiki dir has no .git directory."""
    monkeypatch.setattr(server_mod, "_WIKI_ROOT", tmp_path)
    result = server_mod._wiki_git_commit("wiki: test commit")
    assert result["status"] == "skipped"
    assert result["reason"] == "wiki_repo_not_found"