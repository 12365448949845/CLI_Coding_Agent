"""Read UTF-8 text files with line numbers."""

import asyncio
from pathlib import Path
from typing import Any

from . import Result, _parse_args, _required_string, _truncate


class ReadFileTool:
    def name(self) -> str:
        return "read_file"

    def description(self) -> str:
        return "Read a UTF-8 text file and return its content with line numbers."

    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {"path": {"type": "string", "description": "Path to the file to read."}},
            "required": ["path"],
        }

    async def execute(self, args: str) -> Result:
        data, error = _parse_args(args)
        if error is not None or data is None:
            return error or Result("参数无效", is_error=True)
        path_value, error = _required_string(data, "path")
        if error is not None or path_value is None:
            return error or Result("参数 path 无效", is_error=True)
        return await asyncio.to_thread(self._read, Path(path_value))

    @staticmethod
    def _read(path: Path) -> Result:
        try:
            if not path.exists():
                return Result(f"文件不存在: {path}", is_error=True)
            if not path.is_file():
                return Result(f"路径不是文件: {path}", is_error=True)
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            return Result(f"文件不是有效的 UTF-8 文本: {path}", is_error=True)
        except OSError as exc:
            return Result(f"无法读取文件 {path}: {exc}", is_error=True)

        numbered = "\n".join(
            f"{number:6d}\t{line}" for number, line in enumerate(text.splitlines(), 1)
        )
        return Result(_truncate(numbered, max_lines=2000, max_chars=256 * 1024))
