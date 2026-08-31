"""Protocol-independent single-round tool orchestration."""

import asyncio
import json
from collections.abc import AsyncIterator
from dataclasses import dataclass
from enum import Enum
from typing import Any

from ..conversation import Conversation
from ..llm import Provider, ToolCall, ToolResult
from ..tool import DEFAULT_TIMEOUT, Registry

SINGLE_ROUND_LIMIT_MESSAGE = "本轮已达到一次工具执行上限。请发送后续消息继续。"


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


class Agent:
    """Execute one model tool batch followed by one final model response."""

    def __init__(self, provider: Provider, registry: Registry) -> None:
        self._provider = provider
        self._registry = registry

    async def run(self, conv: Conversation) -> AsyncIterator[Event]:
        definitions = self._registry.definitions()
        preamble: list[str] = []
        calls: list[ToolCall] = []

        try:
            async for event in self._provider.stream(conv.messages(), definitions):
                if event.err is not None:
                    raise event.err
                if event.text:
                    preamble.append(event.text)
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
            conv.add_assistant(preamble_text)
            yield Event(done=True)
            return

        conv.add_assistant_with_tool_calls(preamble_text, calls)
        results: list[ToolResult] = []
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
                    yield Event(text=event.text)
                if event.tool_calls:
                    repeated_calls.extend(event.tool_calls)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            yield Event(err=exc)
            return

        final_text = "".join(final)
        if repeated_calls and not final_text:
            final_text = SINGLE_ROUND_LIMIT_MESSAGE
            yield Event(text=final_text)
        conv.add_assistant(final_text)
        yield Event(done=True)


__all__ = ["SINGLE_ROUND_LIMIT_MESSAGE", "Agent", "Event", "Phase", "ToolEvent"]
