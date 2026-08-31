"""Create or overwrite UTF-8 text files."""

import asyncio
from pathlib import Path
from typing import Any

from . import Result, _parse_args, _required_string


class WriteFileTool:
    def name(self) -> str:
        return "write_file"

    def description(self) -> str:
        return "Create or overwrite a UTF-8 text file, creating parent directories as needed."

    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Destination file path."},
                "content": {"type": "string", "description": "Complete file content."},
            },
            "required": ["path", "content"],
        }

    async def execute(self, args: str) -> Result:
        data, error = _parse_args(args)
        if error is not None or data is None:
            return error or Result("参数无效", is_error=True)
        path_value, error = _required_string(data, "path")
        if error is not None or path_value is None:
            return error or Result("参数 path 无效", is_error=True)
        content, error = _required_string(data, "content", allow_empty=True)
        if error is not None or content is None:
            return error or Result("参数 content 无效", is_error=True)
        return await asyncio.to_thread(self._write, Path(path_value), content)

    @staticmethod
    def _write(path: Path, content: str) -> Result:
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8")
        except OSError as exc:
            return Result(f"无法写入文件 {path}: {exc}", is_error=True)
        return Result(f"已写入 {path}（{len(content.encode('utf-8'))} 字节）")
