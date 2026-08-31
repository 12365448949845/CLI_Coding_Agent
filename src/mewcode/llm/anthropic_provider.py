"""Anthropic protocol adapter."""

import asyncio
import json
from collections.abc import AsyncIterator
from typing import Any

import anthropic

from ..config import ProviderConfig
from ..prompt import build_system_prompt
from . import Message, Provider, StreamEvent, ToolCall, ToolDefinition


def _safe_tool_input(raw: str) -> object:
    try:
        value = json.loads(raw or "{}")
    except json.JSONDecodeError:
        return {"raw": raw}
    return value


def _to_anthropic_messages(messages: list[Message]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for message in messages:
        if message.role == "tool":
            result.append(
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "tool_result",
                            "tool_use_id": item.tool_call_id,
                            "content": item.content,
                            "is_error": item.is_error,
                        }
                        for item in message.tool_results
                    ],
                }
            )
        elif message.role == "assistant" and message.tool_calls:
            content: list[dict[str, Any]] = []
            if message.content:
                content.append({"type": "text", "text": message.content})
            content.extend(
                {
                    "type": "tool_use",
                    "id": call.id,
                    "name": call.name,
                    "input": _safe_tool_input(call.input),
                }
                for call in message.tool_calls
            )
            result.append({"role": "assistant", "content": content})
        else:
            result.append({"role": message.role, "content": message.content})
    return result


def _to_anthropic_tools(tools: list[ToolDefinition]) -> list[dict[str, Any]]:
    return [
        {
            "name": tool.name,
            "description": tool.description,
            "input_schema": tool.input_schema,
        }
        for tool in tools
    ]


class AnthropicProvider(Provider):
    def __init__(self, cfg: ProviderConfig) -> None:
        client_kwargs: dict[str, object] = {"api_key": cfg.api_key}
        if cfg.base_url:
            client_kwargs["base_url"] = cfg.base_url
        self._client = anthropic.AsyncAnthropic(**client_kwargs)  # type: ignore[arg-type]
        self._name = cfg.name
        self._model = cfg.model
        self._thinking = cfg.thinking

    @property
    def name(self) -> str:
        return self._name

    @property
    def model(self) -> str:
        return self._model

    async def close(self) -> None:
        await self._client.close()

    async def stream(
        self,
        msgs: list[Message],
        tools: list[ToolDefinition] | None = None,
    ) -> AsyncIterator[StreamEvent]:
        tool_definitions = list(tools or [])
        messages = _to_anthropic_messages(msgs)
        params: dict[str, object] = {
            "model": self._model,
            "max_tokens": 4096,
            "system": build_system_prompt(tool_definitions),
            "messages": messages,
        }
        if tool_definitions:
            params["tools"] = _to_anthropic_tools(tool_definitions)
        has_tool_history = any(message.tool_calls or message.tool_results for message in msgs)
        if self._thinking and not has_tool_history:
            params["thinking"] = {"type": "enabled", "budget_tokens": 2048}

        try:
            tool_buffers: dict[int, dict[str, str]] = {}
            async with self._client.messages.stream(**params) as stream:  # type: ignore[arg-type]
                async for event in stream:
                    event_type = getattr(event, "type", None)
                    if event_type == "content_block_start":
                        block = getattr(event, "content_block", None)
                        if getattr(block, "type", None) == "tool_use":
                            index = int(getattr(event, "index", 0))
                            tool_buffers[index] = {
                                "id": str(getattr(block, "id", "")),
                                "name": str(getattr(block, "name", "")),
                                "args": "",
                            }
                        continue
                    if event_type != "content_block_delta":
                        continue
                    delta = getattr(event, "delta", None)
                    delta_type = getattr(delta, "type", None)
                    if delta_type == "text_delta":
                        text = getattr(delta, "text", "")
                        if text:
                            yield StreamEvent(text=text)
                    elif delta_type == "input_json_delta":
                        index = int(getattr(event, "index", 0))
                        buffer = tool_buffers.setdefault(index, {"id": "", "name": "", "args": ""})
                        buffer["args"] += str(getattr(delta, "partial_json", ""))
                    # Thinking deltas are deliberately consumed and discarded.
            calls = [
                ToolCall(
                    id=buffer["id"],
                    name=buffer["name"],
                    input=buffer["args"] or "{}",
                )
                for _, buffer in sorted(tool_buffers.items())
            ]
            if calls:
                yield StreamEvent(tool_calls=calls)
            yield StreamEvent(done=True)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            yield StreamEvent(err=exc)
