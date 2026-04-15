from src.mcp.server import list_dir, read_file, run_shell, write_file


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