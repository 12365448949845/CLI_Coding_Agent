"""OpenAI-compatible chat completions adapter."""

import asyncio
from collections.abc import AsyncIterator
from typing import Any, cast

import openai

from ..config import ProviderConfig
from ..prompt import build_system_prompt
from . import Message, Provider, StreamEvent, ToolCall, ToolDefinition


def _to_openai_messages(messages: list[Message], system_prompt: str) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = [{"role": "system", "content": system_prompt}]
    for message in messages:
        if message.role == "tool":
            result.extend(
                {
                    "role": "tool",
                    "tool_call_id": item.tool_call_id,
                    "content": item.content,
                }
                for item in message.tool_results
            )
        elif message.role == "assistant" and message.tool_calls:
            result.append(
                {
                    "role": "assistant",
                    "content": message.content or None,
                    "tool_calls": [
                        {
                            "id": call.id,
                            "type": "function",
                            "function": {
                                "name": call.name,
                                "arguments": call.input or "{}",
                            },
                        }
                        for call in message.tool_calls
                    ],
                }
            )
        else:
            result.append({"role": message.role, "content": message.content})
    return result


def _to_openai_tools(tools: list[ToolDefinition]) -> list[dict[str, Any]]:
    return [
        {
            "type": "function",
            "function": {
                "name": tool.name,
                "description": tool.description,
                "parameters": tool.input_schema,
            },
        }
        for tool in tools
    ]


class OpenAIProvider(Provider):
    def __init__(self, cfg: ProviderConfig) -> None:
        client_kwargs: dict[str, object] = {"api_key": cfg.api_key}
        if cfg.base_url:
            client_kwargs["base_url"] = cfg.base_url
        self._client = openai.AsyncOpenAI(**client_kwargs)  # type: ignore[arg-type]
        self._name = cfg.name
        self._model = cfg.model

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
        messages = _to_openai_messages(msgs, build_system_prompt(tool_definitions))

        try:
            params: dict[str, object] = {
                "model": self._model,
                "messages": messages,
                "stream": True,
            }
            if tool_definitions:
                params["tools"] = _to_openai_tools(tool_definitions)
            stream = cast(
                AsyncIterator[object],
                await self._client.chat.completions.create(**params),  # type: ignore[call-overload]
            )
            tool_buffers: dict[int, dict[str, str]] = {}
            async for chunk in stream:
                choices = getattr(chunk, "choices", ())
                if not choices:
                    continue
                delta = getattr(choices[0], "delta", None)
                text = getattr(delta, "content", None)
                if text:
                    yield StreamEvent(text=text)
                for tool_call in getattr(delta, "tool_calls", None) or ():
                    index = int(getattr(tool_call, "index", 0))
                    buffer = tool_buffers.setdefault(index, {"id": "", "name": "", "args": ""})
                    call_id = getattr(tool_call, "id", None)
                    if call_id:
                        buffer["id"] = str(call_id)
                    function = getattr(tool_call, "function", None)
                    name = getattr(function, "name", None)
                    arguments = getattr(function, "arguments", None)
                    if name:
                        buffer["name"] += str(name)
                    if arguments:
                        buffer["args"] += str(arguments)
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
