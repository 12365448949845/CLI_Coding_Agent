"""Protocol-independent single-round tool orchestration."""

import asyncio
import json
import re
from collections.abc import AsyncIterator
from dataclasses import dataclass
from enum import Enum
from typing import Any

from ..conversation import Conversation
from ..llm import Provider, ToolCall, ToolResult
from ..tool import DEFAULT_TIMEOUT, Registry

SINGLE_ROUND_LIMIT_MESSAGE = "本轮已达到一次工具执行上限。请发送后续消息继续。"
UNBACKED_FILE_MUTATION_MESSAGE = (
    "本轮没有执行成功的写文件、改文件或可识别的写入命令，"
    "所以我不能确认文件已经创建或修改。请发送后续消息继续，我会在首批工具调用中直接执行实际写入。"
)

_FILE_MUTATION_WORDS = (
    "创建",
    "新建",
    "写入",
    "写到",
    "保存",
    "覆盖",
    "修改",
    "编辑",
    "替换",
    "删除",
    "移除",
    "重命名",
    "create",
    "write",
    "overwrite",
    "save",
    "edit",
    "modify",
    "replace",
    "delete",
    "remove",
    "rename",
)
_FILE_HINTS = (
    "文件",
    "file",
    "readme",
    "changelog",
    "license",
    "pyproject",
    ".md",
    ".py",
    ".txt",
    ".json",
    ".yaml",
    ".yml",
    ".toml",
    ".ini",
    ".cfg",
    ".env",
    ".csv",
    ".html",
    ".css",
    ".js",
    ".ts",
    ".tsx",
    ".jsx",
)
_EXPLANATION_MARKERS = ("如何", "怎么", "怎样", "how to", "how do", "what is", "why")
_ACTION_MARKERS = ("帮我", "请", "给我", "直接", "把", "将", "make ", "please ")
_MUTATING_BASH_RE = re.compile(
    r"(^|[\s&|])("
    r"copy|xcopy|robocopy|move|ren|rename|del|erase|"
    r"set-content|add-content|out-file|new-item|remove-item|"
    r"move-item|copy-item|touch|cp|mv|rm|tee"
    r")(\s|$)",
    re.IGNORECASE,
)
_REDIRECTION_RE = re.compile(r"(?<![>&])>{1,2}\s*(?!&)\S+")


class Phase(Enum):
    START = "start"
    END = "end"


@dataclass(frozen=True)
class ToolEvent:
    name: str
    args: str = ""
    phase: Phase = Phase.START
    result: str = ""
    is_error: bool = False


@dataclass(frozen=True)
class Event:
    text: str = ""
    tool: ToolEvent | None = None
    done: bool = False
    err: Exception | None = None


def _preview_args(raw: str, max_chars: int = 80) -> str:
    try:
        data: Any = json.loads(raw or "{}")
    except json.JSONDecodeError:
        preview = raw
    else:
        if isinstance(data, dict):
            preview = ""
            for key in ("path", "command", "pattern"):
                value = data.get(key)
                if isinstance(value, str):
                    preview = value
                    break
            if not preview:
                preview = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
        else:
            preview = str(data)
    return f"{preview[: max_chars - 3]}..." if len(preview) > max_chars else preview


def _latest_user_text(conv: Conversation) -> str:
    for message in reversed(conv.messages()):
        if message.role == "user":
            return message.content
    return ""


def _requests_file_mutation(text: str) -> bool:
    normalized = text.lower()
    has_action = any(word in normalized for word in _FILE_MUTATION_WORDS)
    has_file_hint = any(hint in normalized for hint in _FILE_HINTS)
    asks_for_explanation = any(marker in normalized for marker in _EXPLANATION_MARKERS)
    explicitly_requests_action = any(marker in normalized for marker in _ACTION_MARKERS)
    if asks_for_explanation and not explicitly_requests_action:
        return False
    return has_action and has_file_hint


def _call_may_mutate_file(call: ToolCall) -> bool:
    if call.name in {"write_file", "edit_file"}:
        return True
    if call.name != "bash":
        return False

    try:
        data: Any = json.loads(call.input or "{}")
    except json.JSONDecodeError:
        return False
    if not isinstance(data, dict):
        return False
    command = data.get("command")
    if not isinstance(command, str):
        return False
    return bool(_REDIRECTION_RE.search(command) or _MUTATING_BASH_RE.search(command))


class Agent:
    """Execute one model tool batch followed by one final model response."""

    def __init__(self, provider: Provider, registry: Registry) -> None:
        self._provider = provider
        self._registry = registry

    async def run(self, conv: Conversation) -> AsyncIterator[Event]:
        definitions = self._registry.definitions()
        audit_file_mutation = _requests_file_mutation(_latest_user_text(conv))
        preamble: list[str] = []
        calls: list[ToolCall] = []

        try:
            async for event in self._provider.stream(conv.messages(), definitions):
                if event.err is not None:
                    raise event.err
                if event.text:
                    preamble.append(event.text)
                    if not audit_file_mutation:
                        yield Event(text=event.text)
                if event.tool_calls:
                    calls.extend(event.tool_calls)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            yield Event(err=exc)
            return

        preamble_text = "".join(preamble)
        if not calls:
            if audit_file_mutation:
                preamble_text = UNBACKED_FILE_MUTATION_MESSAGE
                yield Event(text=preamble_text)
            conv.add_assistant(preamble_text)
            yield Event(done=True)
            return

        if audit_file_mutation and preamble_text:
            yield Event(text=preamble_text)
        conv.add_assistant_with_tool_calls(preamble_text, calls)
        results: list[ToolResult] = []
        file_mutation_succeeded = False
        for call in calls:
            args_preview = _preview_args(call.input)
            yield Event(tool=ToolEvent(name=call.name, args=args_preview))
            result = await self._registry.execute(
                call.name,
                call.input,
                timeout=DEFAULT_TIMEOUT,
            )
            yield Event(
                tool=ToolEvent(
                    name=call.name,
                    args=args_preview,
                    phase=Phase.END,
                    result=result.content,
                    is_error=result.is_error,
                )
            )
            if _call_may_mutate_file(call) and not result.is_error:
                file_mutation_succeeded = True
            results.append(
                ToolResult(
                    tool_call_id=call.id,
                    content=result.content,
                    is_error=result.is_error,
                )
            )
        conv.add_tool_results(results)

        final: list[str] = []
        repeated_calls: list[ToolCall] = []
        try:
            async for event in self._provider.stream(conv.messages(), definitions):
                if event.err is not None:
                    raise event.err
                if event.text:
                    final.append(event.text)
                    if not (audit_file_mutation and not file_mutation_succeeded):
                        yield Event(text=event.text)
                if event.tool_calls:
                    repeated_calls.extend(event.tool_calls)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            yield Event(err=exc)
            return

        final_text = "".join(final)
        if audit_file_mutation and not file_mutation_succeeded:
            final_text = UNBACKED_FILE_MUTATION_MESSAGE
            yield Event(text=final_text)
        elif repeated_calls and not final_text:
            final_text = SINGLE_ROUND_LIMIT_MESSAGE
            yield Event(text=final_text)
        conv.add_assistant(final_text)
        yield Event(done=True)


__all__ = [
    "SINGLE_ROUND_LIMIT_MESSAGE",
    "UNBACKED_FILE_MUTATION_MESSAGE",
    "Agent",
    "Event",
    "Phase",
    "ToolEvent",
]
