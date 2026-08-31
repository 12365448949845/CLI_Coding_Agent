import asyncio
import json
import sys

import mewcode.tool.bash as bash_module
import mewcode.tui.app as app_module
from mewcode.agent import SINGLE_ROUND_LIMIT_MESSAGE
from mewcode.config import ProviderConfig
from mewcode.llm import Message, StreamEvent, ToolCall, ToolDefinition
from mewcode.tool import Registry, Result
from mewcode.tool.bash import BashTool
from mewcode.tui.app import MewCodeApp, SessionState

TEST_VERSION = "0.1.0"


class FakeProvider:
    def __init__(self, cfg: ProviderConfig) -> None:
        self._name = cfg.name
        self._model = cfg.model
        self.calls: list[list[Message]] = []
        self.tool_definitions: list[list[ToolDefinition]] = []
        self.closed = False

    @property
    def name(self) -> str:
        return self._name

    @property
    def model(self) -> str:
        return self._model

    async def close(self) -> None:
        self.closed = True

    async def stream(
        self,
        messages: list[Message],
        tools: list[ToolDefinition] | None = None,
    ):
        self.calls.append(messages)
        self.tool_definitions.append(list(tools or []))
        yield StreamEvent(text="hello ")
        yield StreamEvent(text="**world**")
        yield StreamEvent(done=True)


class RecoveringProvider(FakeProvider):
    def __init__(self, cfg: ProviderConfig) -> None:
        super().__init__(cfg)
        self.attempt = 0

    async def stream(
        self,
        messages: list[Message],
        tools: list[ToolDefinition] | None = None,
    ):
        self.calls.append(messages)
        self.tool_definitions.append(list(tools or []))
        self.attempt += 1
        if self.attempt == 1:
            yield StreamEvent(err=RuntimeError("temporary failure"))
            return
        yield StreamEvent(text="recovered")
        yield StreamEvent(done=True)


class SlowProvider(FakeProvider):
    def __init__(
        self,
        cfg: ProviderConfig,
        started: asyncio.Event,
        release: asyncio.Event,
    ) -> None:
        super().__init__(cfg)
        self.started = started
        self.release = release

    async def stream(
        self,
        messages: list[Message],
        tools: list[ToolDefinition] | None = None,
    ):
        self.calls.append(messages)
        self.tool_definitions.append(list(tools or []))
        self.started.set()
        await self.release.wait()
        yield StreamEvent(text="delayed")
        yield StreamEvent(done=True)


class ToolCallingProvider(FakeProvider):
    async def stream(
        self,
        messages: list[Message],
        tools: list[ToolDefinition] | None = None,
    ):
        self.calls.append(messages)
        self.tool_definitions.append(list(tools or []))
        if len(self.calls) == 1:
            yield StreamEvent(text="I will read it.")
            yield StreamEvent(tool_calls=[ToolCall("call-1", "read_file", '{"path":"sample.txt"}')])
        else:
            yield StreamEvent(text="The file says hello.")
        yield StreamEvent(done=True)


class RepeatedToolProvider(FakeProvider):
    async def stream(
        self,
        messages: list[Message],
        tools: list[ToolDefinition] | None = None,
    ):
        self.calls.append(messages)
        self.tool_definitions.append(list(tools or []))
        call_number = len(self.calls)
        yield StreamEvent(
            tool_calls=[
                ToolCall(
                    f"call-{call_number}",
                    "read_file",
                    f'{{"path":"file-{call_number}.txt"}}',
                )
            ]
        )
        yield StreamEvent(done=True)


class LocalEncodingToolProvider(FakeProvider):
    async def stream(
        self,
        messages: list[Message],
        tools: list[ToolDefinition] | None = None,
    ):
        self.calls.append(messages)
        self.tool_definitions.append(list(tools or []))
        if len(self.calls) == 1:
            script = (
                "import sys;"
                "sys.stdout.buffer.write('中文标准输出'.encode('cp936'));"
                "sys.stderr.buffer.write('中文错误输出'.encode('cp936'))"
            )
            command = f'"{sys.executable}" -c "{script}"'
            yield StreamEvent(
                tool_calls=[ToolCall("call-bash", "bash", json.dumps({"command": command}))]
            )
        else:
            yield StreamEvent(text="命令输出已读取。")
        yield StreamEvent(done=True)


