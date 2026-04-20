from __future__ import annotations

from unittest.mock import MagicMock, patch

from git import GitCommandError

from tony_ai.mcp.git_workflow import commit_task, get_workflow_status


def test_commit_task_nothing_to_commit():
    mock_repo = MagicMock()
    mock_repo.active_branch.name = "dev"
    mock_repo.is_dirty.return_value = False
    mock_repo.untracked_files = []

    with patch("tony_ai.mcp.git_workflow._get_repo", return_value=mock_repo):
        result = commit_task("empty commit")

    assert result == {"status": "nothing_to_commit"}


def test_commit_task_commits_and_pushes():
    mock_repo = MagicMock()
    mock_repo.active_branch.name = "dev"
    mock_repo.is_dirty.return_value = True

    with patch("tony_ai.mcp.git_workflow._get_repo", return_value=mock_repo):
        result = commit_task("feat: add thing")

    assert result["status"] == "committed"
    assert result["message"] == "feat: add thing"
    assert result["branch"] == "dev"
    mock_repo.index.commit.assert_called_once_with("feat: add thing")
    mock_repo.git.push.assert_called_once()


def test_commit_task_push_failure():
    mock_repo = MagicMock()
    mock_repo.active_branch.name = "dev"
    mock_repo.is_dirty.return_value = True
    mock_repo.git.push.side_effect = GitCommandError("push", 1, stderr="push failed")

    with patch("tony_ai.mcp.git_workflow._get_repo", return_value=mock_repo):
        result = commit_task("feat: add thing")

    assert result["status"] == "push_failed"
    assert result["branch"] == "dev"
    assert "push failed" in result["error"]


def test_get_workflow_status():
    mock_repo = MagicMock()
    mock_repo.active_branch.name = "dev"
    mock_repo.active_branch.tracking_branch.return_value = "origin/dev"
    mock_repo.is_dirty.return_value = False
    mock_repo.untracked_files = []

    with patch("tony_ai.mcp.git_workflow._get_repo", return_value=mock_repo):
        result = get_workflow_status()

    assert result["workflow_mode"] == "commit_only"
    assert result["current_branch"] == "dev"
    assert result["tracking_branch"] == "origin/dev"
    assert result["uncommitted_changes"] is False
