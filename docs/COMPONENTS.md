# 组件理论文档（COMPONENTS.md）

本文档按 spec §3 的**六维度**组织，逐节说明每个维度的组件文件、测试文件，
以及组件要**验证的理论 / 设计假设**（对应 spec 章节号）。设计规格：
`docs/superpowers/specs/SPEC.md`。

---

## 0. 总览：六维度与支撑组件

| 维度 | 核心组件 | spec |
|---|---|---|
| 治理护栏 | `guardrails.py`、`policy.py`、`state.py` | §3.4、§11.2、§11.4 |
| 安全沙箱 | `sandbox.py` | §11.3 |
| 记忆 | `memory.py`、`tools/memory.py` | §3.3 |
| 上下文工程 | `agent.py`、`llm.py` | §3.1、§3.3 |
| 人机协同 HITL | `main.py`、`state.py`、`tools/ask.py` | §11.4 |
| 反馈闭环 | `agent.py` | §3.6 |

支撑组件：注册表与类型 `registry.py`、内置工具 `tools/*.py`、MCP `mcp.py`、
钩子 `hooks.py`、转录 `transcript.py`、凭据 `credentials.py`、配置 `config.py`、
LLM 客户端 `llm.py`、REPL `main.py`、测试辅助 `fake_llm.py`。

---

## 1. 治理护栏（guardrails / policy / state）

### 组件文件

- `harness/guardrails.py`：`Rule`、`Verdict`、`default_rules()`（内置危险模式
  清单）、`evaluate()`（有序遍历、最后匹配生效）。
- `harness/policy.py`：`Policy` 自适应策略——`apply_answer()`（always_allow
  降级 allow / never_allow 升级 deny / 同一模式拒绝两次自动 deny / 反复批准
  自动降级 allow）、`add_skill_rules()`（仅接受 ask/deny）。
- `harness/state.py`：`StateMachine` 表驱动状态机（`TRANSITIONS`，非法转移
  抛 `StateError`）。

### 测试文件

- `harness/tests/test_guardrails.py`：内置 deny 清单、最后匹配生效。
- `harness/tests/test_policy.py`：自适应升降级、技能规则仅收紧、规则冲突。
- `harness/tests/test_state.py`：完整转移表、非法转移抛错、terminated 终结。
- `harness/tests/test_acceptance_matrix.py`（§3.4 条目）：ask 无超时放行路径等。
- `harness/tests/mechanism_demo/demo_1_guardrail_deny.py`：护栏拒绝演示。

### 验证的理论 / 设计假设

- **护栏先行且不可被钩子复活**：`evaluate` 是流水线第一环（§11.5），
  deny 在 PreToolUse 钩子之前返回，钩子无法复活被拒调用（§3.4）。
- **规则冲突仲裁**：内置默认（不可删）< 技能收紧 < 用户自适应；同来源内
  最后匹配生效（§11.2）。用户规则永远优先于技能规则，且不删除技能规则。
- **自适应策略防止"策略疲劳"**：同一模式拒绝两次自动升级 deny、反复批准
  自动降级 allow，护栏不会因用户习惯性放行而形同虚设（§11.6）。
- **ask 判定无超时放行路径**：必须等待用户回答，代码路径上不存在自动放行
  （§3.4 边界条件）。
- **状态机是交互主轴**：表驱动、事件携带来源（guardrail/agent/user/loop），
  非法转移立即抛错，使 HITL 交互可被确定性测试（§11.4）。

---

## 2. 安全沙箱（sandbox）

### 组件文件

- `harness/sandbox.py`：`Sandbox` 抽象（`run` / `cancel`）、`SandboxResult`、
  `LocalSandbox`（宿主子进程）、`DockerSandbox`（`docker run --rm`
  `--network=none` `-v workspace:/workspace`）、`DockerUnavailableError`。

### 测试文件

- `harness/tests/test_sandbox.py`：超时返回 exit_code=-1、输出截断标记、
  docker 缺失快速报错、cancel 幂等。
- `harness/tests/test_registry.py`：`validate_args` 的路径包含性检查
  （`x-workspace-path` 防 `..` 逃逸）。

### 验证的理论 / 设计假设

- **local 后端非隔离，隔离靠护栏**：`LocalSandbox` 是宿主直接子进程，**不是
  安全边界**；危险操作由护栏 deny/ask + 路径包含性检查承担第一道防线
  （§11.3）。文档必须明确声明这一点，防止用户误以为默认后端有隔离。
