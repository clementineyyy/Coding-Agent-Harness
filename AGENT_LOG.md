# AGENT_LOG.md — Coding Agent Harness 实现过程日志

**范围**：2026-08-14 至 2026-08-18 的全部实现工作（规格 → 计划 → L0-L4 实现 → 真实环境验证 → 测试验收）。
**时间来源**：git commit 时间戳（`git log --format="%h %ad %s"`，均为作者提交时间，UTC+8 本地时区）。
**流程体系**：Superpowers 技能栈——brainstorming / writing-plans / using-git-worktrees / subagent-driven-development / test-driven-development / requesting-code-review / systematic-debugging / verification-before-completion / finishing-a-development-branch。
**工作模式**：每任务 = 独立 git worktree 分支 + 全新 subagent 实现（TDD 红绿）+ 两阶段评审（先规格合规、后代码质量）+ 控制器裁决 + 合入 main。
**交付物**：main 分支 29 个提交（`07ad60f` → `8f356a9`），178 个离线确定性测试全绿，CI（GitHub Actions）实测通过。

---

## Phase 0 — 规格与计划（2026-08-14 ~ 08-17）

### 规格起草与演化 — 2026-08-14 20:50 ~ 08-14 21:28
- **技能**：brainstorming（需求澄清）、writing-plans（自审）
- **提交**：`ddf0ff6`（设计规格初稿）→ `25486c0`（自审：规则模式与沙箱网络模式澄清）→ `9055e55`（译中文）→ `a141316`（+上下文工程/记忆/RAG）→ `d2f2a40`（三阶段循环重构、+MCP、修正任务结束顺序）→ `415ce48`（+动机）→ `f123dbe`（+INVEST 用户故事）
- **关键配置**：规格 6 大功能块（治理护栏/安全沙箱/记忆/上下文工程/人机协同 HITL/反馈闭环）+ MCP + 三阶段循环（收集→决策→执行）
- **人工干预**：控制器主导多轮规格重构；任务结束顺序在 `d2f2a40` 修正（钩子→转录→记忆整合）
- **教训**：规格先行、自审闭环（writing-plans 自审记录）避免后期大返工

### 规格重构与验收标准收紧 — 2026-08-15 13:22 ~ 15:58
- **技能**：writing-plans（自审 + 占位符扫描 + 类型一致性检查）
- **提交**：`2dffc0e`（重构：问题/用户故事/功能规格/非功能需求）→ `b331eb4`（+§5-11 架构/数据模型/分发/技术选型/验收/风险/钩子护栏设计）→ `28b99a1`（状态机 +executing 态）→ `78d5491`（收紧验收 3.6：注入失败后断言下一步动作改变）→ `871c2a4`（实现计划：27 任务 + 依赖图）→ `afe2409`（+§3.2 工具目录 +§3.6 客观反馈信号）→ `f1cdc2e`（PLAN 与 §3.2/§3.6 对齐）
- **关键配置**：27 任务分 L0-L4 五层；依赖图：L1 P1（T4→T5→T6→T7）∥ P2（T8→T9）∥ P3（T10）；L2 七工具并行；L3（T19→T20→T21→T22）+T23 提前；L4（T24→T25→T26→T27）
- **人工干预**：`78d5491` 收紧验收 3.6（反馈闭环必须断言"下一步动作改变"）——这是 T20/T25 两次修复轮（空洞断言）的源头
- **教训**：验收标准写得越具体，实现期返工越少；"改变下一步动作"不可写成文本回合

### 规格定稿与前置规则 — 2026-08-17 13:34 ~ 14:05
- **技能**：writing-plans（自审记录：占位符扫描、类型一致性、3 条已知实现偏差）
- **提交**：`6fa6893`（修正 SPEC.md/SPEC_PROCESS.md）→ `0de73ca`（定稿：重命名+mermaid 5.1+沙箱升级 Docker；PLAN 对齐；组件图资产）
- **关键配置**（前置裁决，全程约束）：① validate_args 在 T11 实现、T26 验证；② 注册表整合（无 harness/types.py）；③ MCP 手写行式 JSON-RPC（官方 mcp SDK 仅安装不使用）；④ 手写轻量 schema 校验（不引入 jsonschema）；⑤ 测试绝不联网、依赖仅 openai/requests/mcp/keyring/httpx+pytest；⑥ 文件 UTF-8 无 BOM/LF/末尾换行
- **教训**：开工前的"裁决清单"是后续 27 个任务的隐式上下文

