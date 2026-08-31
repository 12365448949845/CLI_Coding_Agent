# 工具系统 Checklist

> 每一项通过运行代码或观察行为来验证，聚焦系统行为；括号内为验证方式与对应需求。

## 实现完整性

- [x] 注册中心导出 6 条工具定义且按名可查（证据：`tests/test_tool.py` 验证固定顺序、命中、未命中与重复注册）。(AC1/F1)
- [x] read_file 带行号读出内容；读不存在/目录返回结构化错误（证据：大文件 2000 行截断与不存在文件单测；真实 DeepSeek 闭环读取 `docs/ch03/spec.md` 成功）。(AC2/F2)
- [x] write_file 创建/覆盖文件，父目录自动创建（证据：`tmp_path` 嵌套路径创建与覆盖单测）。(AC3/F2)
- [x] edit_file 唯一匹配替换成功；0 处与 >1 处返回**可区分**错误（含匹配数）（证据：0/1/2 处三种单测均通过）。(AC4/F2)
- [x] bash 返回 stdout/stderr/退出码；超时命令被终止并返回超时结果（证据：成功、退出码 3、50ms 超时单测；超时用例实际耗时约 0.07s）。(AC5/F2/N1)
- [x] glob 列出匹配文件；grep 返回 `file:line:content`（证据：嵌套 Python 文件 glob 与正则命中单测）。(AC6/F2)
- [x] 流式工具调用解析正确：模型一次回复的工具名与完整 JSON 参数被拼齐（证据：Anthropic `input_json_delta` 与 OpenAI `delta.tool_calls` 分片测试；真实 DeepSeek 解析出 `read_file(docs/ch03/spec.md)`）。(AC7/F4)
- [x] 单轮闭环端到端：问“读 X 并总结”→ 模型调用 read_file → 结果回灌 → 给出最终文本总结（证据：真实 DeepSeek 请求形成 `user → assistant → tool → assistant` 并正确总结 ch03 spec）。(AC8/F5/F6)
- [x] 单轮上限：需连续两步工具的任务，第一轮工具后即停、不发起第二轮工具执行（证据：`tests/test_agent.py` 验证仅首批工具被执行，并返回单轮上限提示）。(AC9/F6)
- [x] 工具行 Claude Code 风格：对话区出现 `● name(关键参数)` + 缩进结果摘要，过长截断（证据：Textual 集成测试验证 Running 状态、工具行、结果摘要与 scrollback 顺序）。(AC11/F8)
- [x] 工具失败结构化回灌且 UI 可区分、程序不退出（证据：不存在文件、edit 0 匹配、bash 非零退出单测；TUI 工具错误后下一轮恢复测试）。(AC12/F9/N4)

## 集成

- [ ] 两协议工具流程一致：适配器层的 Anthropic/OpenAI 工具注入、流式拼接与回灌单测均通过，OpenAI 兼容端点真实闭环通过；当前没有 Anthropic 凭据，尚未完成 Anthropic 实机端到端。(AC10/F3/F7/N3)
- [x] 结果回灌进历史并被第二轮请求携带（证据：Agent 测试与真实 DeepSeek 请求均观察到 assistant tool call + tool result，并在续答请求中携带）。(F6)
- [x] 工具执行不阻塞界面（证据：Textual 测试在工具等待期间观察到 `● read_file(sample.txt) Running…`，释放后正常完成）。(N2)
- [x] scrollback 顺序正确（证据：TUI 测试逐项比较 preamble、工具行、结果摘要、最终答复在 `RichLog` 中的位置）。(F8)
- [x] 结果体量受控（证据：>2000 行文件、40000 字符命令输出、105 条 grep 命中均以 `[truncated]` 截断）。(AC13/N5)
- [x] 系统提示词体现 Agent 角色（证据：自动检查确认提示词包含 read/write/edit/shell/find/search 六类能力）。(F3)

## 编译与测试

- [x] `python -m mewcode` 能正常启动（证据：实际进入 TUI，状态栏显示活动 provider/model，输入 `/exit` 后退出码 0）。
- [x] `ruff check .` 无告警。
- [x] `ruff format --check .` 通过（31 个文件均已格式化）。
- [x] `pytest -v` 通过（最终全量测试见验收报告）。
- [x] `mypy src/mewcode` 通过（22 个源文件无问题）。
- [x] 密钥不回显/不打印（证据：启动、测试与真实请求输出均未出现密钥；配置检查只报告 `has_key=True`）。(N6)

## 端到端场景

- [x] 场景 1（读文件并总结）：真实 DeepSeek/OpenAI 兼容端点触发 `read_file(docs/ch03/spec.md)`，结果回灌后返回准确英文总结；TUI 工具行和 `/exit` 分别通过集成与启动冒烟验证。
- [x] 场景 2（写/改/执行链路）：脚本模型单批请求 `write_file → edit_file → bash`，三个真实工具顺序执行，磁盘最终内容和 bash 回读均为 `after`。
- [x] 场景 3（错误恢复）：TUI 集成测试触发 edit 0 匹配错误，错误结果写入 scrollback，随后一轮返回 `Recovered on the next turn.`。
- [ ] 场景 4（跨协议，若有 anthropic 配置）：当前没有 Anthropic 配置/凭据，未做实机验证；协议映射与分片解析单测已通过。