- **docker 后端提供真实隔离**：`--network=none` 无网络、容器文件系统与宿主
  隔离、读不到宿主凭据；未安装 docker 时快速报错而非静默降级（§11.3、§5.3）。
- **执行边界确定性**：超时（默认 30s）与输出截断（`max_output_bytes`）保证
  单次执行有界，配合 §3.6 反馈闭环让模型读到格式化错误而非崩溃（§3.2）。

---

## 3. 记忆（memory）

### 组件文件

- `harness/memory.py`：`MemoryStore`——`load()` 建 TF-IDF 索引（段落分块、
  双字 n-gram 分词，中英文）、`save()`（标题消毒、超长分段）、`search()` /
  `top_k_chunks()`（任务启动注入）。
- `harness/tools/memory.py`：`memory_save` / `memory_search` 工具。

### 测试文件

- `harness/tests/test_memory.py`：top-k 注入、TF-IDF 相关性排序、损坏文件跳过。
- `harness/tests/test_tools_memory.py`：工具 handler、无记忆库时返回错误。
- `harness/tests/test_agent_end.py`：SessionEnd 钩子先执行、记忆整合后执行。
- `harness/tests/test_agent_context.py`：任务开始时记忆注入进系统消息。
- `harness/tests/test_acceptance_matrix.py`（§3.3 条目）。

### 验证的理论 / 设计假设

- **无 embeddings 的检索足够可用**：DeepSeek 无 embeddings 端点，纯标准库
  TF-IDF（§3.3 边界条件）在记忆库规模（文件级 chunk）下检索质量/成本可接受
  （§4.1 O(n) 冒烟测试：`test_perf_smoke.py`）。
- **记忆生命周期顺序**：读取（任务开始）→ 使用（memory_search）→ 整合写入
  （任务收尾、SessionEnd **之后**），顺序可断言（§5.2）。
- **记忆污染有兜底**：损坏文件跳过并警告、检索失败返回空不阻塞任务、
  `/memory` 可查（§10.1）。

---

## 4. 上下文工程（context）

### 组件文件

- `harness/agent.py`：`_check_budget()`（字符数/4 近似 token）、`_compress()`
  （模型总结较旧回合 → 保留最近 N 回合 + 摘要系统消息）、`_drop_oldest()`
  （降级路径）。
- `harness/memory.py`：启动注入 top-2（与 §3 记忆联动）。
- `harness/llm.py`：流式输出即时转发、`approx_tokens` 统计。

### 测试文件

- `harness/tests/test_agent_context.py`：预算边界（恰好不超）、压缩成功
  保留尾段与摘要、压缩失败降级丢弃最旧、压缩轮数上限。
- `harness/tests/test_llm.py`：流式 chunk 聚合、tool_calls 增量解析、
  JSON 损坏报错。
- `harness/tests/test_perf_smoke.py`：会话启动 < 1s、检索 < 50ms（100 条目）。

### 验证的理论 / 设计假设

- **先压缩再降级**：超预算先尝试模型总结压缩；压缩失败（LLM 异常/空摘要/
  超过轮数上限）降级为丢弃最旧回合，任务永不因上下文超限崩溃（§3.3 错误处理）。
- **压缩有界**：`compression_max_rounds` 防压缩死循环；保留最近 N 回合保证
  局部上下文完整（§3.3 边界条件）。
- **token 近似开销可忽略**：字符数/4 近似 + 流式无缓冲，满足 §4.1 性能目标
  （性能冒烟测试佐证）。

---

## 5. 人机协同 HITL（ask / state）

### 组件文件

- `harness/main.py`：`ask_menu()`（编号菜单、EOF→KeyboardInterrupt）、
  `_handle_interrupt()`（interrupt→paused、resume/abort 菜单、仅允许恢复
  一次）、`_first_run_wizard()`（首次运行 key 向导）。
- `harness/state.py`：`awaiting_user` 状态与 `approval_needed` /
  `agent_question` / `user_answered` 转移。
- `harness/agent.py`：`_ask()`（y/n/always_allow/never_allow 四选项）。
- `harness/tools/ask.py`：`ask_user` 工具（经 awaiting_user 返回用户回答）。

### 测试文件

- `harness/tests/test_state.py`：interrupt→paused、resume→running、
  abort→terminated 全转移。
- `harness/tests/test_tools_ask.py`：ask_user 渲染菜单、回答作为工具结果。
- `harness/tests/test_repl.py`：Ctrl+C 菜单、顶层退出触发 SessionEnd、
  ask 菜单重试、首次输入即任务。
- `harness/tests/mechanism_demo/demo_3_hitl_trace.py`：HITL 状态轨迹演示。

