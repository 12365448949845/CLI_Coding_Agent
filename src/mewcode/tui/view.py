"""Rich renderables used by the TUI."""

from rich.console import Group, RenderableType
from rich.markdown import Markdown
from rich.padding import Padding
from rich.table import Table
from rich.text import Text


def user_block(text: str) -> Text:
    return Text(f"● {text}", style="bold")


def render_markdown(reply: str, elapsed: float | None = None) -> Group:
    parts: list[RenderableType] = [Text("● ", style="bold"), Markdown(reply)]
    if elapsed is not None:
        parts.append(Text(f"\nCompleted in {elapsed:.1f}s", style="dim"))
    return Group(*parts)


def error_block(error: Exception) -> Text:
    return Text(f"● {error}", style="bold red")


def streaming_block(
    reply: str,
    elapsed: float,
    tool_name: str = "",
    tool_args: str = "",
) -> Text:
    if tool_name:
        return Text(f"● {tool_name}({tool_args}) Running… ({int(elapsed)}s)", style="cyan")
    content = f"● {reply}" if reply else "●"
    return Text(f"{content}\nImagining… ({int(elapsed)}s)", style="white")


def tool_line(name: str, args: str) -> Text:
    return Text.assemble(("● ", "bold cyan"), (f"{name}({args})", "bold"))


def tool_result_summary(result: str, is_error: bool) -> Padding:
    lines = result.splitlines()
    summary = "\n".join(lines[:8])
    if len(lines) > 8 or len(summary) > 1000:
        summary = f"{summary[:1000]}\n[truncated]"
    style = "red" if is_error else "dim"
    return Padding(Text(f"⎿ {summary}", style=style), (0, 0, 0, 2))


def status_bar(name: str, model: str) -> Table:
    table = Table.grid(expand=True)
    table.add_column(justify="left")
    table.add_column(justify="right")
    table.add_row(name, model)
    return table
