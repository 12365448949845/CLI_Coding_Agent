# Windows 工具兼容性修复 Plan

> 基于已批准的 `docs/ch03-fix/spec.md`。项目语言为 Python 3.12+。

## 架构概览

本次不新增独立子系统，沿现有边界修改三个位置：

1. **命令输出层**：`bash` 工具在拿到原始字节后，先严格尝试 UTF-8；失败时，Windows 根据当前控制台输出代码页解码，其他平台回退系统首选编码。stdout 和 stderr 使用同一策略。
2. **动态系统提示层**：把当前静态系统提示改为每次请求动态构造。构造时读取真实 OS、命令执行 shell 和 cwd，并接收本次注入的工具定义，从中生成准确工具清单和平台约束。因此切换目录后无需重启即可获得新上下文。
3. **单轮边界层**：保持现有 Agent 编排不变，只把第二批工具请求的限制提示改为清晰中文，并确保该提示作为正常助手消息进入 TUI 和对话历史。

Anthropic 和 OpenAI provider 均调用同一个动态提示构造入口，避免两套协议产生不同环境信息。

## 核心数据结构

### `RuntimeContext`

```python
@dataclass(frozen=True)
class RuntimeContext:
    os_name: str
    shell: str
    cwd: str
```

- `os_name`：`Windows`、`Linux` 或 `Darwin`。
- `shell`：命令执行器实际使用的 shell；Windows 为 `cmd.exe`，POSIX 为 `/bin/sh`。
- `cwd`：构造本次请求时的真实工作目录。

该结构只包含允许注入模型的三项信息，不携带完整环境变量。

### 工具定义列表

继续复用现有 `list[ToolDefinition]`，动态提示直接从本次请求的定义中提取工具名。提示中的工具清单与 API 实际收到的工具定义来自同一数据源，不维护第二份硬编码清单。

### 解码结果

不新增公开结果类型。命令工具仍返回现有 `Result(content, is_error)`；解码发生在构造 `content` 之前，对上层接口透明。

## 核心接口

### 运行环境检测

```python
def detect_runtime_context() -> RuntimeContext:
    ...
```

每次调用重新读取 OS、命令执行 shell 和 cwd，不缓存结果。

### 动态系统提示构造

```python
def build_system_prompt(
    tools: list[ToolDefinition],
    context: RuntimeContext | None = None,
) -> str:
    ...
```

- 默认自动调用 `detect_runtime_context()`。
- 测试可显式传入环境快照。
- 从 `tools` 生成准确工具名清单。
- Windows 环境追加 `cmd.exe` 语法约束。
- 所有环境追加 glob 不支持 brace expansion、不得编造工具等规则。
- 保留现有 `SYSTEM_PROMPT` 作为基础角色文本，避免破坏已有引用。

为避免 `prompt -> llm -> provider -> prompt` 循环依赖，`ToolDefinition` 仅在 `TYPE_CHECKING` 分支导入，运行时注解采用延迟求值。

### 命令输出解码

```python
def _decode_output(
    data: bytes,
    *,
    fallback_encoding: str | None = None,
) -> str:
    ...
```

- 首先严格按 UTF-8 解码。
- 失败后使用显式编码或运行平台检测出的回退编码。
- 最终无法完整解码时才替换非法字节。
- 测试通过显式传入 `cp936`，不依赖测试机系统语言。

```python
def _fallback_output_encoding() -> str:
    ...
```

Windows 读取当前控制台输出代码页，无法获得时使用系统 OEM 代码页；其他平台使用系统首选编码。

### Provider 调用

`Provider.stream(...)` 签名不变。Anthropic/OpenAI 适配器在每次请求内部调用：

```python
system_prompt = build_system_prompt(tool_definitions)
```

## 模块设计

### `mewcode.prompt`

**职责：**

- 检测命令实际执行环境。
- 基于本次工具定义构造完整 system prompt。
- 明确输出 OS、shell、cwd、准确工具 API 名称、只能调用清单内工具、Windows `cmd.exe` 语法限制和 glob 不支持 brace expansion。

**依赖：** 标准库 `os`、`platform`、`pathlib`；`ToolDefinition` 仅用于静态类型标注。

### `mewcode.tool.bash`

**职责：**

- 保持现有进程创建、超时和进程树终止行为。
- stdout/stderr 从原始字节进行自适应解码。
- Windows 通过控制台输出代码页或 OEM 代码页确定回退编码。
- 非 Windows 使用系统首选编码。
- UTF-8 始终优先，避免破坏现代工具输出。

