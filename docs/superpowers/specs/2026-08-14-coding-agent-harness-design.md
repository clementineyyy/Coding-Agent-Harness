# 编码智能体框架（Coding Agent Harness）— 设计规格

- 日期：2026-08-14
- 状态：草稿
- 环境：Windows，Python 3.11+，模型通过 DeepSeek API（兼容 OpenAI 协议）调用

## 1. 概述

一个"最小但真实"的编码智能体框架，用于学习 opencode 和 Claude Code 这类工具的内部工作原理。它驱动 LLM 执行智能体循环——模型回合、工具调用、结果回填——并包裹一层安全与交互机制：

- **Guardrails（护栏）** 为每次工具调用把关（allow / ask / deny）
- **Sandbox（沙箱）** 隔离工具执行环境（可插拔的执行器）
- **Hooks（钩子）** 对流水线进行插桩（PreToolUse / PostToolUse / SessionEnd）
- **HITL 状态机** 协调人在环交互，包括智能体主动发起的提问
- **自适应策略（Adaptive policy）** 在会话内从用户回答中学习
- **子智能体（Subagents）** 以全新上下文递归执行同一个循环
- **技能（Skills）** 是可加载的指令文件（SKILL.md 约定），只能收紧策略，绝不可放宽
- **上下文工程 + 记忆与 RAG**：任务开始先检索记忆注入上下文，任务结束整合写入；
  TF-IDF 检索，超预算自动压缩
- **MCP** 支持：外部 MCP 服务器的工具动态注册，与内置工具同走一条流水线

主要目标：代码可读、最小化。智能体循环始终居于核心位置。

## 2. 非目标（v1 不做）

- 无 Docker 后端（先做桩实现，未安装 Docker 时快速报错；后续可接入）
- 无多用户 / 认证 / 远程访问
- 无 embeddings / 向量数据库——v1 检索用纯标准库 TF-IDF（向量检索是后续升级）
- 策略不做跨会话持久化（仅会话内生效；持久化文件留待将来）
- 不使用异步框架——同步、单线程
- 不使用 TUI 框架——纯终端 REPL

## 3. 架构

```
harness/                          # 项目根目录 == 仓库根目录
├── main.py          # REPL：提示符、菜单、中断处理
├── agent.py         # 智能体循环 + 工具流水线
├── state.py         # HITL 状态机（表驱动）
├── policy.py        # 自适应护栏策略（会话内规则）
├── guardrails.py    # 规则评估 → allow | ask | deny
├── sandbox.py       # Sandbox 接口：local（现用）、docker（桩）
├── hooks.py         # 事件总线：PreToolUse/PostToolUse/SessionEnd
├── llm.py           # DeepSeek 客户端封装
├── mcp.py           # MCP 客户端管理（stdio/url 服务器 → 注册表）
├── config.py        # 环境变量、模型、设置、mcp 配置
├── skills/          # 技能文件（SKILL.md 约定）
├── memory/          # 长期记忆文件（*.md，RAG 索引源）
├── tools/
│   ├── __init__.py  # TOOL_REGISTRY
│   ├── bash.py      # 运行 shell 命令
│   ├── files.py     # read_file, write_file
│   ├── search.py    # glob, grep
│   ├── web.py       # fetch_url
│   ├── notes.py     # note_add, note_read
│   ├── memory.py    # memory_save, memory_search（TF-IDF 检索）
│   ├── subagent.py  # run_subagent
│   ├── ask.py       # ask_user
│   └── skills.py    # list_skills, load_skill
├── transcripts/     # 会话转录（由 SessionEnd 写入）
└── tests/           # pytest + 假 LLM 客户端
```

依赖：`openai`（SDK，指向 DeepSeek）、`requests`（fetch_url）、
`mcp`（官方 Model Context Protocol SDK）。
其余全部使用 Python 标准库。

## 4. 组件

### 4.1 智能体循环（agent.py）

一个类 `Agent`。状态：`list[dict]` 消息列表（唯一的状态）。
每次任务按三个阶段执行：

**任务开始——上下文工程（Context Engineering）**
1. 检索记忆：从 `memory/` 取 top-k 相关块（TF-IDF），作为上下文注入
2. 预算检查：token 计数 vs 窗口预算；超出则先自动压缩
3. （模型中途加载的技能按同一机制注入）

