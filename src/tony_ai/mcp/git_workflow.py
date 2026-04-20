from __future__ import annotations

from pathlib import Path

import git

_REPO_ROOT = Path(__file__).parent.parent.parent.parent


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------

def _get_repo() -> git.Repo:
    """Return a Repo instance for the TonyAI repository."""
    return git.Repo(str(_REPO_ROOT))


def commit_task(message: str) -> dict:
    """Stage all changes and commit them on the current branch, then push.

    Call when a task is finished.
    """
    repo = _get_repo()
    branch = repo.active_branch.name
    repo.git.add("-A")

    if not repo.is_dirty(index=True, untracked_files=True):
        return {"status": "nothing_to_commit"}

    repo.index.commit(message)
    try:
        repo.git.push()
    except git.GitCommandError as exc:
        return {"error": str(exc), "status": "push_failed", "branch": branch}

    return {"status": "committed", "message": message, "branch": branch}


def get_workflow_status() -> dict:
    """Return a snapshot of commit-only git workflow state."""
    repo = _get_repo()

    current_branch = repo.active_branch.name
    uncommitted_changes = repo.is_dirty(index=True, untracked_files=True) or bool(repo.untracked_files)

    tracking_branch = None
    try:
        tracking_branch = str(repo.active_branch.tracking_branch())
    except TypeError:
        tracking_branch = None

    return {
        "workflow_mode": "commit_only",
        "current_branch": current_branch,
        "tracking_branch": tracking_branch,
        "uncommitted_changes": uncommitted_changes,
    }
