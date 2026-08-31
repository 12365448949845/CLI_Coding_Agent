"""Search UTF-8 text files using a regular expression."""

import asyncio
import re
from pathlib import Path
from re import Pattern
from typing import Any

from . import Result, _parse_args, _required_string

MAX_RESULTS = 100
MAX_LINE_CHARS = 4000


class GrepTool:
    def name(self) -> str:
        return "grep"

    def description(self) -> str:
        return "Search text files with a Python regular expression and return file:line:content."

    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "pattern": {"type": "string", "description": "Python regular expression."},
                "path": {"type": "string", "description": "Optional file or directory."},
                "glob": {"type": "string", "description": "Optional file glob filter."},
            },
            "required": ["pattern"],
        }

    async def execute(self, args: str) -> Result:
        data, error = _parse_args(args)
        if error is not None or data is None:
            return error or Result("参数无效", is_error=True)
        pattern, error = _required_string(data, "pattern")
        if error is not None or pattern is None:
            return error or Result("参数 pattern 无效", is_error=True)
        try:
            regex = re.compile(pattern)
        except re.error as exc:
            return Result(f"正则非法: {exc}", is_error=True)
        path_value = data.get("path", ".")
        glob_value = data.get("glob")
        if not isinstance(path_value, str) or not path_value.strip():
            return Result("参数 path 必须是非空字符串", is_error=True)
        if glob_value is not None and not isinstance(glob_value, str):
            return Result("参数 glob 必须是字符串", is_error=True)
        return await asyncio.to_thread(self._search, Path(path_value), regex, glob_value)

    @staticmethod
    def _search(root: Path, regex: Pattern[str], glob_filter: str | None) -> Result:
        if not root.exists():
            return Result(f"搜索路径不存在: {root}", is_error=True)
        if root.is_file():
            files = [root]
        elif root.is_dir():
            try:
                files = sorted(root.rglob(glob_filter or "*"))
            except (OSError, ValueError) as exc:
                return Result(f"搜索失败: {exc}", is_error=True)
        else:
            return Result(f"搜索路径不可用: {root}", is_error=True)

        matches: list[str] = []
        truncated = False
        for path in files:
            if not path.is_file():
                continue
            try:
                with path.open("r", encoding="utf-8") as handle:
                    for line_number, line in enumerate(handle, 1):
                        if not regex.search(line):
                            continue
                        content = line.rstrip("\r\n")
                        if len(content) > MAX_LINE_CHARS:
                            content = f"{content[:MAX_LINE_CHARS]} [line truncated]"
                        matches.append(f"{path.as_posix()}:{line_number}:{content}")
                        if len(matches) > MAX_RESULTS:
                            truncated = True
                            break
            except (OSError, UnicodeDecodeError):
                continue
            if truncated:
                break

        if not matches:
            return Result("无命中")
        content = "\n".join(matches[:MAX_RESULTS])
        if truncated:
            content += "\n[truncated]"
        return Result(content)