---

## Phase 1 — L0 骨架（T1-T3，2026-08-17 14:33 ~ 14:56）

### T1 包骨架 — 14:33（`07ad60f`）
- **技能**：test-driven-development；subagent-driven-development（task-brief / review-package 脚本）
- **subagent 输出**："Status: DONE"；评审通过（"spec compliant"）
- **教训**：worktree-per-module 模式首秀成功（`.worktrees/feat-l0` → merge main → 清理）

### T2 凭据存储 — 14:42（`bac0060`）+ 修复 14:52（`03aba88`）
- **技能**：test-driven-development；requesting-code-review（两阶段）
- **配置/prompt**：keyring 优先、.env 回退、status 永不回显明文、拒绝空白 key
- **subagent 输出**：修复轮 "Status: DONE"（信号写失败 + 拒绝空白 key）
- **人工干预**：修复轮后重新评审通过
- **教训**：两阶段评审发现的缺陷由同一 implementer 修复并重审，形成闭环

### T3 配置加载 — 14:56（`f876856`）
- **技能**：test-driven-development
- **配置/prompt**：TOML（tomllib）、默认值表、workspace 夹具
- **教训**：控制器曾误记为 JSON——以测试（test_config.py）为准，文档任务（T27）纠偏

---

## Phase 2 — L1 核心机制（T4-T10，15:06 ~ 16:36）

### T4 状态机 — 15:06（`3e0773a`）
- **技能**：test-driven-development
- **subagent 输出**：7 状态 11 事件表驱动；非法迁移 StateError；event_history 记录
- **评审**：通过（27 行表仅断言 21 行——plan-mandated；source 未校验——留档）
- **教训**：event_history 全轨迹断言（T25 demo ③ 复用）为"确定性"提供了最强证据形式

