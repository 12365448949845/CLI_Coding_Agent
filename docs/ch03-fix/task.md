# Windows 工具兼容性修复 Tasks

> 基于已批准的 `spec.md` 与 `plan.md`。每个任务完成后立即运行对应验证，验证通过后才能进入依赖它的任务。

## 文件清单

| 操作 | 文件 | 职责 |
|---|---|---|
| 修改 | `src/mewcode/prompt.py` | 运行环境检测与动态 system prompt 构造 |
| 修改 | `src/mewcode/tool/bash.py` | UTF-8 优先与平台代码页回退解码 |
| 修改 | `src/mewcode/llm/anthropic_provider.py` | Anthropic 请求使用动态提示 |
| 修改 | `src/mewcode/llm/openai_provider.py` | OpenAI 请求使用动态提示 |
| 修改 | `src/mewcode/agent/__init__.py` | 中文单轮工具限制提示 |
| 新建 | `tests/test_prompt.py` | 环境检测与提示约束测试 |
| 修改 | `tests/test_tool.py` | UTF-8、CP936 与非法字节解码测试 |
| 修改 | `tests/test_llm.py` | 两协议动态提示请求测试 |
| 修改 | `tests/test_agent.py` | 中文单轮限制与不执行第二批工具测试 |
| 修改 | `tests/test_tui.py` | 中文限制提示可见性与输入恢复测试 |

## T1：定义运行环境快照与检测

**文件：** `src/mewcode/prompt.py`  
**依赖：** 无

**步骤：**

1. 启用延迟注解，增加不可变 `RuntimeContext(os_name, shell, cwd)`。
2. 新增 `detect_runtime_context()`，每次调用读取 `platform.system()` 与 `os.getcwd()`。
3. Windows shell 使用 `COMSPEC` 的文件名，缺失时回退 `cmd.exe`；非 Windows 使用 `/bin/sh`，与 `asyncio.create_subprocess_shell` 的实际执行语义一致。
4. 不读取或返回其他环境变量值。

**验证：** `python -c "from mewcode.prompt import detect_runtime_context; print(detect_runtime_context())"` 输出当前 OS、shell 和 cwd；`ruff check src/mewcode/prompt.py` 无告警。

## T2：测试环境检测与 cwd 实时更新

**文件：** `tests/test_prompt.py`  
**依赖：** T1

**步骤：**

1. 测试真实 `detect_runtime_context()` 的 cwd 等于 `os.getcwd()`。
2. 用 `monkeypatch.chdir(tmp_path)` 后再次检测，断言 cwd 更新为新目录。
3. 分别模拟 Windows 与非 Windows，断言 shell 为 `cmd.exe` 或 `/bin/sh`，且结果中不包含环境变量集合。

**验证：** `pytest -q tests/test_prompt.py -k context` 通过。

## T3：实现动态 system prompt

**文件：** `src/mewcode/prompt.py`  
**依赖：** T1

**步骤：**

1. 保留 `SYSTEM_PROMPT` 作为基础角色文本。
2. 仅在 `TYPE_CHECKING` 下导入 `ToolDefinition`，避免循环依赖。
3. 新增 `build_system_prompt(tools, context=None)`；未提供 context 时实时检测。
4. 在提示中列出 OS、shell、cwd，以及按传入顺序排列的准确工具 API 名称。
5. 明确只能调用/陈述清单内工具，不存在 `ToolSearch`；工具名必须保持原始 snake_case。
6. Windows 明确要求 `cmd.exe` 语法并禁止 `pwd`/`ls` 等 POSIX 命令。
7. 明确 glob 不支持 brace expansion，多扩展名应发起多个合法 glob 调用。

**验证：** `python -c "from mewcode.prompt import RuntimeContext, build_system_prompt; print(build_system_prompt([], RuntimeContext('Windows','cmd.exe','C:/work')))"` 输出完整环境与约束；`ruff check` 通过。

## T4：测试动态提示约束

**文件：** `tests/test_prompt.py`  
**依赖：** T3

**步骤：**

1. 构造六个 `ToolDefinition`，断言提示按原名与顺序列出且不生成 PascalCase 别名。
2. 断言提示明确禁止编造未注册工具和 `ToolSearch`。
3. Windows context 下断言存在 `cmd.exe`、POSIX 命令禁用和 cwd。
4. POSIX context 下断言 shell 为 `/bin/sh`，且不错误宣称当前环境是 Windows。
5. 断言 brace expansion 限制和多 glob 调用建议存在。

**验证：** `pytest -q tests/test_prompt.py` 全通过。

## T5：实现命令输出自适应解码

**文件：** `src/mewcode/tool/bash.py`  
**依赖：** 无

**步骤：**

1. 新增 `_fallback_output_encoding()`：Windows 读取 `GetConsoleOutputCP`，取不到时读取 `GetOEMCP`；其他平台使用 `locale.getpreferredencoding(False)`，空值回退 UTF-8。
2. 新增 `_decode_output(data, fallback_encoding=None)`：严格 UTF-8 成功则直接返回；失败后按显式或自动回退编码解码；回退编码仍有非法字节时使用替换策略；无效 codec 名回退系统编码/UTF-8，不能抛到工具层。
3. stdout 和 stderr 都改用 `_decode_output`。
4. 不修改进程创建、超时、终止、截断和 `is_error` 逻辑。

