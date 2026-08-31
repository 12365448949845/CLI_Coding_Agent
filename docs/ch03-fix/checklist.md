# Windows 工具兼容性修复 Checklist

> 每一项都通过运行代码或观察行为验证；未取得实际证据前不得勾选。

## 实现完整性

- [x] UTF-8 中文命令输出保持可读（验证：向解码入口传入 UTF-8 中文字节，期望原文返回且无 `�`）。(AC1/F1/N1)
- [x] CP936 中文命令输出正确回退解码（验证：传入 Windows `dir` 风格 CP936 字节，期望中文可读且无 `�`）。(AC1/F1)
- [x] 无法完整解码的字节返回可显示结果而不抛异常（验证：传入含非法尾字节的数据，期望得到带替换标记的字符串）。(F1/N1)
- [x] stdout 与 stderr 使用相同自适应解码规则（验证：fake 子进程或真实命令分别在两路输出本地编码文本，期望均可读）。(F1)
- [x] 每次模型请求包含真实 OS、命令 shell 和 cwd（验证：捕获动态 system prompt 并与当前进程状态对比）。(AC2/F2/N4)
- [x] cwd 改变后下一次提示同步更新（验证：切换临时目录后重新构造提示，期望出现新绝对路径）。(AC2/N4)
- [x] 提示中的工具清单与本次注册定义完全一致且顺序一致（验证：用六工具定义构造提示并逐项对比）。(AC3/F3)
- [x] 提示明确禁止 `ToolSearch`、PascalCase 别名和其他未注册工具（验证：检查动态提示约束文本）。(AC3/F3)
- [x] Windows 提示明确使用 `cmd.exe`，不使用 `pwd`、`ls` 等 POSIX 命令（验证：Windows context 构造提示并检查约束）。(AC4/F4)
- [x] glob 提示明确不支持 brace expansion，多扩展名应使用多个合法调用（验证：检查提示包含 `{py,json}` 反例与替代行为）。(AC5/F5)
- [x] 续答再次请求工具时不执行第二批，并生成中文限制提示（验证：fake provider 两次请求工具，断言 registry 仅执行首批且最后助手消息为中文提示）。(AC6/F6)

## 集成

- [x] Anthropic 请求的 system prompt 包含动态环境和本次工具清单（验证：fake client 捕获请求参数并与提示构造结果比较）。(AC2/AC3/AC8)
- [x] OpenAI 请求的 system 消息包含同一动态环境和工具清单（验证：fake client 捕获 messages[0] 并与提示构造结果比较）。(AC2/AC3/AC8)
- [x] 两协议的工具定义注入、流式调用拼接和结果回灌测试继续通过（验证：运行 `tests/test_llm.py`）。(AC8/N5)
- [x] TUI 在单轮限制场景显示中文提示并恢复输入状态（验证：Textual 集成测试观察 scrollback、`IDLE` 状态及下一次提交）。(AC6/AC7)
- [x] Windows 本地代码页工具结果在 TUI 摘要中无乱码（验证：运行本地编码命令，观察工具结果行不含 `�`）。(AC1/AC7)
- [x] 六工具公开参数、注册顺序、超时与截断行为未变化（验证：原有 tool/agent 测试全部通过）。(N5)
- [x] 动态提示不包含 API 密钥或环境变量值（验证：用标记值配置环境与 provider，检查请求 system prompt 未出现标记）。(N3)

## 编译与测试

- [x] `python -m mewcode` 使用合法配置正常进入 TUI，并可用 `/exit` 以退出码 0 退出。
- [x] `pytest -q` 全部通过。
- [x] `ruff check .` 无告警。
- [x] `ruff format --check .` 通过。
- [x] `mypy src/mewcode` 通过。
- [x] 测试输出与 TUI 中不出现 API 密钥。(N3)

## 端到端场景

- [x] 场景 1（Windows 中文输出）：运行产生当前代码页中文 stdout/stderr 的命令 -> 工具行与结果摘要中文可读 -> 回灌内容不含 `�`。(AC1/AC7)
- [x] 场景 2（项目入口查询）：用当前 DeepSeek 配置询问“帮我看看项目入口文件有什么” -> 首批调用使用 `cmd.exe` 兼容命令或合法 glob -> 不出现 `pwd`、`ls`、`*.{...}`、`ToolSearch`。(AC3/AC4/AC5)
- [x] 场景 3（单轮边界）：任务在续答阶段再次请求工具 -> 第二批不执行 -> TUI 显示中文上限提示 -> 输入框恢复可用。(AC6/AC7)
- [x] 场景 4（纯文本与原工具回归）：普通对话、读文件、写/改/执行批次继续正常完成，历史顺序和结果不变。(AC8/N5)

## 验收记录（2026-08-31）

- 自动化：`pytest -q` 为 42 passed；`ruff check .`、`ruff format --check .`、`mypy src/mewcode` 全部通过。
- Windows/TUI：CP936 中文 stdout 与 stderr 均可读，scrollback 中无 `�`，结束后状态恢复为 `IDLE`。
- 真实 DeepSeek：询问“帮我看看项目入口文件有什么”后，首批调用为 `bash(dir /a)` 与 `glob(*)`，未出现 POSIX 命令、brace glob 或 `ToolSearch`。
- 单轮边界：DeepSeek 续答再次请求工具时未执行第二批；Textual 集成测试确认中文限制提示可见，且下一条消息可继续提交。
- 启停：`DeepSeek V4 Pro / deepseek-v4-pro` 配置正常进入 TUI，`/exit` 退出码为 0。