class WaitingTool:
    def __init__(self, started: asyncio.Event, release: asyncio.Event) -> None:
        self.started = started
        self.release = release

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
        self.started.set()
        await self.release.wait()
        return Result("hello from sample.txt")


class CountingTool:
    def __init__(self) -> None:
        self.calls = 0

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
        self.calls += 1
        return Result(f"result {self.calls}")


class ErrorThenRecoverProvider(FakeProvider):
    async def stream(
        self,
        messages: list[Message],
        tools: list[ToolDefinition] | None = None,
    ):
        self.calls.append(messages)
        self.tool_definitions.append(list(tools or []))
        if len(self.calls) == 1:
            yield StreamEvent(
                tool_calls=[
                    ToolCall(
                        "call-error",
                        "edit_file",
                        '{"path":"sample.txt","old_string":"missing","new_string":"value"}',
                    )
                ]
            )
        elif len(self.calls) == 2:
            yield StreamEvent(text="The edit could not be applied.")
        else:
            yield StreamEvent(text="Recovered on the next turn.")
        yield StreamEvent(done=True)


class ErrorTool:
    def name(self) -> str:
        return "edit_file"

    def description(self) -> str:
        return "Edit a file."

    def parameters(self) -> dict[str, object]:
        return {"type": "object", "properties": {}}

    async def execute(self, args: str) -> Result:
        return Result("未找到匹配的内容（0 处）", is_error=True)


def test_single_provider_mount_submit_and_complete(monkeypatch) -> None:
    created: list[FakeProvider] = []

    def factory(cfg: ProviderConfig) -> FakeProvider:
        provider = FakeProvider(cfg)
        created.append(provider)
        return provider

    monkeypatch.setattr(app_module, "new_provider", factory)

    async def run() -> None:
        config = ProviderConfig("Test", "openai", "key", "model")
        app = MewCodeApp([config], TEST_VERSION, Registry())
        async with app.run_test(size=(100, 30)) as pilot:
            assert app.state is SessionState.IDLE
            assert str(app.query_one("#input-prefix").render()) == "❯"
            assert app.query_one("#input").placeholder == "Send a message..."
            assert app.query_one("#statusbar").display is True
            banner = "\n".join(str(line) for line in app.query_one("#log").lines)
            assert "MewCode v0.1.0" in banner
            assert "Ready. Type a message or /exit to quit." in banner

            input_area = app.query_one("#input")
            input_area.text = "question"
            await pilot.press("enter")
            await pilot.pause()
            await pilot.pause()

            assert app.state is SessionState.IDLE
            assert input_area.text == ""
            assert [(message.role, message.content) for message in app.conv.messages()] == [
                ("user", "question"),
                ("assistant", "hello **world**"),
            ]
            assert created[0].calls[0] == [Message("user", "question")]

            input_area.text = "follow up"
            await pilot.press("enter")
            await pilot.pause()

            assert created[0].calls[1] == [
                Message("user", "question"),
                Message("assistant", "hello **world**"),
                Message("user", "follow up"),
            ]

            input_area.text = "/exit"
            await pilot.press("enter")
            await pilot.pause()
            assert created[0].closed is True

    asyncio.run(run())


def test_waiting_indicator_is_visible_before_first_stream_chunk(monkeypatch) -> None:
    async def run() -> None:
        started = asyncio.Event()
        release = asyncio.Event()
        created: list[SlowProvider] = []

        def factory(cfg: ProviderConfig) -> SlowProvider:
            provider = SlowProvider(cfg, started, release)
            created.append(provider)
            return provider

        monkeypatch.setattr(app_module, "new_provider", factory)
        app = MewCodeApp(
            [ProviderConfig("Test", "openai", "key", "model")],
            TEST_VERSION,
            Registry(),
        )
        async with app.run_test(size=(100, 30)) as pilot:
            input_area = app.query_one("#input")
            input_area.text = "slow request"
            await pilot.press("enter")
            await asyncio.wait_for(started.wait(), timeout=1)
            await pilot.pause(0.12)

            assert app.state is SessionState.STREAMING
            assert "Imagining" in str(app.query_one("#streaming").render())

            created[0].release.set()
            await pilot.pause()
            assert app.state is SessionState.IDLE
            assert [(message.role, message.content) for message in app.conv.messages()] == [
                ("user", "slow request"),
                ("assistant", "delayed"),
            ]

    asyncio.run(run())


