"""Command-line entry point."""

import sys

from . import __version__
from .config import ConfigError, load
from .tool import new_default_registry


def main() -> None:
    try:
        config = load(".mewcode/config.yaml")
    except ConfigError as exc:
        print(f"配置错误: {exc}", file=sys.stderr)
        raise SystemExit(1) from None

    try:
        from .tui.app import MewCodeApp

        registry = new_default_registry()
        MewCodeApp(config.providers, __version__, registry).run(inline=True)
    except KeyboardInterrupt:
        return
    except Exception as exc:
        print(f"启动失败: {exc}", file=sys.stderr)
        raise SystemExit(1) from None
