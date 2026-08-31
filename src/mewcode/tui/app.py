"""Main Textual application."""

import asyncio
import os
import time
from dataclasses import dataclass
from enum import Enum

from rich.text import Text
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal
from textual.events import Key
from textual.message import Message as TextualMessage
from textual.timer import Timer
from textual.widgets import OptionList, RichLog, Static, TextArea

from ..config import ProviderConfig
from ..conversation import Conversation
from ..llm import Provider, new_provider
from ..prompt import render_banner
from ..tool import Registry
from .select import provider_options
from .stream import consume_agent, tick
from .view import error_block, render_markdown, status_bar, streaming_block, user_block


class SessionState(Enum):
    SELECTING = "selecting"
    IDLE = "idle"
    STREAMING = "streaming"


@dataclass(frozen=True)
class ToolDisplay:
    name: str
    args: str


class SubmitRequested(TextualMessage):
    def __init__(self, text: str) -> None:
        super().__init__()
        self.text = text


class MessageTextArea(TextArea):
    """Text area where Enter submits and Alt+Enter inserts a newline."""

    BINDINGS = [
        Binding("enter", "submit_message", "Submit", show=False),
        Binding("alt+enter", "insert_newline", "New line", show=False),
    ]

    def action_submit_message(self) -> None:
        self.post_message(SubmitRequested(self.text))

    def action_insert_newline(self) -> None:
        self.insert("\n")

    def on_key(self, event: Key) -> None:
        if event.key in {"enter", "alt+enter"}:
            event.stop()
            if event.key == "alt+enter":
                self.insert("\n")
            else:
                self.post_message(SubmitRequested(self.text))


class MewCodeApp(App[None]):
    CSS = """
    Screen {
        layout: vertical;
    }

    #log {
        width: 1fr;
        height: 1fr;
        border: none;
    }

    #streaming {
        width: 1fr;
        height: auto;
        min-height: 1;
        padding: 0 1;
    }

    #input-shell {
        width: 1fr;
        min-height: 3;
        max-height: 8;
        border: round $accent;
    }

    #input-prefix {
        width: 3;
        padding: 1 0 0 1;
        color: $accent;
    }

    #input {
        width: 1fr;
        height: 1fr;
        border: none;
    }

    #statusbar {
        width: 1fr;
        height: 1;
        padding: 0 1;
        color: $text-muted;
    }

    #provider-selector {
        width: 1fr;
        height: 1fr;
        border: round $accent;
    }
    """

    BINDINGS = [Binding("ctrl+c", "quit", "Quit", show=False)]

    def __init__(
        self,
        providers: list[ProviderConfig],
        version: str,
        registry: Registry,
    ) -> None:
        super().__init__()
        self.state = SessionState.SELECTING if len(providers) > 1 else SessionState.IDLE
        self.providers = providers
        self.version = version
        self.registry = registry
        self.provider: Provider | None = None
        self.conv = Conversation()
        self.cur_reply = ""
        self.cur_tool: ToolDisplay | None = None
        self.turn_start = 0.0
        self._turn_checkpoint = 0
        self._stream_task: asyncio.Task[None] | None = None
        self._timer: Timer | None = None

    def compose(self) -> ComposeResult:
        yield RichLog(id="log", wrap=True, markup=True)
        yield Static("", id="streaming")
        yield Horizontal(
            Static("❯", id="input-prefix"),
            MessageTextArea("", id="input", placeholder="Send a message..."),
            id="input-shell",
        )
        yield Static("", id="statusbar")
        if len(self.providers) > 1:
            yield provider_options(self.providers)

    def on_mount(self) -> None:
        log = self.query_one("#log", RichLog)
        log.write(Text(render_banner(self.version, os.getcwd()), style="cyan"))
        if len(self.providers) == 1:
            self._activate_provider(self.providers[0])
        else:
            self._set_selecting_view()

    def _activate_provider(self, cfg: ProviderConfig) -> None:
        self.provider = new_provider(cfg)
        self.state = SessionState.IDLE
        self.query_one("#statusbar", Static).update(
            status_bar(self.provider.name, self.provider.model)
        )
        selector = (
            self.query_one("#provider-selector", OptionList) if len(self.providers) > 1 else None
        )
        if selector is not None:
            selector.display = False
        self.query_one("#log", RichLog).display = True
        self.query_one("#streaming", Static).display = True
        input_area = self.query_one("#input", MessageTextArea)
        input_area.display = True
        input_area.focus()

    def _set_selecting_view(self) -> None:
        self.state = SessionState.SELECTING
        self.query_one("#log", RichLog).display = False
        self.query_one("#streaming", Static).display = False
        self.query_one("#input", MessageTextArea).display = False
        self.query_one("#statusbar", Static).display = False
        selector = self.query_one("#provider-selector", OptionList)
        selector.display = True
        selector.focus()

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        if event.option.id is None:
            return
        index = int(event.option.id)
        self._activate_provider(self.providers[index])

    def on_submit_requested(self, message: SubmitRequested) -> None:
        if self.state is not SessionState.IDLE:
            return
        self.call_later(self.submit, message.text)

    async def submit(self, text: str) -> None:
        if self.state is not SessionState.IDLE:
            return
        if text.strip() == "/exit":
            await self.action_quit()
            return
        if not text.strip() or self.provider is None:
            return

        self._turn_checkpoint = len(self.conv)
        self.conv.add_user(text)
        self.query_one("#log", RichLog).write(user_block(text))
        self.query_one("#input", MessageTextArea).text = ""
        self.cur_reply = ""
        self.cur_tool = None
        self.turn_start = time.monotonic()
        self.state = SessionState.STREAMING
        self._refresh_streaming_view()
        self._stream_task = asyncio.create_task(self._consume_agent())
        self._timer = self.set_interval(0.1, self._tick)

    async def _consume_agent(self) -> None:
        await consume_agent(self)

    def _tick(self) -> None:
        tick(self)

    def _refresh_streaming_view(self) -> None:
        elapsed = time.monotonic() - self.turn_start
        tool_name = self.cur_tool.name if self.cur_tool is not None else ""
        tool_args = self.cur_tool.args if self.cur_tool is not None else ""
        self.query_one("#streaming", Static).update(
            streaming_block(self.cur_reply, elapsed, tool_name, tool_args)
        )

    def _stop_timer(self) -> float:
        elapsed = time.monotonic() - self.turn_start
        if self._timer is not None:
            self._timer.stop()
            self._timer = None
        return elapsed

    def _finish_with_assistant(self, reply: str) -> None:
        elapsed = self._stop_timer()
        if reply:
            self.query_one("#log", RichLog).write(render_markdown(reply, elapsed))
        self.cur_reply = ""
        self.cur_tool = None
        self._stream_task = None
        self.state = SessionState.IDLE
        self.query_one("#streaming", Static).update("")
        self.query_one("#input", MessageTextArea).focus()

    def _finish_with_error(self, error: Exception) -> None:
        self._stop_timer()
        self.conv.truncate(self._turn_checkpoint)
        self.query_one("#log", RichLog).write(error_block(error))
        self.cur_reply = ""
        self.cur_tool = None
        self._stream_task = None
        self.state = SessionState.IDLE
        self.query_one("#streaming", Static).update("")
        self.query_one("#input", MessageTextArea).focus()

    async def action_quit(self) -> None:
        if self._stream_task is not None:
            task = self._stream_task
            task.cancel()
            self._stream_task = None
            try:
                await task
            except asyncio.CancelledError:
                pass
        if self._timer is not None:
            self._timer.stop()
            self._timer = None
        if self.provider is not None:
            await self.provider.close()
        self.exit()