def test_multiple_providers_can_be_selected_and_alt_enter_inserts_newline(monkeypatch) -> None:
    monkeypatch.setattr(app_module, "new_provider", lambda cfg: FakeProvider(cfg))

    async def run() -> None:
        configs = [
            ProviderConfig("First", "openai", "key", "model-1"),
            ProviderConfig("Second", "anthropic", "key", "model-2"),
        ]
        app = MewCodeApp(configs, TEST_VERSION, Registry())
        async with app.run_test(size=(100, 30)) as pilot:
            assert app.state is SessionState.SELECTING
            selector = app.query_one("#provider-selector")
            assert selector.option_count == 2
            await pilot.press("down", "enter")
            await pilot.pause()

            assert app.state is SessionState.IDLE
            assert app.provider is not None
            assert app.provider.name == "Second"
            assert app.provider.model == "model-2"
            assert app.query_one("#provider-selector").display is False

            input_area = app.query_one("#input")
            input_area.focus()
            await pilot.press("alt+enter")
            assert input_area.text == "\n"

    asyncio.run(run())


def test_failed_turn_is_visible_and_next_turn_can_continue(monkeypatch) -> None:
    created: list[RecoveringProvider] = []

    def factory(cfg: ProviderConfig) -> RecoveringProvider:
        provider = RecoveringProvider(cfg)
        created.append(provider)
        return provider

    monkeypatch.setattr(app_module, "new_provider", factory)

    async def run() -> None:
        app = MewCodeApp(
            [ProviderConfig("Test", "openai", "key", "model")],
            TEST_VERSION,
            Registry(),
        )
        async with app.run_test(size=(100, 30)) as pilot:
            input_area = app.query_one("#input")
            input_area.text = "first attempt"
            await pilot.press("enter")
            await pilot.pause()

            assert app.state is SessionState.IDLE
            assert "temporary failure" in str(app.query_one("#log").lines[-1])
            assert app.conv.messages() == []

            input_area.text = "retry"
            await pilot.press("enter")
            await pilot.pause()

            assert app.state is SessionState.IDLE
            assert [(message.role, message.content) for message in app.conv.messages()] == [
                ("user", "retry"),
                ("assistant", "recovered"),
            ]
            assert created[0].calls == [
                [Message("user", "first attempt")],
                [Message("user", "retry")],
            ]

    asyncio.run(run())


def test_tool_call_shows_running_state_and_scrollback_result(monkeypatch) -> None:
    created: list[ToolCallingProvider] = []

    def factory(cfg: ProviderConfig) -> ToolCallingProvider:
        provider = ToolCallingProvider(cfg)
        created.append(provider)
        return provider

    monkeypatch.setattr(app_module, "new_provider", factory)

    async def run() -> None:
        started = asyncio.Event()
        release = asyncio.Event()
        registry = Registry()
        registry.register(WaitingTool(started, release))
        app = MewCodeApp(
            [ProviderConfig("Test", "openai", "key", "model")],
            TEST_VERSION,
            registry,
        )
        async with app.run_test(size=(100, 30)) as pilot:
            input_area = app.query_one("#input")
            input_area.text = "read sample.txt"
            await pilot.press("enter")
            await asyncio.wait_for(started.wait(), timeout=1)
            await pilot.pause()

            running = str(app.query_one("#streaming").render())
            assert "read_file(sample.txt)" in running
            assert "Running" in running

            release.set()
            await pilot.pause()
            await pilot.pause()

            assert app.state is SessionState.IDLE
            history = "\n".join(str(line) for line in app.query_one("#log").lines)
            assert history.index("I will read it.") < history.index("read_file(sample.txt)")
            assert history.index("read_file(sample.txt)") < history.index("hello from sample.txt")
            assert history.index("hello from sample.txt") < history.index("The file says hello.")
            assert "read_file(sample.txt)" in history
            assert "hello from sample.txt" in history
            assert "The file says hello." in history
            assert [message.role for message in app.conv.messages()] == [
                "user",
                "assistant",
                "tool",
                "assistant",
            ]
            assert [definition.name for definition in created[0].tool_definitions[0]] == [
                "read_file"
            ]

    asyncio.run(run())


