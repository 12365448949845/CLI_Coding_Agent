from pathlib import Path

import pytest

from mewcode.config import ConfigError, load


def write_config(tmp_path: Path, content: str) -> Path:
    path = tmp_path / "config.yaml"
    path.write_text(content, encoding="utf-8")
    return path


def test_load_valid_config(tmp_path: Path) -> None:
    path = write_config(
        tmp_path,
        """
providers:
  - name: Anthropic
    protocol: anthropic
    api_key: test-key
    model: claude-test
    base_url: https://example.test
    thinking: true
""",
    )

    config = load(str(path))

    assert len(config.providers) == 1
    assert config.providers[0].name == "Anthropic"
    assert config.providers[0].thinking is True
    assert config.providers[0].base_url == "https://example.test"


@pytest.mark.parametrize(
    ("content", "message"),
    [
        (
            "providers:\n  - name: Test\n    protocol: openai\n    model: test\n",
            "api_key",
        ),
        (
            "providers:\n  - name: Test\n    protocol: other\n    api_key: key\n    model: test\n",
            "protocol",
        ),
    ],
)
def test_load_invalid_provider(tmp_path: Path, content: str, message: str) -> None:
    with pytest.raises(ConfigError, match=message):
        load(str(write_config(tmp_path, content)))


def test_load_missing_file(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="配置文件不存在"):
        load(str(tmp_path / "missing.yaml"))


def test_load_invalid_yaml(tmp_path: Path) -> None:
    path = write_config(tmp_path, "providers: [")

    with pytest.raises(ConfigError, match="YAML 配置解析失败"):
        load(str(path))
