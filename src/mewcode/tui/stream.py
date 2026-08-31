"""Agent event consumption and response timing helpers."""

import asyncio
from typing import TYPE_CHECKING

from textual.widgets import RichLog

from ..agent import Agent, Phase
from .view import render_markdown, tool_line, tool_result_summary

if TYPE_CHECKING:
    from .app import MewCodeApp


async def consume_agent(app: "MewCodeApp") -> None:
    if app.provider is None:
        app._finish_with_error(RuntimeError("未选择 provider"))
        return

    try:
        agent = Agent(app.provider, app.registry)
        async for event in agent.run(app.conv):
            if event.err is not None:
                app._finish_with_error(event.err)
                return
            if event.text:
                app.cur_reply += event.text
                app._refresh_streaming_view()
            if event.tool is not None:
                log = app.query_one("#log", RichLog)
                if event.tool.phase is Phase.START:
                    if app.cur_reply:
                        log.write(render_markdown(app.cur_reply))
                        app.cur_reply = ""
                    from .app import ToolDisplay

                    app.cur_tool = ToolDisplay(event.tool.name, event.tool.args)
                else:
                    log.write(tool_line(event.tool.name, event.tool.args))
                    log.write(tool_result_summary(event.tool.result, event.tool.is_error))
                    app.cur_tool = None
                app._refresh_streaming_view()
            if event.done:
                app._finish_with_assistant(app.cur_reply)
                return
    except asyncio.CancelledError:
        raise
    except Exception as exc:
        app._finish_with_error(exc)


def tick(app: "MewCodeApp") -> None:
    if app.state.value != "streaming":
        return
    app._refresh_streaming_view()
