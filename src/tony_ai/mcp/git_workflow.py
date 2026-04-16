from __future__ import annotations

import json
import re
import subprocess
from datetime import datetime
from pathlib import Path

import git

_REPO_ROOT = Path(__file__).parent.parent.parent.parent


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------

def _get_repo() -> git.Repo:
    """Return a Repo instance for the TonyAI repository."""
    return git.Repo(str(_REPO_ROOT))


def _slugify(text: str) -> str:
    """Lowercase, replace non-alphanumeric chars with underscores, max 50 chars."""
    slug = text.lower()
    slug = re.sub(r"[^a-z0-9]+", "_", slug)
    slug = slug.strip("_")
    return slug[:50]


def _state_path() -> Path:
    """Return path to the git workflow state file."""
    return Path(__file__).parent / "git_state.json"


def _load_state() -> dict:
    """Load workflow state from disk; return {} if the file does not exist."""
    path = _state_path()
    if not path.exists():
        return {}
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _save_state(data: dict) -> None:
    """Persist workflow state to disk."""
    with open(_state_path(), "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


# ---------------------------------------------------------------------------
# Tool functions (plain — decorated in server.py)
# ---------------------------------------------------------------------------

def start_request(description: str) -> dict:
    """Start a new development request.

    Creates branch tony/<timestamp>_<slug>, pushes to origin.
    Call this before making any changes to the TonyAI project.
    """
    state = _load_state()
    if state.get("branch"):
        return {
            "error": "An active request already exists. Finish or close it before starting a new one.",
            "active_branch": state["branch"],
        }

    repo = _get_repo()

    # Sync dev branch
    repo.git.fetch("origin")
    repo.git.checkout("dev")
    repo.git.pull("origin", "dev")

    # Build unique branch name
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    slug = _slugify(description)
    branch_name = f"tony/{timestamp}_{slug}"

    # Create and push branch
    repo.git.checkout("-b", branch_name)
    repo.git.push("--set-upstream", "origin", branch_name)

    started_at = datetime.now().isoformat()
    new_state: dict = {
        "branch": branch_name,
        "description": description,
        "pr_number": None,
        "started_at": started_at,
    }
    _save_state(new_state)

    return {"branch": branch_name, "status": "started"}


def commit_task(message: str) -> dict:
    """Stage all changes and commit them to the active request branch, then push.

    Call after each meaningful unit of work.
    """
    state = _load_state()
    if not state.get("branch"):
        return {"error": "No active request"}

    repo = _get_repo()
    repo.git.add("-A")

    if not repo.is_dirty(index=True, untracked_files=True):
        return {"status": "nothing_to_commit"}

    repo.index.commit(message)
    repo.git.push()

    return {"status": "committed", "message": message, "branch": state["branch"]}


def finish_request(pr_title: str, pr_body: str) -> dict:
    """Push the branch and open a PR against dev via the gh CLI.

    Call when the full request is done. Do NOT merge manually.
    """
    state = _load_state()
    if not state.get("branch"):
        return {"error": "No active request"}

    repo = _get_repo()
    repo.git.push()

    result = subprocess.run(
        ["gh", "pr", "create", "--base", "dev", "--title", pr_title, "--body", pr_body],
        capture_output=True,
        text=True,
        cwd=str(_REPO_ROOT),
        check=False,
    )

    if result.returncode != 0:
        return {"error": result.stderr.strip(), "stdout": result.stdout.strip()}

    # Extract PR URL — last non-empty line of stdout
    lines = [l for l in result.stdout.splitlines() if l.strip()]
    pr_url = lines[-1].strip() if lines else ""

    # Extract PR number from URL
    m = re.search(r"/pull/(\d+)", pr_url)
    pr_number = int(m.group(1)) if m else None

    state["pr_number"] = pr_number
    state["pr_url"] = pr_url
    _save_state(state)

    return {"pr_url": pr_url, "pr_number": pr_number, "branch": state["branch"]}


def check_pr_reviews(pr_number: int | None = None) -> dict:
    """Fetch review and comment data for a PR from GitHub.

    If pr_number is omitted, uses the PR from the active request state.
    """
    if pr_number is None:
        state = _load_state()
        pr_number = state.get("pr_number")
    if pr_number is None:
        return {"error": "No PR number available. Provide pr_number or run finish_request first."}

    result = subprocess.run(
        [
            "gh", "pr", "view", str(pr_number),
            "--json", "reviews,comments,state,title,url",
        ],
        capture_output=True,
        text=True,
        cwd=str(_REPO_ROOT),
        check=False,
    )

    if result.returncode != 0:
        return {"error": result.stderr.strip()}

    return json.loads(result.stdout)


def get_workflow_status() -> dict:
    """Return a snapshot of the current git workflow state.

    Call at session start to check for any in-progress request to resume.
    """
    state = _load_state()
    repo = _get_repo()

    current_branch = repo.active_branch.name
    uncommitted_changes = repo.is_dirty(index=True, untracked_files=True) or bool(repo.untracked_files)

    pr_info: dict | None = None
    if state.get("pr_number"):
        result = subprocess.run(
            ["gh", "pr", "view", str(state["pr_number"]), "--json", "state,url"],
            capture_output=True,
            text=True,
            cwd=str(_REPO_ROOT),
            check=False,
        )
        if result.returncode == 0:
            pr_info = json.loads(result.stdout)

    return {
        "active_request": state,
        "current_branch": current_branch,
        "uncommitted_changes": uncommitted_changes,
        "pr": pr_info,
    }
