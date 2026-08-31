import asyncio
import json
import os
import sys
from pathlib import Path

import pytest

import mewcode.tool.bash as bash_module
from mewcode.tool import Registry, new_default_registry
from mewcode.tool.bash import BashTool, _decode_output
from mewcode.tool.edit_file import EditFileTool
from mewcode.tool.glob_tool import GlobTool
from mewcode.tool.grep_tool import GrepTool
from mewcode.tool.read_file import ReadFileTool
from mewcode.tool.write_file import WriteFileTool


def execute(tool, args: dict[str, object]):
    return asyncio.run(tool.execute(json.dumps(args)))


def test_registry_exports_six_tools_and_rejects_duplicates() -> None:
    registry = new_default_registry()

    definitions = registry.definitions()

    assert [definition.name for definition in definitions] == [
        "read_file",
        "write_file",
        "edit_file",
        "bash",
        "glob",
        "grep",
    ]
    assert registry.get("read_file") is not None
    assert registry.get("missing") is None
    with pytest.raises(ValueError, match="工具名称重复"):
        registry.register(ReadFileTool())


def test_read_file_adds_line_numbers_and_truncates(tmp_path: Path) -> None:
    path = tmp_path / "large.txt"
    path.write_text("\n".join(f"line {index}" for index in range(2100)), encoding="utf-8")

    result = execute(ReadFileTool(), {"path": str(path)})
    missing = execute(ReadFileTool(), {"path": str(tmp_path / "missing.txt")})

    assert result.is_error is False
    assert "     1\tline 0" in result.content
    assert "  2000\tline 1999" in result.content
    assert result.content.endswith("[truncated]")
    assert missing.is_error is True
    assert "文件不存在" in missing.content


def test_write_file_creates_parents_and_overwrites(tmp_path: Path) -> None:
    path = tmp_path / "nested" / "file.txt"
    tool = WriteFileTool()

    first = execute(tool, {"path": str(path), "content": "first"})
    second = execute(tool, {"path": str(path), "content": "second"})

    assert first.is_error is False
    assert second.is_error is False
    assert path.read_text(encoding="utf-8") == "second"


def test_edit_file_requires_a_unique_match(tmp_path: Path) -> None:
    path = tmp_path / "file.txt"
    tool = EditFileTool()
    path.write_text("one two", encoding="utf-8")

    success = execute(
        tool,
        {"path": str(path), "old_string": "one", "new_string": "three"},
    )
    missing = execute(
        tool,
        {"path": str(path), "old_string": "absent", "new_string": "value"},
    )
    path.write_text("same same", encoding="utf-8")
    repeated = execute(
        tool,
        {"path": str(path), "old_string": "same", "new_string": "value"},
    )

    assert success.is_error is False
    assert missing.is_error is True
    assert "0 处" in missing.content
    assert repeated.is_error is True
    assert "2 处" in repeated.content
    assert path.read_text(encoding="utf-8") == "same same"


def test_bash_returns_output_and_nonzero_status() -> None:
    success = execute(BashTool(), {"command": "echo hello"})
    command = f'"{sys.executable}" -c "import sys; print(\'bad\', file=sys.stderr); sys.exit(3)"'
    failure = execute(BashTool(), {"command": command})

    assert success.is_error is False
    assert "hello" in success.content
    assert "exit_code: 0" in success.content
    assert failure.is_error is True
    assert "exit_code: 3" in failure.content
    assert "bad" in failure.content


def test_bash_output_decoder_prefers_utf8_and_falls_back_to_cp936() -> None:
    utf8 = "UTF-8 中文".encode()
    cp936 = "驱动器中的卷是项目".encode("cp936")

    assert _decode_output(utf8, fallback_encoding="cp936") == "UTF-8 中文"
    assert _decode_output(cp936, fallback_encoding="cp936") == "驱动器中的卷是项目"
    assert "�" not in _decode_output(cp936, fallback_encoding="cp936")


def test_bash_output_decoder_tolerates_invalid_bytes_and_codec_names() -> None:
    damaged = _decode_output(b"text\x81", fallback_encoding="cp936")
    unknown_codec = _decode_output(b"text\xff", fallback_encoding="not-a-codec")

    assert isinstance(damaged, str)
    assert damaged.startswith("text")
    assert isinstance(unknown_codec, str)


def test_bash_decodes_fallback_encoding_from_stdout_and_stderr(monkeypatch) -> None:
    monkeypatch.setattr(bash_module, "_fallback_output_encoding", lambda: "cp936")
    script = (
        "import sys;"
        "sys.stdout.buffer.write('中文标准输出'.encode('cp936'));"
        "sys.stderr.buffer.write('中文错误输出'.encode('cp936'))"
    )
    command = f'"{sys.executable}" -c "{script}"'

    result = execute(BashTool(), {"command": command})

    assert result.is_error is False
    assert "中文标准输出" in result.content
    assert "中文错误输出" in result.content
    assert "�" not in result.content


@pytest.mark.skipif(os.name != "nt", reason="requires Windows cmd.exe")
def test_bash_decodes_real_windows_console_output() -> None:
    result = execute(BashTool(), {"command": "echo 中文输出"})

    assert result.is_error is False
    assert "中文输出" in result.content
    assert "�" not in result.content


def test_registry_converts_timeout_and_unknown_tool_to_results() -> None:
    registry = Registry()
    registry.register(BashTool())
    command = f'"{sys.executable}" -c "import time; time.sleep(5)"'

    timeout = asyncio.run(registry.execute("bash", json.dumps({"command": command}), 0.05))
    unknown = asyncio.run(registry.execute("missing", "{}"))

    assert timeout.is_error is True
    assert "超时" in timeout.content
    assert unknown.is_error is True
    assert "未知工具" in unknown.content


def test_glob_and_grep_return_sorted_bounded_matches(tmp_path: Path) -> None:
    first = tmp_path / "a.py"
    second = tmp_path / "nested" / "b.py"
    second.parent.mkdir()
    first.write_text("needle = 1\n", encoding="utf-8")
    second.write_text("needle = 2\n", encoding="utf-8")
    (tmp_path / "skip.txt").write_text("needle", encoding="utf-8")

    glob_result = execute(GlobTool(), {"path": str(tmp_path), "pattern": "**/*.py"})
    grep_result = execute(
        GrepTool(),
        {"path": str(tmp_path), "pattern": "needle", "glob": "*.py"},
    )
    invalid_regex = execute(GrepTool(), {"path": str(tmp_path), "pattern": "["})

    assert glob_result.is_error is False
    assert glob_result.content.splitlines() == sorted([first.as_posix(), second.as_posix()])
    assert grep_result.is_error is False
    assert f"{first.as_posix()}:1:needle = 1" in grep_result.content
    assert f"{second.as_posix()}:1:needle = 2" in grep_result.content
    assert "skip.txt" not in grep_result.content
    assert invalid_regex.is_error is True
    assert "正则非法" in invalid_regex.content


def test_bash_and_grep_truncate_large_results(tmp_path: Path) -> None:
    command = f'"{sys.executable}" -c "print(\'x\' * 40000)"'
    bash_result = execute(BashTool(), {"command": command})
    source = tmp_path / "many.txt"
    source.write_text("\n".join(f"needle {index}" for index in range(105)), encoding="utf-8")
    grep_result = execute(GrepTool(), {"path": str(source), "pattern": "needle"})

    assert bash_result.is_error is False
    assert bash_result.content.endswith("[truncated]")
    assert grep_result.is_error is False
    assert len(grep_result.content.splitlines()) == 101
    assert grep_result.content.endswith("[truncated]")
