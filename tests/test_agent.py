import asyncio
import json
import os
from collections.abc import AsyncIterator
from pathlib import Path

from mewcode.agent import (
    SINGLE_ROUND_LIMIT_MESSAGE,
    UNBACKED_FILE_MUTATION_MESSAGE,
    Agent,
    Phase,
)
from mewcode.conversation import Conversation
from mewcode.llm import Message, StreamEvent, ToolCall, ToolDefinition
from mewcode.tool import Registry, Result, new_default_registry


class FakeProvider:
    name = "Fake"
    model = "fake-model"

    def __init__(self, scripts: list[list[StreamEvent]]) -> None:
        self.scripts = scripts
        self.calls: list[tuple[list[Message], list[ToolDefinition]]] = []

    async def close(self) -> None:
        return None

    async def stream(
        self,
        messages: list[Message],
        tools: list[ToolDefinition] | None = None,
    ) -> AsyncIterator[StreamEvent]:
        self.calls.append((messages, list(tools or [])))
        for event in self.scripts[len(self.calls) - 1]:
            yield event


class RecordingTool:
    def __init__(self) -> None:
        self.inputs: list[str] = []

    def name(self) -> str:
        return "read_file"

    def description(self) -> str:
        return "Read a file."

    def parameters(self) -> dict[str, object]:
        return {
            "type": "object",
            "properties": {"path": {"type": "string"}},
            "required": ["path"],
        }

    async def execute(self, args: str) -> Result:
        self.inputs.append(args)
        return Result(f"result {len(self.inputs)}")


class NamedRecordingTool:
    def __init__(self, name: str, result: Result | None = None) -> None:
        self._name = name
        self.result = result or Result("ok")
        self.inputs: list[str] = []

    def name(self) -> str:
        return self._name

    def description(self) -> str:
        return f"Run {self._name}."

    def parameters(self) -> dict[str, object]:
        return {"type": "object", "properties": {}}

    async def execute(self, args: str) -> Result:
        self.inputs.append(args)
        return self.result


def run_agent(agent: Agent, conversation: Conversation):
    async def collect():
        return [event async for event in agent.run(conversation)]

    return asyncio.run(collect())


def test_agent_executes_first_tool_batch_and_streams_final_answer() -> None:
    provider = FakeProvider(
        [
            [
                StreamEvent(text="I will inspect it."),
                StreamEvent(
                    tool_calls=[
                        ToolCall("call-1", "read_file", '{"path":"first.txt"}'),
                        ToolCall("call-2", "read_file", '{"path":"second.txt"}'),
                    ]
                ),
                StreamEvent(done=True),
            ],
            [StreamEvent(text="Files read."), StreamEvent(done=True)],
        ]
    )
    tool = RecordingTool()
    registry = Registry()
    registry.register(tool)
    conversation = Conversation()
    conversation.add_user("Read both files")

    events = run_agent(Agent(provider, registry), conversation)

    assert tool.inputs == ['{"path":"first.txt"}', '{"path":"second.txt"}']
    assert [event.tool.phase for event in events if event.tool is not None] == [
        Phase.START,
        Phase.END,
        Phase.START,
        Phase.END,
    ]
    assert "".join(event.text for event in events) == "I will inspect it.Files read."
    assert events[-1].done is True
    assert [message.role for message in conversation.messages()] == [
        "user",
        "assistant",
        "tool",
        "assistant",
    ]
    assert [result.content for result in conversation.messages()[2].tool_results] == [
        "result 1",
        "result 2",
    ]
    assert len(provider.calls) == 2
    assert [definition.name for definition in provider.calls[0][1]] == ["read_file"]
    assert provider.calls[1][0] == conversation.messages()[:-1]


def test_agent_does_not_execute_a_second_tool_batch() -> None:
    provider = FakeProvider(
        [
            [
                StreamEvent(tool_calls=[ToolCall("call-1", "read_file", '{"path":"first.txt"}')]),
                StreamEvent(done=True),
            ],
            [
                StreamEvent(tool_calls=[ToolCall("call-2", "read_file", '{"path":"second.txt"}')]),
                StreamEvent(done=True),
            ],
        ]
    )
    tool = RecordingTool()
    registry = Registry()
    registry.register(tool)
    conversation = Conversation()
    conversation.add_user("This normally needs two tool rounds")

    events = run_agent(Agent(provider, registry), conversation)

    assert tool.inputs == ['{"path":"first.txt"}']
    assert len(provider.calls) == 2
    assert SINGLE_ROUND_LIMIT_MESSAGE in "".join(event.text for event in events)
    assert events[-1].done is True
    assert conversation.messages()[-1] == Message("assistant", SINGLE_ROUND_LIMIT_MESSAGE)