### T5 护栏 — 15:28（`d5e5cf9`）
- **技能**：test-driven-development
- **配置/prompt**：last-match-wins；内置 4 规则（含 fork-bomb 正则 `.*:\(\)\s*\{.*:.*\};`、`rm -rf`、`C:\` 盘符写、`shutdown`）
- **评审**：通过。**控制器裁决**：guardrails.py 必须为纯函数（不 import state）——deny 事件由 agent.py 以 source=guardrail 触发
- **教训**：纯函数裁决避免了循环依赖，后续 agent 管线（T19）自然分层

### T6 自适应策略 — 16:05（`c006a2d`）+ 修复 16:18（`6e1f842`）
- **技能**：test-driven-development
- **配置/prompt**：降级/升级、技能收紧、按模式×回答类型计数（`{pattern}:{answer}`，deny≥2 降级 / allow≥3 升级）
- **subagent 输出**：修复轮 "per-type y/n adaptive counters and user-source attribution"
- **评审**：两轮通过；"user-last 排序"裁决正确（先 guardrail 后 user）
- **教训**：评审者与实现者都需验证计数语义（类型维度），否则易退化

### T7 钩子 + 转录 — 16:36（`4bd7d44`）
- **技能**：test-driven-development
- **subagent 输出**：HookBus（pre/post_tool_use/session_end）+ 默认转录钩子（`%Y-%m-%dT%H-%M-%S-%f.json`）
- **评审**：通过（Minor：同毫秒文件名覆盖——留档）
- **教训**：转录为 T22/T26 的"会话生命周期"验收提供数据基础

### T8 沙箱 — 15:12（`53abcdc`，rebase 后哈希）
- **技能**：test-driven-development
- **配置/prompt**：LocalSandbox（宿主子进程，非隔离=护栏第一道防线）+ DockerSandbox（`--rm --network=none -v ws:/workspace`）；timeout→exit -1；DockerUnavailableError
- **评审**：通过（Windows 孙进程杀——plan-mandated；Docker 未真实运行——留档）
- **人工干预**：**教训（重大）**：评审 Minor 记录"真实 Docker 未验证"——最终在 08-17 21:07 由用户质疑触发真实验证，挖出 cidfile 真 bug（见 Phase 6）

### T9 LLM 客户端 + FakeLLM — 15:50（`0a787b8`）
- **技能**：test-driven-development
- **配置/prompt**：OpenAILLM（api_key/base_url/model/http_client 可注入）；SSE 流式解析；错误映射 LLMError；FakeLLM/FakeTurn 脚本化
- **subagent 输出**：第 1、2 次派发均返回**空结果**（零工作）；第 3 次成功
- **人工干预**：控制器重派 2 次；裁决：SSE `"\n\n"` join 与 `max_retries=0` 为必要偏差；后补 pyproject httpx 依赖（`df96c2f`，openai 3.x 不再提供 httpx）
- **教训**：空结果故障模式第一次出现（共 5 次：T9×2、T11×2、T12×1）——"MANDATORY 回复"条款不根治，重派新 agent 有效；solo 派发（非批量）与成功率正相关

### T10 TF-IDF 记忆 — 15:12（`b1937ea`）
- **技能**：test-driven-development
- **配置/prompt**：中文+英文 2-gram TF-IDF；top_k=2；损坏文件跳过；top_k_chunks/warnings
- **评审**：通过（英文 2-gram 由 brief 测试强制——T15 知情；search 吞异常 plan-mandated）
- **教训**：跨任务接口（top_k_chunks）由 T15/T21 消费，接口契约在 brief 中交叉引用

### L1 合入 — 15:18 `4087bee`（.gitignore *.egg-info/）
- **人工干预**：控制器修复 `pip install -e` 产物被 git 跟踪问题

---

## Phase 3 — L2 工具集（T11-T18 + T23，16:29 ~ 17:22）

### 控制器重大纠偏：任务编号映射 — 16:29 起
- **人工干预**：派发时把 T12（files+search）误标为 bash、T13 误标为 web 等（dispatch 标签与 PLAN.md 真实映射不符）；**implementer 按 brief 内容自纠**，全部完成正确任务
- **教训**：PLAN.md 是唯一权威；dispatch 标签不可靠时，implementer 以 brief 为准自纠是最后防线

### T11 注册表 + bash — 16:29（`6336763`）与 17:10（`4535e67`）
- **技能**：test-driven-development
- **配置/prompt**：注册表整合裁决（Tool/ToolResult/Context/make_registry/validate_args/build_request_tools 全部进 harness/registry.py，**无 ToolResult.to_message**）
- **subagent 输出**：前 2 次空结果；第 3 次 "Status: DONE"
- **评审**：通过（7 Minor：workspace=None 静默跳过路径规则、`x-workspace-path` 泄漏进模型 schema 等——留档）
- **人工干预**：bash 工具（T11 第二部分）独立提交 `4535e67`（brief 拆分）
- **教训**：注册表类型合并的裁决避免了 T12-T18 七个工具的接口漂移

### T12 files+search — 17:08（`4f2a898`）
- **subagent 输出**：第 1 次空结果；重派成功
- **评审**：通过（containment 逻辑三处重复、grep 硬编码上限——留档）
- **教训**：空结果重试模式再次验证

### T13 web / T14 notes / T15 记忆工具 / T16 ask / T17 skills / T23 subagent — 16:46 ~ 16:55
- **提交**：`14d7b61`（fetch_url 网络开关门控+大小上限）/ `332c207`（notes，扩展 Tool.handler+ToolResult——裁决为共享约定）/ `ec28cee`（memory 工具，save 后重载）/ `ff60217`（ask 编号菜单→HITL）/ `bd9625d`（skills 只紧不松）/ `083e490`（run_subagent 隔离+步数上限+护栏继承）
- **评审**：全部通过
- **人工干预**：T23 提前实现（L3 任务前置到 L2 lane）——前置裁决执行
- **教训**：T14 的 handler 扩展被裁定为全局约定，T15-T23 全跟随，避免二次返工

### 依赖修复 — 17:13（`df96c2f`）
- **人工干预**：llm.py 顶层 `import httpx` 而 pyproject 未声明（openai 3.1.0 仅提供 httpx2）——新 venv 装不上依赖；补 httpx + [dev] extra
- **教训**：真实 venv 重建验证依赖声明（CI/换机必现）

### T18 MCP — 17:12（`d29b31e`）+ 修复 17:22（`326dea4`）
- **技能**：test-driven-development
- **配置/prompt**：手写行式 JSON-RPC（stdio/url），动态工具注册，失败优雅禁用
- **评审**：修复轮（stdio read-timeout 楔子：_teardown + 离线超时测试）后通过
- **教训**：子进程协议类实现必须覆盖"对端不响应"路径（真实进程 IO 阻塞）

---

## Phase 4 — L3 引擎（T19-T22，17:33 ~ 18:40）

### T19 agent 核心 — 17:33（`bea62ab`）+ 修复 17:38（`03a8d2d`）
- **技能**：test-driven-development
- **配置/prompt**：护栏优先管线（guardrail → tool_requested → pre 钩子 → handler → post 钩子 → tool_finished）；运行时注册表（真实 spec 而非静态桩）
- **评审**：1 个 Important（ask-deny 路径把状态机停在 awaiting_user → run() 未捕获 StateError 崩溃）；修复轮通过
- **人工干预**：修复后测试加入 test_agent_core.py（评审者假定的 test_agent.py 不存在）；**GBK 编码事故**：修复报告被 PowerShell 追加写成 GBK，控制器重构为 UTF-8
- **教训**：PowerShell `Add-Content` 必须显式 `-Encoding utf8`；含引号/反斜杠的行用单引号；report 文件统一 UTF-8

### T20 反馈循环 — 17:55（`dfae7c2`）
- **技能**：test-driven-development
- **配置/prompt**：连续失败预算（failure_budget=3，同工具累加/异工具重置/成功清零）；错误反馈注入（status/output/error/exit_code 进回喂消息）
- **评审**：通过。**控制器裁决**：① `failed_sequence`=峰值语义（brief 自己的测试断言 `==1` 后随成功，当前值读法会得 0——峰值是唯一一致解读）；② 预算终止走 `final_answer`（abort 从 running 非法——与步数上限一致）
- **教训**：brief 内部矛盾（接口文本 vs 测试）时以测试为可执行规格

### T21 上下文工程 — 18:09（`1302c4f`）+ 修复 18:17（`c54e626`）
- **技能**：test-driven-development
- **配置/prompt**：任务开始 top-2 记忆注入（`[memory]` system 消息）；预算 `sum(len/4) > max_budget_tokens` 触发压缩；`[summary]` 摘要+保留最近 turns；压缩轮数上限；异常→降级截断
- **评审**：1 个 Important（压缩成功路径完全无测试——plan-mandated 覆盖缺口）；修复轮 +4 测试通过
- **人工干预**：裁决 max_budget_tokens 补入 config 正当（brief 涉及文件表遗漏但接口/测试需要）
- **教训**：旗舰路径必须有断言（成功路径≠仅异常路径）

### T22 收尾（转录+记忆整合）— 18:32（`9659f6e`）+ 18:40（`43820aa`）
- **技能**：test-driven-development
- **配置/prompt**：三退出路径（final-answer/预算/步数上限）收拢 _finish→_finalize；session_end→转录→整合顺序；policy_changes 真实汇入（T19 Minor 修复）
- **评审**：通过。**控制器裁决**：hooks.py/transcript.py 越界为正当扩展（brief 测试断言默认钩子产物含 policy_changes，仅改 agent.py 无法满足）；session_data 机制可接受
- **人工干预**：控制器直接修复末尾换行（`43820aa`）——TDD 工作流外的琐碎机械修复由控制器执行
- **教训**：brief 越界文件需明确披露+裁决；mechanical whitespace 修复不必走完整 subagent 流程

---

## Phase 5 — L4 产品化（T24-T27，19:03 ~ 20:17）

### T24 REPL — 19:03（`c8f0854`）+ 修复 19:14（`ffc0b8c`）
- **技能**：test-driven-development
- **配置/prompt**：run_repl/ask_menu/斜杠命令（/exit /reset /skills /rules [/rules drop skill:] /key set|status|clear /memory）；Ctrl+C 中断菜单；on_text 流式回调；无凭证友好退出
- **评审**：1 个 Important（LLM/API 错误崩溃 REPL——违反 SPEC §3.1"会话存活"）；修复轮（except LLMError+settle_state）通过
- **人工干预**：裁决 on_text 越界正当、`Policy._skill_rules` 私有访问可接受（policy.py 无公开删除 API 且 brief 禁改）；CRLF 漂移为仓库级既有问题（留待整体处理）
- **教训**：真实用户第一行输入即任务（plan-mandated，T26 修复同源）；外部边界（API 错误）必须做存活测试

### T25 机制演示 — 19:27（`84917c8`）+ 修复 19:37（`ab08271`）
- **技能**：test-driven-development
- **配置/prompt**：demo ① 护栏拦截 `rm -rf C:\Windows`（钩子零触发+沙箱零执行+`⊘ denied`）；demo ② 失败→反思→换动作；demo ③ 状态机全轨迹精确断言
- **评审**：1 个 Important（**demo ② 空洞**：反思回合是纯文本回合 → run() 终止 → 第 3/4 回合从未执行，"下一条动作≠失败命令"断言无意义）；修复轮（反思+换动作合并为同一 FakeTurn、断言最后执行命令）通过
- **人工干预**：编码裁决——subprocess 包装必须 `encoding="utf-8", errors="replace"`（GBK 机器子进程 `⊘` 不可编码/父进程 UTF-8 不可解码）
- **教训**：FakeLLM 的"纯文本回合即终止"语义让一切"先反思再行动"脚本天然失效——必须反思+tool_calls 同回合（T26 同源修复）

### T26 验收矩阵 — 20:01（`797c96c`）
- **技能**：test-driven-development
- **配置/prompt**：§9 全部条目参数化映射（3.1-3.6、4.x）；凭据扫描（源码/git 历史/转录/夹具）；性能冒烟（启动<1s、检索<50ms）
- **subagent 输出**：RED 暴露 2 个问题（§3.6 反思回合建模、git 扫描 GBK 解码）——均测试侧修复，**未发现模块缺陷**
- **人工干预**：控制器纠偏——brief 的"registry.validate 需补"已由 T11 完成（validate_args 存在且接线），不得重复添加；brief 过时路径（harness/tools/registry.py）纠正为 harness/registry.py
- **教训**：跨任务 brief 会过时；implementer 需对照合并现实核验 brief 前提

### T27 README/文档 — 20:17（`3aaba8d`）
- **技能**：test-driven-development
- **配置/prompt**：命令表钉死 main.py 实际实现（/help 字面量断言防漂移）；COMPONENTS.md 六维度组织（组件文件/测试文件/验证的理论）
- **评审**：通过。**裁决**：文档以实际实现为准——config 是 TOML（控制器误记为 JSON）、.env 解析在 credentials.py（无 dotenv.py）；三个已知实现偏差双处记录
- **教训**：文档任务的正确性=与实现零漂移，控制器记忆不可作为文档依据

---

## Phase 6 — 真实环境验证 + 热修复（08-17 21:07）

### Docker 真实验证 — 21:07（`cc056be`）
- **技能**：systematic-debugging（四阶段）；test-driven-development（回归测试先行）
- **触发**：**用户人工干预**——"我在 Docker Desktop 上没看到你启动的容器，这也算完成了吗？"
- **过程**：控制器承认计划要求测试离线（mock subprocess），Docker 后端从未真实运行 → 真实冒烟：`docker version` OK → harness DockerSandbox.run 失败（exit 125）→ 手动 docker run 成功 → 隔离变量：差异仅在 `--cidfile` → 读实现 `sandbox.py:100`：`tempfile.mkstemp` **预创建空文件**，而 docker 要求 cidfile 不存在 → 根因确认
- **修复**：回归测试 `test_docker_cidfile_does_not_preexist`（RED 确认）→ 改 uuid 生成不存在的路径（GREEN）→ 真实 Docker 验证：执行（exit 0 输出 2）/ 挂载（/workspace/README.md）/ 超时（exit -1+容器 stop）/ daemon 事件流（create→start→die→destroy 实拍）
- **教训**：**离线 mock 测试无法验证真实外部边界**；评审 Minor 记录的"真实 Docker 未验证"应被升级为显式验证任务；用户驱动的真实环境质疑是最高价值的验收

---

## Phase 7 — 测试验收（T28，08-18 12:49）

### T28 一键测试 + CI + 证据 — 12:49（`8f356a9`）
- **技能**：subagent-driven-development；test-driven-development；verification-before-completion
- **配置/prompt**：Makefile（`make test` 一键：venv 自动建+安装+全套；`make demo`；`$(OS)` 双平台分支）；ci.yml（push+pull_request；test job ubuntu/Python 3.11；build job `python -m build`+upload-artifact）；pyproject `[build-system]`；README（CI badge+机制演示 §A.4-D 对齐+离线确定性清单）；2 个漂移测试
- **subagent 输出**：评审第 1 次派发返回**空结果**——重派（含强制回复条款）成功，评审通过
- **真实验证**：`mingw32-make test` exit 0；push 后 GitHub Actions 实测：`test -> success`、`build -> success`、`dist` 产物 128,362 bytes（GitHub API 核验，本机无 gh CLI）
- **人工干预**：wheel 完整性风险检查（所有子包均有 __init__.py，setuptools 自动发现不会丢包）
- **教训**：CI 的"真的在跑"要用 API/页面证据核验，不能只信本地绿；评审空结果同样可重派

---

## 附录 A — 人工干预清单（控制器/用户）

| # | 干预 | 原因 |
|---|------|------|
| 1 | L2 dispatch 编号纠偏 | 派发标签与 PLAN.md 映射不符；implementer 按 brief 自纠 |
| 2 | 空结果重派 ×5（T9×2/T11×2/T12×1） | subagent 返回空结果零工作 |
| 3 | T6 修复轮 | 按类型计数 + user-last 排序裁决 |
| 4 | SSE join / max_retries=0 裁决 | T9 必要偏差 |
| 5 | GBK 报告重构 UTF-8 | PowerShell Add-Content 编码事故 |
| 6 | 测试文件路径纠偏 | reviewer 假定的 test_agent.py 不存在 |
| 7 | T20 峰值语义/终止事件裁决 | brief 文本与测试矛盾 |
| 8 | T21 补测试修复轮 | 压缩成功路径 plan-mandated 覆盖缺口 |
| 9 | T22 越界文件/session_data 裁决 | brief 测试要求默认钩子产物 |
| 10 | T24 LLMError 崩溃修复轮 | SPEC §3.1 会话存活 |
| 11 | T25 demo ② 空洞断言修复轮 | 反思回合终止 run() |
| 12 | T26 validate_args 纠偏 | brief 过时前提 |
| 13 | T27 文档以实现为准 | 控制器记忆（JSON）错误 |
| 14 | 尾部换行直接修复（43820aa） | 机械琐碎修复不走 subagent |
| 15 | **用户质疑 Docker 未真实运行** | 触发真实验证 → cidfile 真 bug 修复 |
| 16 | **用户确认全 mock 运行** | 声明真实 LLM 链路未验证边界 |
| 17 | 用户要求 AGENT_LOG.md | 本日志的缘起 |

## 附录 B — 经验教训汇总

1. **离线测试的边界**：mock 一切外部资源时，"真实外部边界"（Docker、LLM API）必须显式列入验证清单——T8 的 Docker 直到用户质疑才真实验证，挖出 mkstemp/cidfile 真 bug。
2. **空结果故障模式**（5 次）：重派新 agent 有效；强制回复条款不根治；solo 派发更稳；验收后核对 `git log` 与报告文件存在性。
3. **编码纪律**：Windows + PowerShell 环境下，UTF-8 无 BOM/LF/末尾换行需要显式执行；GBK 事故与子进程 GBK 解码问题各发生一次，均以 `encoding="utf-8", errors="replace"` 与 `-Encoding utf8` 收场。
4. **brief 权威性**：PLAN.md/brief 是唯一权威；控制器记忆（JSON/TOML、dotenv.py、registry.validate）多次不可靠——implementer 以代码与测试为准自纠。
5. **裁决留痕**：每个语义歧义（峰值/终止事件/越界文件/私有访问）都要显式裁决并写入账本，避免评审者重复质疑。
6. **空洞断言陷阱**：FakeLLM 纯文本回合即终止——"反思→行动"脚本必须同回合携带 tool_calls；验收 3.6 的收紧（78d5491）正是为此。
7. **两阶段评审的价值**：评审者发现 implementer 自我验证盲区（T21 成功路径、T24 会话存活、T25 空洞断言）——TDD 红绿不覆盖"没写测试的行为"。
8. **真实 CI 证据**：push 后 CI 自动跑并通过（test+build+artifacts）——"真的在跑"用 API/日志核验。

## 附录 C — 未验证边界（如实声明）

- **真实 LLM API 链路**（OpenAILLM → api.deepseek.com：SSE 线格式、tool_calls 字段、限流/错误响应）仅对合成 payload 做单元测试，**从未以真实 key 端到端运行**。待用户提供 key 后执行 REPL/一次性脚本验证。
- POSIX 分支的 `make` 未在本机执行（无 make），已由 CI ubuntu 首跑覆盖。

## Phase 8 — 真实 LLM 验证与 PyPI 发布（2026-08-18）

### 8.1 真实 LLM 端到端验证（用户硅基流动 Key）

- `scripts/verify_live_llm.py`（74e5c54 加入，53fdd2b 修正 tool_calls 断言）：
  `--base-url https://api.siliconflow.cn/v1 --model deepseek-ai/DeepSeek-V3`