### `mewcode.llm.anthropic_provider`

**职责：** 每次请求时使用本次工具定义动态构造 system prompt；其余工具定义转换、流式解析和结果回灌保持不变。

### `mewcode.llm.openai_provider`

**职责：** 每次请求时使用本次工具定义动态构造 system prompt 并放入 system 消息；其余行为保持不变。

### `mewcode.agent`

**职责：** 保持单批工具执行逻辑；第二次模型响应再次请求工具且无正文时，返回中文限制说明；限制说明进入正常助手历史并交给 TUI 渲染。

### 测试模块

- prompt 测试：环境字段、准确工具名、Windows/POSIX 规则、cwd 实时变化。
- bash 测试：UTF-8、CP936、非法字节兜底。
- provider 测试：两协议实际请求均使用动态提示。
- agent/TUI 测试：中文单轮限制提示可见且输入状态恢复。

## 模块交互

```text
用户提交消息
  -> Agent 请求 provider.stream(messages, tool_definitions)
  -> Provider 调用 build_system_prompt(tool_definitions)
       -> detect_runtime_context()
       -> 组合 OS/shell/cwd、准确工具清单与平台约束
  -> Provider 将动态 system prompt + 工具定义发送给模型
  -> 模型发起平台兼容的工具调用
  -> Registry 执行工具
       -> bash 原始 stdout/stderr bytes
       -> 严格 UTF-8
       -> 失败时按平台代码页回退
       -> Result(content)
  -> 工具结果回灌，Provider 发起一次续答请求
       -> 返回正文：正常渲染并结束
       -> 再次请求工具：不执行，输出中文单轮限制提示并结束
```

动态提示在第一次请求和结果回灌后的续答请求中都会重新构造，因此 cwd 始终取请求发出时的真实值。工具定义与提示清单使用同一份输入，避免名称漂移。

## 文件组织

```text
mewcode/
├── docs/ch03-fix/
│   ├── spec.md
│   ├── plan.md
│   ├── task.md
│   └── checklist.md
├── src/mewcode/
│   ├── prompt.py
│   ├── agent/__init__.py
│   ├── llm/
│   │   ├── anthropic_provider.py
│   │   └── openai_provider.py
│   └── tool/
│       └── bash.py
└── tests/
    ├── test_prompt.py
    ├── test_tool.py
    ├── test_llm.py
    ├── test_agent.py
    └── test_tui.py
```

不新增运行时包，不修改配置文件格式，也不修改六个工具的注册和参数定义。

## 技术决策

| 决策点 | 选择 | 理由 |
|---|---|---|
| 解码顺序 | 严格 UTF-8 -> 平台回退编码 -> 替换非法字节 | 优先兼容现代 CLI，同时正确处理 CP936 等 Windows 输出 |
| Windows 编码来源 | 当前控制台输出代码页，取不到时使用 OEM 代码页 | 与 `cmd.exe` 实际输出最接近，不依赖写死的简体中文编码 |
| 环境检测时机 | 每次模型请求重新检测 | cwd 改变后不会使用过期信息 |
| shell 标识 | 描述命令执行器实际使用的 shell | 模型需要的是工具语法，不是用户登录 shell 偏好 |
| 工具清单来源 | 从本次 `ToolDefinition` 列表动态生成 | API 定义和文字说明天然一致，避免再次出现 `ToolSearch` |
| 命令兼容方式 | 提示约束，不做自动翻译 | 自动改写 shell 命令风险高，也超出本次范围 |
| glob 兼容方式 | 明确禁止 brace expansion，不扩展工具语法 | 保持现有 Schema 和实现边界 |
| 单轮限制 | 保持现有编排，统一返回中文提示 | 尊重 ch03 范围，同时避免工具后静默结束 |
| 测试可重复性 | 环境快照和回退编码支持测试注入 | 不依赖 CI 所在 OS 和系统语言即可覆盖关键分支 |

## Spec 覆盖

| 需求 | 设计归属 |
|---|---|
| F1 | `mewcode.tool.bash` 自适应解码 |
| F2 | `RuntimeContext`、`detect_runtime_context`、`build_system_prompt` |
| F3 | 动态提示从 `ToolDefinition` 生成准确清单 |
| F4 | 动态提示中的 OS/shell 规则 |
| F5 | 动态提示中的 glob 语法规则 |
| F6 | `mewcode.agent` 中文单轮限制反馈 |

接口依赖无环；设计不修改工具 Schema、注册顺序或 Provider 上层接口；与“不加入 Agent Loop”的范围一致。
