"""Find files using a glob pattern."""

import asyncio
from pathlib import Path
from typing import Any

from . import Result, _parse_args, _required_string

MAX_RESULTS = 100


class GlobTool:
    def name(self) -> str:
        return "glob"

    def description(self) -> str:
        return "Find files recursively using a glob pattern and return sorted paths."

    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "pattern": {"type": "string", "description": "Glob such as **/*.py."},
                "path": {"type": "string", "description": "Optional search root."},
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
        path_value = data.get("path", ".")
        if not isinstance(path_value, str) or not path_value.strip():
            return Result("参数 path 必须是非空字符串", is_error=True)
        return await asyncio.to_thread(self._find, Path(path_value), pattern)

    @staticmethod
    def _find(root: Path, pattern: str) -> Result:
        if not root.exists():
            return Result(f"搜索路径不存在: {root}", is_error=True)
        if not root.is_dir():
            return Result(f"搜索路径不是目录: {root}", is_error=True)
        try:
            matches = sorted(path.as_posix() for path in root.glob(pattern) if path.is_file())
        except (OSError, ValueError) as exc:
            return Result(f"glob 搜索失败: {exc}", is_error=True)
        if not matches:
            return Result("无匹配")
        truncated = len(matches) > MAX_RESULTS
        content = "\n".join(matches[:MAX_RESULTS])
        if truncated:
            content += "\n[truncated]"
        return Result(content)
