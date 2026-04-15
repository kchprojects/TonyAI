import os
import subprocess
from pathlib import Path

from mcp.server.fastmcp import FastMCP


_REPO_ROOT = Path(__file__).parent.parent.parent
_VENV_PYTHON = str(_REPO_ROOT / ".venv" / "Scripts" / "python.exe")

mcp = FastMCP("tony-desktop")


@mcp.tool()
def run_shell(command: str, cwd: str | None = None) -> str:
    """Run a shell command. Returns stdout and stderr."""
    result = subprocess.run(
        command,
        shell=True,
        cwd=cwd or str(_REPO_ROOT),
        capture_output=True,
        text=True,
        timeout=120,
    )
    return result.stdout + result.stderr


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


@mcp.resource("desktop://cwd")
def get_cwd() -> str:
    """Current working directory."""
    return os.getcwd()


if __name__ == "__main__":
    # stdio transport for Copilot SDK subprocess mode
    mcp.run()