### 验证的理论 / 设计假设

- **ask 与 agent_question 共用 awaiting_user，但语义不同**：前者回答进策略
  （`apply_answer`），后者作为工具结果回灌（§11.4 关键性质）——同一状态
  通过事件来源区分渲染与语义。
- **用户始终掌控会话**：Ctrl+C 干净退出并触发 SessionEnd（US-4 验收）；
  interrupt 先终止在途子进程（executing + interrupt → paused，§11.4）。
- **ask 必须等待**：`ask_menu` 无超时放行路径，EOF 抛 KeyboardInterrupt 走
  abort 而非静默放行（§3.4 边界条件）。

---

## 6. 反馈闭环（feedback）

### 组件文件

- `harness/agent.py`：`run()` 中失败序列统计（`fail_seq` / `fail_tool`）、
  `failure_budget` 触发停止并向用户报告；工具结果（`status` / `error` /
  `exit_code`）逐回合回灌为 `role:"tool"` 消息。
- `harness/registry.py`：`ToolResult` 承载确定性反馈信号。

### 测试文件

- `harness/tests/test_agent_feedback.py`：注入失败后下一回合动作改变、
  连续失败 3 次停止重试。
- `harness/tests/test_acceptance_matrix.py`（§3.6 条目）。
- `harness/tests/mechanism_demo/demo_2_feedback_change.py`：反馈修正演示。

### 验证的理论 / 设计假设

- **客观反馈信号可回灌**：`exit_code`、`is_error`、stdout/stderr、护栏拒绝
  reason 是确定性的"行为是否正确"证据；错误以格式化文本返回、绝不抛异常，
  模型因此总能读到反馈并自我修正（§3.6 客观反馈信号）。
- **失败预算防盲目重试**：同类工具连续失败达到 `failure_budget`（默认 3）
  停止并汇总报告，避免死循环烧 token（§3.6 边界条件、US-1 验收）。

---

## 7. 工具集与注册表（tools / registry）

### 组件文件

- `harness/registry.py`：`Tool`、`ToolResult`、`Context`、`make_registry()`、
  `build_request_tools()`、`validate_args()`（手写轻量 schema 校验）、
  `REGISTRY`（内置 11 个工具声明）。
- `harness/tools/`：`bash.py`、`files.py`、`search.py`、`web.py`、`notes.py`、
  `memory.py`、`skills.py`、`subagent.py`、`ask.py`。

### 测试文件

- `harness/tests/test_registry.py`：注册表构建、schema 校验（缺字段/类型错/
  越界/工作区外路径）。
- `harness/tests/test_tools_*.py`：各工具 handler（bash 捕获、文件读写、
  glob/grep、模拟 fetch_url、notes、记忆、技能、子智能体、ask）。

### 验证的理论 / 设计假设

- **动作即工具调用**：agent 对世界的一切干预都通过工具完成，全部走同一条
  护栏→执行→反馈流水线（§3.2、§11.2）。
- **类型之家集中在 registry.py**（实现偏差 1）：`Context` / `Tool` /
  `ToolResult` 定义于 `registry.py`（`AgentResult` 在 `agent.py`），无独立
  `types.py`——注册表是"工具描述、校验、类型"的统一入口。
- **手写轻量 schema 校验**（实现偏差 3）：`validate_args` 覆盖类型、必填、
  最小/最大值、maxLength/maxItems、`x-workspace-path` 路径包含性，不引入
  `jsonschema` 依赖（§3.2 边界条件"非法参数 100% 被拒"）。

---

## 8. MCP 与子智能体（mcp / subagent / skills）

### 组件文件

- `harness/mcp.py`：`MCPServer`（stdio 子进程 / url HTTP 两种通道）、
  `load_mcp_servers()`（会话启动时列出并动态注册工具，与内置工具同流水线）。
- `harness/tools/subagent.py`：`run_subagent` 工具（独立上下文、独立步数
  上限，继承护栏/钩子/策略）。
- `harness/tools/skills.py`：`list_skills` / `load_skill`（读取
  `skills/<name>/SKILL.md`，`## Guardrails` 声明规则仅收紧）。

### 测试文件

- `harness/tests/test_mcp.py`：假 stdio 服务器子进程——列出/注册/schema
  透传/调用转发；连接失败优雅停用、其余服务器不受影响。
- `harness/tests/test_tools_subagent.py`：父/子上下文隔离、子任务返回最终
  答案、超限报错。