**验证：** `python -c "from mewcode.tool.bash import _decode_output; print(_decode_output('中文'.encode('cp936'), fallback_encoding='cp936'))"` 输出 `中文`；现有 bash 超时测试继续通过。

## T6：测试 UTF-8 与 CP936 解码

**文件：** `tests/test_tool.py`  
**依赖：** T5

**步骤：**

1. 断言 UTF-8 中文字节优先正确解码。
2. 断言 CP936 编码的 Windows `dir` 风格中文通过显式回退解码且不含 `�`。
3. 断言包含非法尾字节时返回可显示字符串而不抛异常。
4. 在 Windows 上补充调用真实当前代码页命令的条件测试；非 Windows 自动跳过。
5. 保留现有成功、非零退出、超时和长输出截断测试。

**验证：** `pytest -q tests/test_tool.py` 全通过；`ruff check tests/test_tool.py` 无告警。

## T7：Anthropic 使用动态提示

**文件：** `src/mewcode/llm/anthropic_provider.py`  
**依赖：** T3

**步骤：**

1. 导入 `build_system_prompt`，不再把静态 `SYSTEM_PROMPT` 直接放入请求。
2. 在 `stream` 每次调用时先归一化 `tools`，再用同一列表构造提示与 API tools 参数。
3. 保持 thinking、消息转换和流式工具调用解析逻辑不变。

**验证：** `ruff check src/mewcode/llm/anthropic_provider.py` 无告警；现有 Anthropic 流测试通过。

## T8：OpenAI 使用动态提示

**文件：** `src/mewcode/llm/openai_provider.py`  
**依赖：** T3

**步骤：**

1. 让 `_to_openai_messages` 接收本次构造的 system prompt，不再内部读取静态常量。
2. 在 `stream` 每次调用时先归一化 `tools`，调用 `build_system_prompt`，再构造消息和 API tools 参数。
3. 保持 base_url、流式正文、工具参数分片和结果回灌逻辑不变。

**验证：** `ruff check src/mewcode/llm/openai_provider.py` 无告警；现有 OpenAI 流测试通过。

## T9：验证两协议请求使用同一动态提示

**文件：** `tests/test_llm.py`  
**依赖：** T7、T8

**步骤：**

1. 更新原有静态 `SYSTEM_PROMPT` 断言，使其验证动态提示包含基础文本、真实环境和传入工具名。
2. Anthropic fake 请求断言 `system` 与 `build_system_prompt(definitions)` 一致。
3. OpenAI fake 请求断言首条 system 消息与同样输入构造的提示一致。
4. 保留两协议工具定义注入、分片拼接与结果回灌断言。

**验证：** `pytest -q tests/test_llm.py` 全通过；输出证明两协议请求使用同一提示构造规则。

## T10：中文化单轮工具限制反馈

**文件：** `src/mewcode/agent/__init__.py`、`tests/test_agent.py`  
**依赖：** 无

**步骤：**

1. 将 `SINGLE_ROUND_LIMIT_MESSAGE` 改为简洁中文，说明本轮已达到一次工具执行上限，并提示用户发送后续消息继续。
2. 保持“只有续答再次请求工具且没有正文时才补提示”的条件不变。
3. 更新测试断言中文提示进入 Event 文本和最后一条 assistant 历史。
4. 继续断言第二批工具没有被执行。

**验证：** `pytest -q tests/test_agent.py -k second_tool_batch` 通过。

## T11：验证 TUI 显示中文限制并恢复输入

**文件：** `tests/test_tui.py`  
**依赖：** T10

**步骤：**

1. 新增 fake provider：第一次请求工具，续答再次请求工具且不返回正文。
2. 提交消息后等待 turn 完成，断言 scrollback 出现中文限制提示。
3. 断言状态回到 `IDLE`、输入框可再次提交。
4. 断言 registry 只执行第一次工具调用。

**验证：** `pytest -q tests/test_tui.py -k single_round` 通过。

## T12：全量回归与 Windows 实机验收

**文件：** 无  
**依赖：** T2、T4、T6、T9、T10、T11

**步骤：**

1. 运行 `pytest -q`、`ruff check .`、`ruff format --check .`、`mypy src/mewcode`。
2. 运行 `python -m mewcode`，确认 TUI 正常启动并可用 `/exit` 退出。
3. 用当前 DeepSeek 配置询问“帮我看看项目入口文件有什么”，记录首批工具名与参数；确认不再出现 `pwd`、`ls`、`*.{...}` 或 `ToolSearch`。
4. 执行包含 Windows 当前代码页中文输出的命令，确认工具结果和 TUI 摘要不含 `�`。
5. 若任务需要第二批工具，确认显示中文单轮限制提示并恢复输入。

**验证：** 所有自动化命令通过；真实 Windows 场景满足 AC1、AC4、AC5、AC6、AC7。

## 执行顺序

```text
T1 -> T2
  \-> T3 -> T4 -> T7 -> T9
              \-> T8 -/

T5 -> T6 ----------------\
T10 -> T11 ---------------+-> T12
T2,T4,T9 ----------------/
```
