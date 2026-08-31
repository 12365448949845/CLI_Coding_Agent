"""Built-in prompt, runtime context, and startup banner."""

from __future__ import annotations

import os
import platform
from dataclasses import dataclass
from pathlib import PureWindowsPath
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .llm import ToolDefinition

SYSTEM_PROMPT = """You are MewCode, a concise and helpful terminal coding agent.
You can use tools to read, write, and edit files, run shell commands, find files, and search
source code. Use tools when you need real project information or must perform an action. After
receiving tool results, explain the actual outcome clearly. Use Markdown when it improves
readability, and never claim to have performed actions you did not perform.
""".strip()


@dataclass(frozen=True)
class RuntimeContext:
    os_name: str
    shell: str
    cwd: str


def detect_runtime_context() -> RuntimeContext:
    os_name = platform.system() or os.name
    if os_name == "Windows":
        comspec = os.environ.get("COMSPEC", "cmd.exe")
        shell = PureWindowsPath(comspec).name or "cmd.exe"
    else:
        shell = "/bin/sh"
    return RuntimeContext(os_name=os_name, shell=shell, cwd=os.getcwd())


def build_system_prompt(
    tools: list[ToolDefinition],
    context: RuntimeContext | None = None,
) -> str:
    runtime = context or detect_runtime_context()
    tool_names = ", ".join(tool.name for tool in tools) or "(none)"
    platform_rules = ""
    if runtime.os_name == "Windows":
        platform_rules = """
- The bash tool runs commands with cmd.exe. Use cmd.exe syntax such as `cd` and `dir`.
- Do not use POSIX-only commands or syntax such as `pwd`, `ls`, `cat`, or `export`.
""".rstrip()
    else:
        platform_rules = f"- The bash tool runs commands with {runtime.shell} syntax."

    return f"""{SYSTEM_PROMPT}

Runtime environment:
- Operating system: {runtime.os_name}
- Shell used by the bash tool: {runtime.shell}
- Working directory: {runtime.cwd}

Available tool API names (exact and exhaustive): {tool_names}

Tool rules:
- Only claim and call tools from the exact list above. Never invent tools such as ToolSearch.
- Preserve each tool name exactly as shown; do not convert snake_case names to PascalCase.
{platform_rules}
- Creating, writing, editing, replacing, or deleting files is an action request. A branch check,
  status check, read, glob, or grep is only inspection and does not complete the action.
- For file-changing requests, include the actual write_file, edit_file, or mutating bash call in
  the first tool batch. Never claim a file was changed unless the matching tool result succeeded.
- The glob tool supports pathlib-style patterns such as `**/*.py`.
- The glob tool does not support brace expansion such as `*.{{py,json}}`.
  Use multiple glob calls in the same first tool batch when matching several extensions.
- Only one tool-execution batch is available per user turn. Include all independent tool calls
  needed in the first batch, then answer from their results without requesting more tools.
""".strip()


CAT_BANNER = r""" /\_/\
( o.o )
 > ^ <"""


def render_banner(version: str, cwd: str) -> str:
    return f"{CAT_BANNER}\nMewCode v{version}\n{cwd}\nReady. Type a message or /exit to quit."