def test_single_round_limit_is_visible_and_next_message_can_submit(monkeypatch) -> None:
    created: list[RepeatedToolProvider] = []

    def factory(cfg: ProviderConfig) -> RepeatedToolProvider:
        provider = RepeatedToolProvider(cfg)
        created.append(provider)
        return provider

    monkeypatch.setattr(app_module, "new_provider", factory)

    async def run() -> None:
        tool = CountingTool()
        registry = Registry()
        registry.register(tool)
        app = MewCodeApp(
            [ProviderConfig("Test", "openai", "key", "model")],
            TEST_VERSION,
            registry,
        )
        async with app.run_test(size=(100, 30)) as pilot:
            input_area = app.query_one("#input")
            input_area.text = "needs another tool round"
            await pilot.press("enter")
            await pilot.pause()
            await pilot.pause()

            history = "\n".join(str(line) for line in app.query_one("#log").lines)
            assert SINGLE_ROUND_LIMIT_MESSAGE in history
            assert app.state is SessionState.IDLE
            assert tool.calls == 1
            assert len(created[0].calls) == 2
            assert app.conv.messages()[-1] == Message("assistant", SINGLE_ROUND_LIMIT_MESSAGE)

            input_area.text = "continue"
            await pilot.press("enter")
            await pilot.pause()
            await pilot.pause()

            assert len(created[0].calls) == 4
            assert tool.calls == 2
            assert app.state is SessionState.IDLE

    asyncio.run(run())


def test_windows_local_encoding_tool_result_is_readable_in_scrollback(monkeypatch) -> None:
    monkeypatch.setattr(bash_module, "_fallback_output_encoding", lambda: "cp936")
    monkeypatch.setattr(app_module, "new_provider", LocalEncodingToolProvider)

    async def run() -> None:
        registry = Registry()
        registry.register(BashTool())
        app = MewCodeApp(
            [ProviderConfig("Test", "openai", "key", "model")],
            TEST_VERSION,
            registry,
        )
        async with app.run_test(size=(100, 30)) as pilot:
            input_area = app.query_one("#input")
            input_area.text = "run a local encoding command"
            await pilot.press("enter")
            for _ in range(30):
                await pilot.pause(0.1)
                if app.state is SessionState.IDLE:
                    break

            history = "\n".join(str(line) for line in app.query_one("#log").lines)
            assert "中文标准输出" in history
            assert "中文错误输出" in history
            assert "�" not in history
            assert app.state is SessionState.IDLE

    asyncio.run(run())


def test_tool_error_is_visible_and_next_turn_continues(monkeypatch) -> None:
    created: list[ErrorThenRecoverProvider] = []

    def factory(cfg: ProviderConfig) -> ErrorThenRecoverProvider:
        provider = ErrorThenRecoverProvider(cfg)
        created.append(provider)
        return provider

    monkeypatch.setattr(app_module, "new_provider", factory)

    async def run() -> None:
        registry = Registry()
        registry.register(ErrorTool())
        app = MewCodeApp(
            [ProviderConfig("Test", "openai", "key", "model")],
            TEST_VERSION,
            registry,
        )
        async with app.run_test(size=(100, 30)) as pilot:
            input_area = app.query_one("#input")
            input_area.text = "edit a missing string"
            await pilot.press("enter")
            await pilot.pause()
            await pilot.pause()

            history = "\n".join(str(line) for line in app.query_one("#log").lines)
            assert "未找到匹配的内容" in history
            assert app.state is SessionState.IDLE

            input_area.text = "continue"
            await pilot.press("enter")
            await pilot.pause()

            assert app.state is SessionState.IDLE
            assert app.conv.messages()[-1] == Message("assistant", "Recovered on the next turn.")
            assert len(created[0].calls) == 3

    asyncio.run(run())
