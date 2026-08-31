"""Run a non-interactive shell command."""

import asyncio
import ctypes
import locale
import os
import signal
import subprocess
from typing import Any

from . import Result, _parse_args, _required_string, _truncate


def _fallback_output_encoding() -> str:
    if os.name == "nt":
        try:
            windll = getattr(ctypes, "windll")
            kernel32 = windll.kernel32
            code_page = int(kernel32.GetConsoleOutputCP())
            if not code_page:
                code_page = int(kernel32.GetOEMCP())
            if code_page:
                return f"cp{code_page}"
        except (AttributeError, OSError, TypeError, ValueError):
            pass

    return locale.getpreferredencoding(False) or "utf-8"


def _decode_output(data: bytes, *, fallback_encoding: str | None = None) -> str:
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        pass

    encoding = fallback_encoding or _fallback_output_encoding()
    try:
        return data.decode(encoding)
    except UnicodeDecodeError:
        return data.decode(encoding, errors="replace")
    except LookupError:
        detected_encoding = _fallback_output_encoding()
        try:
            return data.decode(detected_encoding, errors="replace")
        except LookupError:
            return data.decode("utf-8", errors="replace")


class BashTool:
    def name(self) -> str:
        return "bash"

    def description(self) -> str:
        return "Run a non-interactive shell command in the current working directory."

    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "command": {"type": "string", "description": "Shell command to execute."}
            },
            "required": ["command"],
        }

    async def execute(self, args: str) -> Result:
        data, error = _parse_args(args)
        if error is not None or data is None:
            return error or Result("参数无效", is_error=True)
        command, error = _required_string(data, "command")
        if error is not None or command is None:
            return error or Result("参数 command 无效", is_error=True)

        if os.name == "nt":
            process = await asyncio.create_subprocess_shell(
                command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                creationflags=subprocess.CREATE_NEW_PROCESS_GROUP,
            )
        else:
            process = await asyncio.create_subprocess_shell(
                command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                start_new_session=True,
            )
        try:
            stdout_bytes, stderr_bytes = await process.communicate()
        except asyncio.CancelledError:
            await self._terminate_process_tree(process)
            raise

        stdout = _decode_output(stdout_bytes)
        stderr = _decode_output(stderr_bytes)
        output = f"exit_code: {process.returncode}\nstdout:\n{stdout}\nstderr:\n{stderr}"
        return Result(
            _truncate(output, max_lines=10000, max_chars=30000),
            is_error=process.returncode != 0,
        )

    @staticmethod
    async def _terminate_process_tree(process: asyncio.subprocess.Process) -> None:
        if process.returncode is not None:
            return
        if os.name == "nt":
            ctrl_break = getattr(signal, "CTRL_BREAK_EVENT", None)
            if ctrl_break is not None:
                try:
                    process.send_signal(ctrl_break)
                    await asyncio.wait_for(process.wait(), timeout=0.5)
                    return
                except (ProcessLookupError, TimeoutError):
                    pass

            killer = await asyncio.create_subprocess_exec(
                "taskkill",
                "/PID",
                str(process.pid),
                "/T",
                "/F",
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
            )
            await asyncio.wait_for(killer.wait(), timeout=1.0)
        else:
            try:
                kill_process_group = getattr(os, "killpg", None)
                sigkill = getattr(signal, "SIGKILL", None)
                if kill_process_group is not None and sigkill is not None:
                    kill_process_group(process.pid, sigkill)
                else:
                    process.kill()
            except ProcessLookupError:
                pass
        if process.returncode is None:
            process.kill()
        await asyncio.wait_for(process.wait(), timeout=1.0)