**迭代——工具使用（直到最终答案）**
4. 构造请求：系统提示词 + 历史记录，`tools=` 模式来自注册表
5. 调用 DeepSeek：`client.chat.completions.create(stream=True)`，将流式文本转发到终端
6. 该回合没有工具调用 → 得到最终答案 → 进入任务结束阶段
7. 否则，通过工具流水线（第 5 节）执行每个工具调用
8. 追加 assistant 消息 + `role: "tool"` 结果 → 回到步骤 4

**任务结束——收尾**
9. 触发 `SessionEnd` 钩子（默认处理器将转录写入 `transcripts/<时间戳>.json`）
10. 记忆整合：模型总结本次会话的关键经验（决策、事实、坑）→
    `memory_save` 写入 `memory/`，供未来会话检索

循环自身的护栏：
- 步数上限（默认 50），超限时以明确消息终止失控循环
- 每次工具调用超时（默认 30s）
- 对话历史仅保存在内存中

子智能体（`run_subagent`）按同一三阶段序列执行——各自检索记忆、
各自迭代、各自收尾整合——上下文天然隔离。

### 4.2 HITL 状态机（state.py）

表驱动：一个普通字典，映射 `(state, event) → next state`。

```
状态：
  idle, running, awaiting_user, paused, completed, terminated

事件：
  task_submitted, tool_requested, approval_needed, user_answered,
  agent_question, interrupt, resume, abort, final_answer, error
```

标准转移：
- `idle + task_submitted → running`
- `running + approval_needed → awaiting_user`（护栏 ask）
- `running + agent_question → awaiting_user`（ask_user 工具）
- `awaiting_user + user_answered → running`
- `awaiting_user + abort → terminated`
- `running + interrupt → paused`；`paused + resume → running`；
  `paused + abort → terminated`
- `running + final_answer → completed`；`completed + task_submitted → running`
- 任意状态 + `error` → `running`（可恢复），除非会话已不可用 → `terminated`

每个事件都携带来源（护栏、智能体、用户、循环），便于 REPL 渲染正确的交互。

### 4.3 自适应策略（policy.py）

会话级 `Policy` 对象，持有实时规则。护栏 `ask` 的结果会反馈进去：

- 用户回答"总是允许" → 该规则降级为会话内 `allow`
- 同一模式被拒绝两次 → 自动升级为 `deny`（并发出会话提示）
- 同一模式被反复批准 → 自动降级为 `allow`
- `ask_user` 的回答会记录轻量偏好（例如"不要删除文件"→ 未来的删除操作升级为 ask）

`/rules` 显示实时策略。技能规则带 `skill:<name>` 标签，可用
`/rules drop skill:<name>` 移除。用户产生的规则永远优先于技能规则。

### 4.4 Guardrails（guardrails.py）

有序规则表：`工具模式 → allow | ask | deny`，最后匹配者生效。
规则模式为 `tool_name[:arg_regex]`——仅工具名，或工具名加一个匹配序列化参数
的正则表达式（例如 `bash:rm -rf.*`）。规则有三个来源：内置默认、用户回答
（自适应）、技能声明（仅限收紧，见 4.7）。

内置默认：
- 拒绝危险的 bash 模式（系统路径上的 `rm -rf`、fork 炸弹等）
- 拒绝在工作区之外写入
- 拒绝未经批准切换沙箱网络模式（见 4.5）
- 其余全部 allow

`ask` 判定会触发 REPL 菜单（人在环），并将状态机转入 `awaiting_user`。

### 4.5 Sandbox（sandbox.py）

`Sandbox` 接口——两种后端，按工具在注册表配置中选择：

- `local` — 直接在宿主机上运行子进程（默认；bash 使用）
- `docker` — 桩：未安装 Docker 时抛出明确错误提示需要 Docker Desktop；
  后端已完整接入接口，安装后可无缝替换，不影响其他代码

接口暴露 `network_enabled` 标志（bash 默认关闭；`fetch_url` 开启）。
会话中途切换该标志需经护栏把关（`ask`），并为会话记录一条策略规则。

文件类工具只允许操作工作区路径；路径规范化（`resolve()` + 包含性检查）
防止 `..` 逃逸和符号链接逃逸。

### 4.6 Hooks（hooks.py）

小型事件总线。用户在 `hooks.py` 中注册 Python 回调。钩子点：

- `PreToolUse(name, args)` — 观察或修改参数；仅在护栏批准之后运行；
  无法复活已被拒绝的调用
