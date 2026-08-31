"""YAML configuration loading and validation."""

from dataclasses import dataclass
from pathlib import Path
from typing import Literal, cast

import yaml

ProtocolName = Literal["anthropic", "openai"]


class ConfigError(Exception):
    """Raised when the runtime configuration cannot be loaded or validated."""


@dataclass(frozen=True)
class ProviderConfig:
    name: str
    protocol: ProtocolName
    api_key: str
    model: str
    base_url: str | None = None
    thinking: bool = False


@dataclass(frozen=True)
class Config:
    providers: list[ProviderConfig]


def _required_text(item: dict[object, object], index: int, field: str) -> str:
    value = item.get(field)
    if not isinstance(value, str) or not value.strip():
        raise ConfigError(f"providers[{index}].{field} 不能为空")
    return value.strip()


def _from_dict(data: object) -> Config:
    if not isinstance(data, dict):
        raise ConfigError("配置根节点必须是对象")

    raw_providers = data.get("providers")
    if not isinstance(raw_providers, list) or not raw_providers:
        raise ConfigError("providers 必须是非空列表")

    providers: list[ProviderConfig] = []
    for index, raw_provider in enumerate(raw_providers):
        if not isinstance(raw_provider, dict):
            raise ConfigError(f"providers[{index}] 必须是对象")

        name = _required_text(raw_provider, index, "name")
        protocol = _required_text(raw_provider, index, "protocol")
        if protocol not in {"anthropic", "openai"}:
            raise ConfigError(f"providers[{index}].protocol 必须是 anthropic 或 openai")
        api_key = _required_text(raw_provider, index, "api_key")
        model = _required_text(raw_provider, index, "model")

        base_url_value = raw_provider.get("base_url")
        if base_url_value is not None and not isinstance(base_url_value, str):
            raise ConfigError(f"providers[{index}].base_url 必须是字符串")
        base_url = base_url_value.strip() if isinstance(base_url_value, str) else None
        base_url = base_url or None

        thinking_value = raw_provider.get("thinking", False)
        if not isinstance(thinking_value, bool):
            raise ConfigError(f"providers[{index}].thinking 必须是布尔值")

        providers.append(
            ProviderConfig(
                name=name,
                protocol=cast(ProtocolName, protocol),
                api_key=api_key,
                model=model,
                base_url=base_url,
                thinking=thinking_value,
            )
        )

    return Config(providers=providers)


def load(path: str) -> Config:
    """Load and validate a YAML config file without exposing secret values."""
    config_path = Path(path)
    if not config_path.is_file():
        raise ConfigError(f"配置文件不存在: {path}")

    try:
        raw = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        mark = getattr(exc, "problem_mark", None)
        if mark is not None:
            location = f"第 {mark.line + 1} 行，第 {mark.column + 1} 列"
            raise ConfigError(f"YAML 配置解析失败（{location}）") from None
        raise ConfigError("YAML 配置解析失败") from None
    except OSError as exc:
        raise ConfigError(f"无法读取配置文件: {path} ({exc})") from None

    return _from_dict(raw)
