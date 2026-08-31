import os

import mewcode.prompt as prompt_module
from mewcode.llm import ToolDefinition
from mewcode.prompt import RuntimeContext, build_system_prompt, detect_runtime_context


def definitions() -> list[ToolDefinition]:
    return [
        ToolDefinition(name, f"Description for {name}", {"type": "object"})
        for name in (
            "read_file",
            "write_file",
            "edit_file",
            "bash",
            "glob",
            "grep",
        )
    ]


def test_runtime_context_uses_current_working_directory(monkeypatch, tmp_path) -> None:
    initial = detect_runtime_context()
    assert initial.cwd == os.getcwd()

    monkeypatch.chdir(tmp_path)
    changed = detect_runtime_context()

    assert changed.cwd == str(tmp_path)
    assert changed.cwd != initial.cwd


def test_runtime_context_reports_the_command_executor_shell(monkeypatch) -> None:
    monkeypatch.setattr(prompt_module.platform, "system", lambda: "Windows")
    monkeypatch.setenv("COMSPEC", r"C:\Windows\System32\cmd.exe")
    windows = detect_runtime_context()

    monkeypatch.setattr(prompt_module.platform, "system", lambda: "Linux")
    posix = detect_runtime_context()

    assert windows.shell == "cmd.exe"
    assert posix.shell == "/bin/sh"


def test_windows_prompt_contains_exact_tools_and_platform_rules() -> None:
    tool_definitions = definitions()
    result = build_system_prompt(
        tool_definitions,
        RuntimeContext("Windows", "cmd.exe", r"C:\work\mewcode"),
    )

    assert "Operating system: Windows" in result
    assert "Shell used by the bash tool: cmd.exe" in result
    assert r"Working directory: C:\work\mewcode" in result
    assert "read_file, write_file, edit_file, bash, glob, grep" in result
    assert "ToolSearch" in result
    assert "Never invent tools such as ToolSearch" in result
    assert "ReadFile" not in result
    assert "Do not use POSIX-only commands" in result
    assert "`pwd`, `ls`, `cat`, or `export`" in result
    assert "A branch check" in result
    assert "Never claim a file was changed unless the matching tool result succeeded" in result
    assert "does not support brace expansion" in result
    assert "*.{py,json}" in result
    assert "multiple glob calls in the same first tool batch" in result


def test_posix_prompt_does_not_claim_windows_and_preserves_tool_order() -> None:
    result = build_system_prompt(
        definitions(),
        RuntimeContext("Linux", "/bin/sh", "/work/mewcode"),
    )

    assert "Operating system: Linux" in result
    assert "Shell used by the bash tool: /bin/sh" in result
    assert "cmd.exe syntax" not in result
    tools_line = next(
        line for line in result.splitlines() if line.startswith("Available tool API names")
    )
    positions = [
        tools_line.index(name)
        for name in (
            "read_file",
            "write_file",
            "edit_file",
            "bash",
            "glob",
            "grep",
        )
    ]
    assert positions == sorted(positions)


def test_prompt_does_not_include_unrelated_environment_values(monkeypatch) -> None:
    marker = "DO_NOT_LEAK_THIS_VALUE"
    monkeypatch.setenv("MEWCODE_SECRET_MARKER", marker)

    result = build_system_prompt(
        definitions(),
        RuntimeContext("Windows", "cmd.exe", r"C:\work"),
    )

    assert marker not in result
