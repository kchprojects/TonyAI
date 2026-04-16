from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from tony_ai.mcp.git_workflow import (
    _load_state,
    _slugify,
    check_pr_reviews,
    commit_task,
    finish_request,
    get_workflow_status,
    start_request,
)


# ---------------------------------------------------------------------------
# Helper: _slugify
# ---------------------------------------------------------------------------

def test_slugify_basic():
    assert _slugify("Hello World!") == "hello_world"


def test_slugify_truncates():
    long_text = "a" * 100
    result = _slugify(long_text)
    assert len(result) <= 50


def test_slugify_special_chars():
    assert _slugify("Fix: bug #42 (urgent)") == "fix_bug_42_urgent"


# ---------------------------------------------------------------------------
# Helper: _load_state
# ---------------------------------------------------------------------------

def test_load_state_missing(tmp_path):
    """Returns {} when the state file does not exist."""
    with patch("tony_ai.mcp.git_workflow._state_path", return_value=tmp_path / "nonexistent.json"):
        result = _load_state()
    assert result == {}


def test_load_state_reads_existing(tmp_path):
    state_file = tmp_path / "git_state.json"
    state_file.write_text(json.dumps({"branch": "tony/test"}), encoding="utf-8")
    with patch("tony_ai.mcp.git_workflow._state_path", return_value=state_file):
        result = _load_state()
    assert result == {"branch": "tony/test"}


# ---------------------------------------------------------------------------
# Tool: start_request
# ---------------------------------------------------------------------------

def test_start_request_blocks_when_active():
    """If state has a branch, returns error dict instead of creating a new branch."""
    active_state = {"branch": "tony/20240101_000000_existing", "description": "old", "pr_number": None, "started_at": "2024-01-01T00:00:00"}
    with patch("tony_ai.mcp.git_workflow._load_state", return_value=active_state):
        result = start_request("new task")
    assert "error" in result
    assert result["active_branch"] == "tony/20240101_000000_existing"


def test_start_request_creates_branch():
    """Happy path: creates branch, pushes, saves state, returns status."""
    mock_repo = MagicMock()

    with (
        patch("tony_ai.mcp.git_workflow._load_state", return_value={}),
        patch("tony_ai.mcp.git_workflow._save_state") as mock_save,
        patch("tony_ai.mcp.git_workflow._get_repo", return_value=mock_repo),
    ):
        result = start_request("add feature x")

    assert result["status"] == "started"
    assert "tony/" in result["branch"]
    assert "add_feature_x" in result["branch"]
    mock_save.assert_called_once()


# ---------------------------------------------------------------------------
# Tool: commit_task
# ---------------------------------------------------------------------------

def test_commit_task_no_active_request():
    """Returns error when there is no active request in state."""
    with patch("tony_ai.mcp.git_workflow._load_state", return_value={}):
        result = commit_task("some message")
    assert result == {"error": "No active request"}


def test_commit_task_nothing_to_commit():
    mock_repo = MagicMock()
    mock_repo.is_dirty.return_value = False
    mock_repo.untracked_files = []

    with (
        patch("tony_ai.mcp.git_workflow._load_state", return_value={"branch": "tony/xyz"}),
        patch("tony_ai.mcp.git_workflow._get_repo", return_value=mock_repo),
    ):
        result = commit_task("empty commit")

    assert result == {"status": "nothing_to_commit"}


def test_commit_task_commits_and_pushes():
    mock_repo = MagicMock()
    mock_repo.is_dirty.return_value = True

    with (
        patch("tony_ai.mcp.git_workflow._load_state", return_value={"branch": "tony/abc"}),
        patch("tony_ai.mcp.git_workflow._get_repo", return_value=mock_repo),
    ):
        result = commit_task("feat: add thing")

    assert result["status"] == "committed"
    assert result["message"] == "feat: add thing"
    assert result["branch"] == "tony/abc"
    mock_repo.index.commit.assert_called_once_with("feat: add thing")
    mock_repo.git.push.assert_called_once()


