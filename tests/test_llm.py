import asyncio
from types import SimpleNamespace

from mewcode.config import ProviderConfig
from mewcode.llm import Message, StreamEvent, ToolCall, ToolDefinition, ToolResult
from mewcode.llm.anthropic_provider import AnthropicProvider
from mewcode.llm.openai_provider import OpenAIProvider
from mewcode.prompt import SYSTEM_PROMPT, build_system_prompt


class AsyncEventStream:
    def __init__(self, events: list[object]) -> None:
        self.events = iter(events)

    async def __aenter__(self) -> "AsyncEventStream":
        return self

    async def __aexit__(self, *args: object) -> None:
        return None

    def __aiter__(self) -> "AsyncEventStream":
        return self

    async def __anext__(self) -> object:
        try:
            return next(self.events)
        except StopIteration:
            raise StopAsyncIteration from None


class FakeAnthropicMessages:
    def __init__(self, events: list[object]) -> None:
        self.events = events
        self.params: dict[str, object] | None = None

    def stream(self, **params: object) -> AsyncEventStream:
        self.params = params
        return AsyncEventStream(self.events)


class AsyncChunkStream:
    def __init__(self, chunks: list[object]) -> None:
        self.chunks = iter(chunks)

    def __aiter__(self) -> "AsyncChunkStream":
        return self

    async def __anext__(self) -> object:
        try:
            return next(self.chunks)
        except StopIteration:
            raise StopAsyncIteration from None


class FakeOpenAICompletions:
    def __init__(self, stream: AsyncChunkStream) -> None:
        self.stream = stream
        self.params: dict[str, object] | None = None

    async def create(self, **params: object) -> AsyncChunkStream:
        self.params = params
        return self.stream


def anthropic_config(thinking: bool = True) -> ProviderConfig:
    return ProviderConfig("Anthropic", "anthropic", "test-key", "claude-test", thinking=thinking)


def collect(coro):
    return asyncio.run(coro)


def test_anthropic_stream_injects_system_and_drops_thinking() -> None:
    provider = AnthropicProvider(anthropic_config())
    events = [
        SimpleNamespace(
            type="content_block_delta",
            delta=SimpleNamespace(type="thinking_delta", thinking="secret"),
        ),
        SimpleNamespace(
            type="content_block_delta", delta=SimpleNamespace(type="text_delta", text="hello")
        ),
    ]
    messages = FakeAnthropicMessages(events)
    provider._client.messages = messages

    async def run() -> list[StreamEvent]:
        return [event async for event in provider.stream([Message("user", "question")])]

    result = collect(run())

    assert [event.text for event in result if event.text] == ["hello"]
    assert result[-1].done is True
    assert messages.params is not None
    assert messages.params["system"] == build_system_prompt([])
    assert SYSTEM_PROMPT in str(messages.params["system"])
    assert messages.params["thinking"] == {"type": "enabled", "budget_tokens": 2048}


def test_openai_stream_injects_system_and_messages() -> None:
    provider = OpenAIProvider(
        ProviderConfig(
            "OpenAI", "openai", "test-key", "gpt-test", base_url="https://example.test/v1"
        )
    )
    completions = FakeOpenAICompletions(
        AsyncChunkStream(
            [
                SimpleNamespace(choices=[SimpleNamespace(delta=SimpleNamespace(content="hello"))]),
                SimpleNamespace(choices=[]),
                SimpleNamespace(choices=[SimpleNamespace(delta=SimpleNamespace(content=None))]),
            ]
        )
    )
    provider._client.chat.completions = completions

    async def run() -> list[StreamEvent]:
        return [event async for event in provider.stream([Message("user", "question")])]

    result = collect(run())

    assert [event.text for event in result if event.text] == ["hello"]
    assert result[-1].done is True
    assert completions.params is not None
    assert completions.params["messages"] == [
        {"role": "system", "content": build_system_prompt([])},
        {"role": "user", "content": "question"},
    ]


def test_provider_converts_runtime_errors_to_error_events() -> None:
    provider = OpenAIProvider(ProviderConfig("OpenAI", "openai", "test-key", "gpt-test"))

    async def fail(**params: object) -> AsyncChunkStream:
        raise RuntimeError("request failed")

    provider._client.chat.completions.create = fail

    async def run() -> list[StreamEvent]:
        return [event async for event in provider.stream([Message("user", "question")])]

    result = collect(run())

    assert len(result) == 1
    assert isinstance(result[0].err, RuntimeError)


