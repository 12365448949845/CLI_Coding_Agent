"""Built-in tool protocol, registry, and helpers."""

import asyncio
import json
from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable

from ..llm import ToolDefinition

DEFAULT_TIMEOUT = 30.0


@dataclass(frozen=True)
class Result:
    content: str
    is_error: bool = False


@runtime_checkable
class Tool(Protocol):
    def name(self) -> str: ...

    def description(self) -> str: ...

    def parameters(self) -> dict[str, Any]: ...

    async def execute(self, args: str) -> Result: ...


def _parse_args(args: str) -> tuple[dict[str, Any] | None, Result | None]:
    try:
        value = json.loads(args or "{}")
    except json.JSONDecodeError as exc:
        return None, Result(f"参数 JSON 无效: {exc.msg}", is_error=True)
    if not isinstance(value, dict):
        return None, Result("工具参数必须是 JSON 对象", is_error=True)
    return value, None


def _required_string(
    data: dict[str, Any], field: str, *, allow_empty: bool = False
) -> tuple[str | None, Result | None]:
    value = data.get(field)
    if not isinstance(value, str):
        return None, Result(f"参数 {field} 必须是字符串", is_error=True)
    if not allow_empty and not value.strip():
        return None, Result(f"参数 {field} 不能为空", is_error=True)
    return value, None


def _truncate(value: str, max_lines: int, max_chars: int) -> str:
    lines = value.splitlines()
    truncated = len(lines) > max_lines
    result = "\n".join(lines[:max_lines])
    if len(result) > max_chars:
        result = result[:max_chars]
        truncated = True
    if truncated:
        result = f"{result}\n[truncated]" if result else "[truncated]"
    return result


class Registry:
    def __init__(self) -> None:
        self._order: list[str] = []
        self._tools: dict[str, Tool] = {}

    def register(self, tool: Tool) -> None:
        name = tool.name()
        if name in self._tools:
            raise ValueError(f"工具名称重复: {name}")
        self._order.append(name)
        self._tools[name] = tool

    def get(self, name: str) -> Tool | None:
        return self._tools.get(name)

    def definitions(self) -> list[ToolDefinition]:
        return [
            ToolDefinition(
                name=name,
                description=self._tools[name].description(),
                input_schema=self._tools[name].parameters(),
            )
            for name in self._order
        ]

    async def execute(
        self,
        name: str,
        args: str,
        timeout: float = DEFAULT_TIMEOUT,
    ) -> Result:
        tool = self.get(name)
        if tool is None:
            return Result(f"未知工具: {name}", is_error=True)
        try:
            return await asyncio.wait_for(tool.execute(args), timeout=timeout)
        except TimeoutError:
            return Result(f"工具 {name} 执行超时（{timeout:g}s）", is_error=True)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            return Result(f"工具 {name} 执行异常: {exc}", is_error=True)


def new_default_registry() -> Registry:
    from .bash import BashTool
    from .edit_file import EditFileTool
    from .glob_tool import GlobTool
    from .grep_tool import GrepTool
    from .read_file import ReadFileTool
    from .write_file import WriteFileTool

    registry = Registry()
    for tool in (
        ReadFileTool(),
        WriteFileTool(),
        EditFileTool(),
        BashTool(),
        GlobTool(),
        GrepTool(),
    ):
        registry.register(tool)
    return registry


__all__ = ["DEFAULT_TIMEOUT", "Registry", "Result", "Tool", "new_default_registry"]