- `PostToolUse(name, args, result)` — 观察/记录
- `SessionEnd(messages)` — 任务结束时**最先**触发（早于记忆整合）；默认处理器
  将转录写入 `transcripts/<时间戳>.json`

钩子异常只记日志，绝不致命。钩子按注册顺序执行。

### 4.7 Skills（skills/）

目录约定：`skills/<name>/SKILL.md`，带 frontmatter
（`name`、`description`，可选 `rules`、`hooks`）。

工具：`list_skills`（名称 + 描述）、`load_skill(name)`（读取文件，
作为系统消息注入，并注册声明的规则/钩子）。

安全模型（仅限收紧，加载时强制）：
- 声明的 `rules` 只能是 `ask` 或 `deny`——`allow` 声明会被拒绝并给出警告后丢弃
- 声明的 `hooks` 仅限观察：PostToolUse / SessionEnd；PreToolUse 修改会被拒绝
- 违规在 `load_skill` 时大声失败，违规部分被丢弃，技能提示词本身仍可加载

### 4.8 Tools（tools/）

注册表：`TOOL_REGISTRY` 映射 `name → {description, parameters (JSON schema),
handler}`。注册表生成 API 所需的 `tools=` 载荷。

| 工具 | 处理器 | 说明 |
|---|---|---|
| `bash` | bash.py | 经 Sandbox 执行器运行，超时，捕获 stdout/stderr/退出码 |
| `read_file` | files.py | 仅工作区路径 |
| `write_file` | files.py | 仅工作区路径；受护栏把关 |
| `glob` | search.py | 仅工作区路径 |
| `grep` | search.py | 仅工作区路径 |
| `fetch_url` | web.py | `requests`，响应大小上限 |
| `note_add` / `note_read` | notes.py | 模型草稿纸（内存中） |
| `memory_save` | memory.py | 写入长期记忆 `memory/*.md`（带标签），跨会话存活 |
| `memory_search` | memory.py | 纯标准库 TF-IDF 检索，返回 top-k 相关块 |
| `run_subagent` | subagent.py | 新建 Agent，全新上下文，独立步数上限（约 30），继承护栏/钩子/策略 |
| `ask_user` | ask.py | 渲染编号菜单，回答作为工具结果返回 |
| `list_skills` / `load_skill` | skills.py | 技能加载 + 仅限收紧的注册 |
| MCP 工具（动态） | mcp.py | 会话启动时从 MCP 服务器列出并注册，走同一条流水线 |

子智能体的隔离是免费的：每个 `Agent` 持有自己的消息列表。父智能体将子智能体
的最终答案作为工具结果接收。

### 4.9 REPL（main.py）

- 提示符接受任务；智能体工作时流式输出
- 行内工具活动：`→ bash: ls -la`、`⊘ denied: ...`、`? allow ...? (y/n)`
- `ask_user` 渲染编号菜单；护栏 ask 渲染 y/n（附带"总是允许"/"绝不允许"选项）
- 命令：`/exit`、`/reset`（清空上下文）、`/skills`、`/rules`、
  `/rules drop skill:<name>`
- 每回合结束显示：token 用量 + 步数

### 4.10 LLM 封装（llm.py）+ 配置（config.py）

- `config.py` 从环境变量读取 `DEEPSEEK_API_KEY`；模型 `deepseek-chat`
- `llm.py`：薄封装——`openai.OpenAI(base_url="https://api.deepseek.com",
  api_key=...)`，暴露单一方法 `complete(messages, tools) → stream`

### 4.11 上下文工程 + 记忆与 RAG（memory.py）

**长期记忆**（`memory/` 目录 + 2 个工具）：
- `memory_save(title, content, tags)` — 智能体将持久的事实/决策/经验写入
  `memory/*.md`。跨会话存活；会话内的 `notes` 仍为内存草稿纸
- `memory_search(query)` — 检索 top-k 相关块并作为上下文返回

**记忆生命周期**：任务开始先**读取检索**（注入上下文）→ 任务结束再**整合写入**
（SessionEnd 钩子之后执行，见 4.1）。

**检索——简单 RAG，零外部依赖**：
- 按段落切分记忆文件；会话启动时建立索引
- 纯标准库 **TF-IDF**（分词 → 词频 → IDF → 余弦相似度）——约 80 行可实现，
  无新依赖，无需 embedding API（DeepSeek 本身也没有 embeddings 端点）