- `harness/tests/test_tools_skills.py`：allow 声明被拒绝并警告、规则注入
  策略、非法技能名拒绝。
- `harness/tests/fixtures/fake_mcp_server.py`：测试用假 MCP 服务器。

### 验证的理论 / 设计假设

- **MCP 手写行式 JSON-RPC**（实现偏差 2）：非官方 `mcp` SDK（依赖已安装但
  未使用），手写 JSON-RPC 2.0 逐行协议（stdio）/HTTP（url）——零网络依赖、
  可确定性测试；连接失败/超时该服务器优雅停用，不阻塞其余（§4.3、§3.5）。
- **MCP 工具与内置工具同流水线**：动态注册的工具同样受护栏管辖
  （`requires_approval=True`，§3.5、§11.2"未知 MCP 工具"场景）。
- **子智能体隔离与继承**：子上下文互不污染、步数上限独立（继承
  `max_steps`）、护栏/钩子/策略继承（US-7 验收）。
- **技能只能收紧**：技能声明的 allow 被拒绝并警告，违规部分丢弃（US-6
  验收、§3.4 边界条件）。

---

## 9. 支撑组件（hooks / transcript / credentials / config / llm / main）

### 组件文件

- `harness/hooks.py`：`HookBus`（pre/post/session_end，异常仅记录不致命）。
- `harness/transcript.py`：转录写入 `transcripts/<时间戳>.json`（消息、
  工具调用、策略变化）。
- `harness/credentials.py`：`CredentialStore`（keyring 优先 → `.env`/环境
  变量回退）、`wizard_enter_key()`（getpass 隐藏输入）。
- `harness/config.py`：`Config` dataclass + `Config.load()`（TOML，tomllib）。
- `harness/llm.py`：`OpenAILLM`（流式、限流退避一次、错误分类 Auth/RateLimit/
  Network）。
- `harness/main.py`：REPL 组装与命令分发（命令表见 README）。
- `harness/fake_llm.py`：测试用假客户端（无网络）。

### 测试文件

- `harness/tests/test_hooks.py`：钩子顺序（guardrail→pre→tool→post）、
  钩子异常不致命。
- `harness/tests/test_credentials.py`：来源优先级、状态不回显明文、keyring
  不可用时行为。
- `harness/tests/test_config.py`：默认值、TOML 覆盖、mcp_servers 解析。
- `harness/tests/test_llm.py`：流式聚合、错误分类。
- `harness/tests/test_repl.py`：命令分发、首次输入即任务、Ctrl+C 行为。
- `harness/tests/test_security_scan.py`：key 不出现在源码、git 历史、日志、
  转录、测试夹具（§4.2 凭据扫描）。
- `harness/tests/test_perf_smoke.py`：启动与检索性能（§4.1）。

### 验证的理论 / 设计假设

- **钩子只观察、不改变安全结果**：PreToolUse 可修改参数但 deny 已在钩子前
  返回；钩子异常仅记日志，绝不致命（§3.4 错误处理）。
- **凭据来源优先级与明文风险**：keyring（系统加密）→ `.env`（本地明文、
  进程环境可见、已被 .gitignore 排除）；`/key status` 只回显状态绝不回显
  明文（§4.2、§7.1）。
- **转录可审计**：SessionEnd 默认写转录，含消息/工具调用/策略变化，可作为
  会话审计与反馈闭环的观察数据（§4.4）。
- **REPL 无状态漂移**：命令行为与 README 命令表由 `test_docs.py` 约束一致。

---

## 10. 验收矩阵与安全（acceptance / security / perf）

### 组件文件

- 无独立生产组件；由上述所有组件的组合行为验证。

### 测试文件

- `harness/tests/test_acceptance_matrix.py`：§9 验收标准逐条映射
  （3.1 LLM 解析、3.2 工具与 schema、3.3 上下文工程、3.4 护栏顺序、
  3.5 子智能体/技能/MCP、3.6 反馈预算、4.x 转录/凭据/性能）。
- `harness/tests/test_mechanism_demo.py`：驱动 `mechanism_demo/` 三个演示脚本。
- `harness/tests/test_docs.py`：README 命令表与 `main.py` 实现一致、
  安全/沙箱说明存在。

### 验证的理论 / 设计假设

- **可度量的验收**：每条 §9 验收标准都有客观、可断言的测试对应，假 LLM
  客户端下零网络、确定性运行（§9 前言）。
- **文档与实现不漂移**：`test_docs.py` 把 README 命令表钉在 `main.py`
  `/help` 文本与实际命令上，防止文档在实现变更后失真（T27 目标）。