def test_agent_preserves_plain_text_turns() -> None:
    provider = FakeProvider(
        [[StreamEvent(text="plain "), StreamEvent(text="answer"), StreamEvent(done=True)]]
    )
    conversation = Conversation()
    conversation.add_user("Hello")

    events = run_agent(Agent(provider, Registry()), conversation)

    assert "".join(event.text for event in events) == "plain answer"
    assert conversation.messages()[-1] == Message("assistant", "plain answer")
    assert events[-1].done is True


def test_agent_blocks_plain_text_file_mutation_claim_without_tool() -> None:
    provider = FakeProvider([[StreamEvent(text="已创建 ccp.md。"), StreamEvent(done=True)]])
    conversation = Conversation()
    conversation.add_user("创建一个名为 ccp.md 的文件")

    events = run_agent(Agent(provider, Registry()), conversation)

    text = "".join(event.text for event in events)
    assert text == UNBACKED_FILE_MUTATION_MESSAGE
    assert "已创建 ccp.md" not in text
    assert conversation.messages()[-1] == Message("assistant", UNBACKED_FILE_MUTATION_MESSAGE)


def test_agent_blocks_file_mutation_claim_after_inspection_only_tool() -> None:
    command = "git branch --show-current"
    provider = FakeProvider(
        [
            [
                StreamEvent(
                    tool_calls=[ToolCall("call-branch", "bash", json.dumps({"command": command}))]
                ),
                StreamEvent(done=True),
            ],
            [StreamEvent(text="已经创建 ccp.md。"), StreamEvent(done=True)],
        ]
    )
    tool = NamedRecordingTool(
        "bash",
        Result("exit_code: 0\nstdout:\nmain\nstderr:\n"),
    )
    registry = Registry()
    registry.register(tool)
    conversation = Conversation()
    conversation.add_user("请创建一个名为 ccp.md 的文件放在主分支下")

    events = run_agent(Agent(provider, registry), conversation)

    assert tool.inputs == [json.dumps({"command": command})]
    text = "".join(event.text for event in events)
    assert text == UNBACKED_FILE_MUTATION_MESSAGE
    assert "已经创建 ccp.md" not in text
    assert conversation.messages()[-1] == Message("assistant", UNBACKED_FILE_MUTATION_MESSAGE)


def test_agent_runs_write_edit_and_bash_in_order(tmp_path: Path) -> None:
    path = tmp_path / "batch.txt"
    command = f'type "{path}"' if os.name == "nt" else f'cat "{path}"'
    provider = FakeProvider(
        [
            [
                StreamEvent(
                    tool_calls=[
                        ToolCall(
                            "call-write",
                            "write_file",
                            json.dumps({"path": str(path), "content": "before"}),
                        ),
                        ToolCall(
                            "call-edit",
                            "edit_file",
                            json.dumps(
                                {
                                    "path": str(path),
                                    "old_string": "before",
                                    "new_string": "after",
                                }
                            ),
                        ),
                        ToolCall(
                            "call-bash",
                            "bash",
                            json.dumps({"command": command}),
                        ),
                    ]
                ),
                StreamEvent(done=True),
            ],
            [StreamEvent(text="Batch completed."), StreamEvent(done=True)],
        ]
    )
    conversation = Conversation()
    conversation.add_user("Write, edit, and inspect the file")

    events = run_agent(Agent(provider, new_default_registry()), conversation)

    assert path.read_text(encoding="utf-8") == "after"
    starts = [
        event.tool.name
        for event in events
        if event.tool is not None and event.tool.phase is Phase.START
    ]
    assert starts == ["write_file", "edit_file", "bash"]
    assert "after" in conversation.messages()[2].tool_results[-1].content
    assert conversation.messages()[-1] == Message("assistant", "Batch completed.")


def test_agent_allows_file_mutation_claim_after_successful_write(tmp_path: Path) -> None:
    path = tmp_path / "ccp.md"
    provider = FakeProvider(
        [
            [
                StreamEvent(
                    tool_calls=[
                        ToolCall(
                            "call-write",
                            "write_file",
                            json.dumps({"path": str(path), "content": ""}),
                        )
                    ]
                ),
                StreamEvent(done=True),
            ],
            [StreamEvent(text="已创建 ccp.md。"), StreamEvent(done=True)],
        ]
    )
    conversation = Conversation()
    conversation.add_user("创建一个名为 ccp.md 的文件")

    events = run_agent(Agent(provider, new_default_registry()), conversation)

    assert path.read_text(encoding="utf-8") == ""
    assert "".join(event.text for event in events) == "已创建 ccp.md。"
    assert conversation.messages()[-1] == Message("assistant", "已创建 ccp.md。")