# ---------------------------------------------------------------------------
# Tool: finish_request
# ---------------------------------------------------------------------------

def test_finish_request_no_active_request():
    with patch("tony_ai.mcp.git_workflow._load_state", return_value={}):
        result = finish_request("Title", "Body")
    assert "error" in result


def test_finish_request_creates_pr():
    import subprocess as _sp

    mock_repo = MagicMock()
    mock_proc = MagicMock()
    mock_proc.returncode = 0
    mock_proc.stdout = "https://github.com/owner/repo/pull/42\n"
    mock_proc.stderr = ""

    with (
        patch("tony_ai.mcp.git_workflow._load_state", return_value={"branch": "tony/abc", "pr_number": None}),
        patch("tony_ai.mcp.git_workflow._get_repo", return_value=mock_repo),
        patch("tony_ai.mcp.git_workflow._save_state") as mock_save,
        patch("tony_ai.mcp.git_workflow.subprocess.run", return_value=mock_proc),
    ):
        result = finish_request("My PR Title", "My PR body")

    assert result["pr_number"] == 42
    assert result["pr_url"] == "https://github.com/owner/repo/pull/42"
    mock_save.assert_called_once()


# ---------------------------------------------------------------------------
# Tool: check_pr_reviews
# ---------------------------------------------------------------------------

def test_check_pr_reviews_no_pr_number():
    with patch("tony_ai.mcp.git_workflow._load_state", return_value={}):
        result = check_pr_reviews()
    assert "error" in result


def test_check_pr_reviews_uses_state_pr():
    mock_proc = MagicMock()
    mock_proc.returncode = 0
    mock_proc.stdout = json.dumps({"state": "OPEN", "title": "Test PR", "reviews": [], "comments": [], "url": "https://github.com/owner/repo/pull/7"})

    with (
        patch("tony_ai.mcp.git_workflow._load_state", return_value={"pr_number": 7}),
        patch("tony_ai.mcp.git_workflow.subprocess.run", return_value=mock_proc),
    ):
        result = check_pr_reviews()

    assert result["state"] == "OPEN"
    assert result["title"] == "Test PR"


# ---------------------------------------------------------------------------
# Tool: get_workflow_status
# ---------------------------------------------------------------------------

def test_get_workflow_status_no_active():
    """Returns dict with active_request: {} and current_branch from mocked repo."""
    mock_repo = MagicMock()
    mock_repo.active_branch.name = "dev"
    mock_repo.is_dirty.return_value = False
    mock_repo.untracked_files = []

    with (
        patch("tony_ai.mcp.git_workflow._load_state", return_value={}),
        patch("tony_ai.mcp.git_workflow._get_repo", return_value=mock_repo),
    ):
        result = get_workflow_status()

    assert result["active_request"] == {}
    assert result["current_branch"] == "dev"
    assert result["uncommitted_changes"] is False
    assert result["pr"] is None


def test_get_workflow_status_with_pr():
    mock_repo = MagicMock()
    mock_repo.active_branch.name = "tony/20240101_fix"
    mock_repo.is_dirty.return_value = True
    mock_repo.untracked_files = []

    mock_proc = MagicMock()
    mock_proc.returncode = 0
    mock_proc.stdout = json.dumps({"state": "OPEN", "url": "https://github.com/owner/repo/pull/5"})

    with (
        patch("tony_ai.mcp.git_workflow._load_state", return_value={"branch": "tony/20240101_fix", "pr_number": 5}),
        patch("tony_ai.mcp.git_workflow._get_repo", return_value=mock_repo),
        patch("tony_ai.mcp.git_workflow.subprocess.run", return_value=mock_proc),
    ):
        result = get_workflow_status()

    assert result["current_branch"] == "tony/20240101_fix"
    assert result["uncommitted_changes"] is True
    assert result["pr"]["state"] == "OPEN"