- 两个注入点：新任务启动时自动注入 top-2 块（低成本上下文），加上按需的
  `memory_search` 工具供模型需要更多时调用
- `load_skill` 与记忆检索共用同一注入机制（作为上下文消息追加）

**上下文窗口管理**：
- 近似 token 计数（字符数/4 启发式——不引入 tiktoken 依赖）
- 每次调用 LLM 前做预算检查：若历史超出预算，触发**自动压缩**——模型将较旧
  回合总结为一条精简系统消息（"当前状态"），保留最近 N 个回合完整不动。
  压缩设置步数上限防止死循环
- 每回合打印 token 用量（REPL 设计中已有）

**取舍说明**：embeddings 版 RAG（质量更好，但需要外部 API + 密钥 + 成本）
vs TF-IDF（免费、离线、对学习项目透明）。v1 推荐 TF-IDF——向量/embedding
路径是日后干净的升级方向。

### 4.12 MCP 支持（mcp.py）

通过官方 `mcp` Python 包（Model Context Protocol）连接外部 MCP 服务器，
将服务器的工具动态注册进 `TOOL_REGISTRY`——注册后与内置工具走同一条
流水线（护栏 → 沙箱 → 钩子 → 执行），无需特殊处理。

配置（config.py 中的 `mcp` 段，或独立 `mcp.json`）：

```json
{
  "mcp": {
    "filesystem": { "command": ["npx", "-y", "@modelcontextprotocol/server-filesystem", "./"] },
    "remote": { "url": "https://example.com/mcp" }
  }
}
```

- `stdio` 服务器：子进程方式启动（默认）；`url` 服务器：HTTP 方式连接
- 会话启动时连接服务器并列出工具；每个 MCP 工具封装为注册表条目
  （schema 原样透传，handler 转发调用）
- v1 只支持**工具**（tools），不支持 resources / prompts 通道
- 连接失败：记录警告，该服务器本会话停用，其余服务器不受影响
- 会话结束时关闭连接 / 终止子进程

## 5. 工具流水线（每次工具调用）

```
发起工具调用
  → 护栏：allow | ask | deny            （policy.py，自适应）
      ask → 状态=awaiting_user → 菜单 → 回答反馈回策略
  → 选择 Sandbox 执行器                （按工具：local / docker-桩）
  → PreToolUse 钩子                    （观察/修改；不能复活）
  → 执行                                （超时）
  → PostToolUse 钩子                   （观察/记录）
  → 结果追加为 role:"tool" 消息
```

护栏是安全边界；沙箱是执行边界；钩子是插桩；状态机是交互主轴。

## 6. 错误处理

- API 错误（密钥错误、限流、网络）：给出明确提示；会话继续存活
- 工具异常：格式化的错误作为工具结果返回给模型（模型可自我纠正）；绝不崩溃
- 护栏拒绝 / 钩子异常：拒绝优先；钩子错误只记日志
- Ctrl+C：干净退出；触发 `SessionEnd`（保存转录），随后执行记忆整合

## 7. 测试（pytest，无网络）

- 假 LLM 客户端桩掉 SDK：脚本化响应（第 1 回合 = 工具调用，第 2 回合 = 最终答案）
- 循环测试：消息历史、步数上限、护栏拒绝路径、钩子顺序
  （guardrail → PreToolUse → tool → PostToolUse）、状态机转移
- 工具测试：处理器针对临时夹具（bash 捕获、文件读写、glob/grep、
  模拟 fetch_url、笔记）
- 策略测试：双重拒绝升级、总是允许降级、技能规则拒绝
  （技能声明 allow 会被丢弃）
- 子智能体测试：父 + 子脚本化回合；断言上下文隔离
- 路径测试：`..` 与符号链接逃逸被拒绝
- 记忆/RAG 测试：memory_save 落盘、TF-IDF 检索命中/相关性排序、
  启动时自动注入 top-2
- 压缩测试：历史超出预算触发总结压缩、保留最近回合、压缩步数上限
- MCP 测试：假 stdio 服务器（测试脚本内），断言工具列出/注册/schema 透传/
  调用转发/连接失败时优雅停用
- 收尾顺序测试：任务结束时 SessionEnd 钩子先于记忆整合执行

## 8. 未决事项

无——所有决策已在头脑风暴中解决。Docker 后端为桩实现，不属未决项。