- 结果：连接 + SSE 文本回合 OK；tool_calls 映射为 harness 形状；全管线任务 → bash 工具执行 → final_answer；
  EVENTS 序列 task_submitted→tool_requested→tool_finished→final_answer；均 exit 0。附录 C 首项由此闭环。

### 8.2 SPEC §7 合规审计与缺口补齐（b992bfd）

- 审计结论：keyring 存储、.env 加载、getpass 向导、/key status 无明文、兜底安全均达标；三缺口：
  1. console script `cah`（§7.2 明示"提供 console script（如 cah）作为入口命令"）— 缺失
  2. 密钥"可选验证"（§7.1：调 `{base_url}/models` 轻量确认，通过才落盘并记录 verified_at；失败提示重输不落盘）— 缺失
  3. `/key clear` 环境来源提示"请手动从 .env 删除"（§7.1）— 缺失
- 补齐（TDD 红→绿；新增 verify_api_key×3 / mark_verified / REPL 验证失败不落盘 / 验证成功落盘+标记 / env 来源提示 / cah 漂移测试，186 测试全绿）：
  - credentials.py：`verify_api_key()`（httpx，可注入 client 保离线测试）、`CredentialStore.mark_verified()`
  - main.py：`_enter_key_flow()`（≤3 次尝试、可选验证），`_first_run_wizard` 与 `/key set` 共用；`/key clear` 按来源分流
  - README：cah 运行命令、来源措辞修正（keyring → .env 文件 → 向导）、可选验证说明
- 用户裁决：补齐三项。

### 8.3 PyPI 发布 v0.1.0 / v0.1.1

- v0.1.0（148296e）：Trusted Publishing（OIDC 免 token，环境 pypi）发布 nju-coding-agent-harness（原名已被他人占用）；
  干净 venv 安装 + 核心模块导入验证通过。
- v0.1.1（b6c9ed4）：首次 tag v0.1.1 时 pyproject 版本未同步（仍 0.1.0）→ 产物重复上传被 PyPI 拒绝（build 成功、publish 失败，
  日志接口需 admin 权限，经版本号比对定位）→ **教训：tag 与 pyproject 版本必须同一 commit 同步**；修复 = 升版本 → 删旧 tag
  → 重建 → 重推。
- 干净环境验证：pip install nju-coding-agent-harness（注意 pip 索引缓存曾致误装 0.1.0，加 --no-cache-dir 后正确）→ 0.1.1 +
  cah 入口点；`cah` 冒烟：无 key 时进向导、空行 EOF 干净退出 exit 0。

### 8.4 环境事件

- GitHub HTTPS 短暂被阻断（TLS 握手失败、ICMP 通、pypi 可达）→ 用户开启代理后恢复；push/tag 未受影响重推成功。