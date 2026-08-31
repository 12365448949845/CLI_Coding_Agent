"""Edit a UTF-8 text file using a unique exact match."""

import asyncio
from pathlib import Path
from typing import Any

from . import Result, _parse_args, _required_string


class EditFileTool:
    def name(self) -> str:
        return "edit_file"

    def description(self) -> str:
        return "Replace exactly one occurrence of old_string in a UTF-8 text file."

    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "File path to edit."},
                "old_string": {
                    "type": "string",
                    "description": "Exact text that must occur exactly once.",
                },
                "new_string": {"type": "string", "description": "Replacement text."},
            },
            "required": ["path", "old_string", "new_string"],
        }

    async def execute(self, args: str) -> Result:
        data, error = _parse_args(args)
        if error is not None or data is None:
            return error or Result("参数无效", is_error=True)
        path_value, error = _required_string(data, "path")
        if error is not None or path_value is None:
            return error or Result("参数 path 无效", is_error=True)
        old_string, error = _required_string(data, "old_string")
        if error is not None or old_string is None:
            return error or Result("参数 old_string 无效", is_error=True)
        new_string, error = _required_string(data, "new_string", allow_empty=True)
        if error is not None or new_string is None:
            return error or Result("参数 new_string 无效", is_error=True)
        return await asyncio.to_thread(self._edit, Path(path_value), old_string, new_string)

    @staticmethod
    def _edit(path: Path, old_string: str, new_string: str) -> Result:
        try:
            content = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            return Result(f"文件不是有效的 UTF-8 文本: {path}", is_error=True)
        except OSError as exc:
            return Result(f"无法读取文件 {path}: {exc}", is_error=True)

        matches = content.count(old_string)
        if matches == 0:
            return Result("未找到匹配的内容（匹配到 0 处）", is_error=True)
        if matches > 1:
            return Result(
                f"匹配到 {matches} 处，old_string 不唯一，请提供更长上下文使其唯一",
                is_error=True,
            )
        try:
            path.write_text(content.replace(old_string, new_string, 1), encoding="utf-8")
        except OSError as exc:
            return Result(f"无法写入文件 {path}: {exc}", is_error=True)
        return Result(f"已修改 {path}（唯一匹配替换成功）")
