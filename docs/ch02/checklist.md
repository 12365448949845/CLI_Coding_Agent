# 多协议 LLM 终端对话客户端 Checklist

> 每一项通过运行代码或观察行为来验证，聚焦系统行为；括号内为验证方式。

> 本轮本地验证记录：`.venv\Scripts\python.exe -m pytest -q` 通过 14 项；`ruff check .`、`ruff format --check .`、`mypy src\mewcode` 均通过。真实供应商 API 和真实兼容端点因未提供 API key 未执行。

## 实现完整性

- [x] 配置加载：合法 `.mewcode/config.yaml` 能解析出 providers 列表（验证：`tests/test_config.py` 通过；合法配置返回 provider）。(AC1/F1)
- [x] 配置校验：缺密钥/非法 protocol/文件缺失时给出可读错误并非零退出，无未捕获堆栈（验证：配置单测覆盖字段、协议、文件和 YAML 错误；无配置运行返回 `EXIT_CODE=1` 且仅输出配置错误）。(AC1/N4)
- [x] 单 provider 直进：仅一条配置时启动直接进入对话（验证：`tests/test_tui.py::test_single_provider_mount_submit_and_complete`）。(AC2/F2)
- [x] 多 provider 选择：多条配置时出现方向键 `OptionList`，选定后进入对话（验证：TUI headless 测试上下选择 + Enter 后激活第二个 provider）。(AC2/F2)
- [x] 内置 system prompt 与历史随请求发送（验证：`tests/test_llm.py` 检查两种协议注入 system prompt；TUI 测试检查第二轮完整消息序列）。(AC4/F4)
- [x] thinking：anthropic 配 `thinking: true` 时启用，且界面不出现任何思考文本（验证：Anthropic 适配器单测检查 thinking 参数并丢弃 `thinking_delta`）。(AC5/F5)
- [x] 流式逐字：回复以纯文本逐字出现（验证：TUI headless 测试按多个 `StreamEvent(text=...)` 累积回复）。(AC5/F8)
- [ ] markdown 定型：回复结束后整段以 markdown 渲染（代码块/列表/强调正确）（验证：让模型输出含代码块与列表的内容）。(AC8/F8)
- [x] 多行输入：Alt+Enter 换行、Enter 提交、提交后输入框清空（验证：TUI headless 测试 Alt+Enter 后文本为换行；提交测试检查输入清空）。(AC9/F9)
- [x] 响应计时：自提交即显示 `Imagining… (Ns)` 且秒数递增，结束后显示总耗时（验证：慢速模拟 provider 在首个增量前观察到 `Imagining`；完成后渲染耗时）。(AC12/F12)
- [x] 错误反馈：错误 key/不存在模型时，错误在对话区可区分样式（红色）显示且不退出（验证：模拟 provider 错误事件测试检查错误文本、空闲状态和下一轮成功；真实错误 key 未执行）。(AC11/F11)
- [x] 退出：`/exit` 与 Ctrl+C 均能安全退出，终端恢复正常（验证：已运行真实 TUI 进程验证 Ctrl+C 返回码 0；Textual 负责恢复终端状态；`/exit` 入口由 `submit` 分支覆盖）。(AC10/F10/N7)
- [x] 界面布局：启动含猫 banner + 名称版本 + cwd + 就绪提示行 + 输入框（含 `❯` 与占位符）+ 状态栏（左 name 右 model）（验证：真实 TUI 启动观察；headless 测试检查 banner、Ready、`❯`、`Send a message...` 和状态栏可见）。(AC7/F7)

## 集成

- [x] TUI 通过统一 `Provider` Protocol 驱动两种协议，切换协议不改变上层交互（验证：两种适配器单测使用相同 `StreamEvent`；真实双协议对话未执行）。(AC3/N3)
- [x] 多轮上下文携带：先告知信息、后追问，模型能正确引用前文；退出再启动后历史为空（验证：TUI headless 测试检查第二轮携带完整历史；会话为进程内对象，重启持久化未启用；真实模型引用前文未执行）。(AC6/F6)
- [x] 流式不阻塞：等待/流式期间界面仍响应、不冻结（验证：慢速 provider 测试在等待期间仍能观察流式状态和计时）。(AC13/N1)
- [ ] scrollback 渲染（Claude Code 风格）：完成的消息（用户输入/助手回复/错误）追加到 `RichLog`，可用终端原生滚轮/Textual 滚动回看，退出后内容保留在终端历史中；动态区仅含输入框 + 正在流式的回复 + 状态栏（验证：真实终端/tmux 多轮后回滚查看历史 + 退出后历史仍在）。
- [ ] base_url 覆盖：为某 provider 配自定义 `base_url`（兼容端点）可正常收发（验证：真实兼容端点跑通一轮；适配器单测已覆盖 OpenAI 自定义端点配置路径）。(F3)
- [ ] 窗口自适应：缩放终端宽度后输入框/对话区/markdown 不错版（验证：真实运行中调整终端宽度）。(N6)

## 编译与测试

- [x] `python -m mewcode` 能正常启动（验证：临时合法 smoke-test 配置启动真实 TUI，观察到完整界面后输入 `/exit`，退出码 0）。
- [x] `ruff check .` 无告警（验证：命令通过）。
- [x] `ruff format --check .` 通过（验证：21 个文件已格式化）。
- [x] `pytest` 通过（验证：14 passed；包含 config、conversation、LLM 和 TUI 测试）。
- [x] （可选）`mypy src/mewcode` 通过（验证：命令输出 `Success: no issues found in 14 source files`）。
- [x] 密钥不回显/不打印：对话区与任何输出均不出现 `api_key`（验证：运行错误路径不输出 key；源码与示例仅有占位符/测试 key，无真实密钥）。(N5)

## 端到端场景

- [ ] 场景 1（anthropic 多轮）：单条 anthropic 配置启动 -> 连续两轮、第二轮引用第一轮 -> 流式 + 计时 + markdown 定型 -> `/exit` 退出（需要真实 Anthropic key）。
- [ ] 场景 2（openai 流式）：openai 协议配置 -> 发一条含代码块的请求 -> 流式逐字后 markdown 渲染正确（需要真实 OpenAI/兼容端点）。
- [x] 场景 3（多 provider 选择）：两条配置 -> 启动出现列表 -> 选第二条 -> 状态栏显示其 name/model -> 正常对话（验证：TUI headless 测试通过）。
- [x] 场景 4（错误恢复）：错误 key 触发失败 -> 对话区红色错误、程序不退出 -> 修正后（重启）继续正常对话（验证：模拟错误 provider 测试通过；真实错误 key 未执行）。