def test_anthropic_stream_assembles_tool_input_and_maps_results() -> None:
    provider = AnthropicProvider(anthropic_config())
    events = [
        SimpleNamespace(
            type="content_block_start",
            index=1,
            content_block=SimpleNamespace(type="tool_use", id="call-1", name="read_file"),
        ),
        SimpleNamespace(
            type="content_block_delta",
            index=1,
            delta=SimpleNamespace(type="input_json_delta", partial_json='{"path":'),
        ),
        SimpleNamespace(
            type="content_block_delta",
            index=1,
            delta=SimpleNamespace(type="input_json_delta", partial_json='"README.md"}'),
        ),
    ]
    messages = FakeAnthropicMessages(events)
    provider._client.messages = messages
    definitions = [ToolDefinition("read_file", "Read a file", {"type": "object", "properties": {}})]
    history = [
        Message(
            "assistant",
            tool_calls=[ToolCall("old-call", "read_file", '{"path":"old"}')],
        ),
        Message(
            "tool",
            tool_results=[ToolResult("old-call", "old result")],
        ),
    ]

    async def run() -> list[StreamEvent]:
        return [event async for event in provider.stream(history, definitions)]

    result = collect(run())

    assert result[-2].tool_calls == [ToolCall("call-1", "read_file", '{"path":"README.md"}')]
    assert messages.params is not None
    assert messages.params["system"] == build_system_prompt(definitions)
    assert messages.params["tools"] == [
        {
            "name": "read_file",
            "description": "Read a file",
            "input_schema": {"type": "object", "properties": {}},
        }
    ]
    assert "thinking" not in messages.params
    assert messages.params["messages"][-1] == {
        "role": "user",
        "content": [
            {
                "type": "tool_result",
                "tool_use_id": "old-call",
                "content": "old result",
                "is_error": False,
            }
        ],
    }


def test_openai_stream_assembles_fragmented_tool_call_and_maps_results() -> None:
    provider = OpenAIProvider(ProviderConfig("OpenAI", "openai", "test-key", "gpt-test"))
    chunks = [
        SimpleNamespace(
            choices=[
                SimpleNamespace(
                    delta=SimpleNamespace(
                        content=None,
                        tool_calls=[
                            SimpleNamespace(
                                index=0,
                                id="call-1",
                                function=SimpleNamespace(name="read_", arguments='{"path":'),
                            )
                        ],
                    )
                )
            ]
        ),
        SimpleNamespace(
            choices=[
                SimpleNamespace(
                    delta=SimpleNamespace(
                        content=None,
                        tool_calls=[
                            SimpleNamespace(
                                index=0,
                                id=None,
                                function=SimpleNamespace(name="file", arguments='"README.md"}'),
                            )
                        ],
                    )
                )
            ]
        ),
    ]
    completions = FakeOpenAICompletions(AsyncChunkStream(chunks))
    provider._client.chat.completions = completions
    definition = ToolDefinition("read_file", "Read a file", {"type": "object", "properties": {}})
    history = [
        Message(
            "assistant",
            tool_calls=[ToolCall("old-call", "read_file", '{"path":"old"}')],
        ),
        Message("tool", tool_results=[ToolResult("old-call", "old result")]),
    ]

    async def run() -> list[StreamEvent]:
        return [event async for event in provider.stream(history, [definition])]

    result = collect(run())

    assert result[-2].tool_calls == [ToolCall("call-1", "read_file", '{"path":"README.md"}')]
    assert completions.params is not None
    assert completions.params["messages"][0] == {
        "role": "system",
        "content": build_system_prompt([definition]),
    }
    assert completions.params["tools"] == [
        {
            "type": "function",
            "function": {
                "name": "read_file",
                "description": "Read a file",
                "parameters": {"type": "object", "properties": {}},
            },
        }
    ]
    assert completions.params["messages"][-1] == {
        "role": "tool",
        "tool_call_id": "old-call",
        "content": "old result",
    }
