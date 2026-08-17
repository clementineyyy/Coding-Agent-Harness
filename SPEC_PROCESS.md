# SPEC_PROCESS.md — 交付物 3：与 Superpowers 协作生成 spec 与 plan 的过程记录

> 本文档记录本项目使用 opencode + Superpowers 插件（brainstorming / writing-plans / systematic-debugging 等技能）协作产出设计规格（spec）与实施计划（PLAN.md）的全过程。

---

## 1. Brainstorming 关键节点

### 1.1 智能体追问了哪些好问题

| # | 问题 | 你的回答 / 最终结论 | 是否修正了原设想 |
|---|---|---|---|
| Q1 | 这个项目是驾驭agent，评估agent性能还是多个agent的统一接口 |驾驭agent (harness) | 否，但是让我更明确了coding实现的具体内容和目标 |
| Q2 |这个项目是"产品"还是"验证理论的载体"？ |  验证理论的载体| 否，但进一步明确了coding实现的具体内容和目标 |
| Q3 | agent需要拥有哪些工具tools？ | 命令行运行、读写文件、文件/网络搜索 | 否，但是问题在于除了user明确回答的tools，智能体未主动追加生产力类工具（如构建/测试封装），工具范围仍主要取决于用户 |
| Q4 | Sandbox. How should the agent's environment be isolated?|Pluggable executors — a Sandbox interface with two backends: local (direct subprocess, no isolation — for convenience) and docker (full isolation). Tool registry picks per-tool. | 是，最终落地：单一 Sandbox 接口，local 默认、docker部署；文件工具不走沙箱（路径包含性检查） |
| Q5 | Skills hooks — should skills (SKILL.md files) also be able to register hooks/guardrail rules? (Superpowers-style skills are mostly prompts; deep integration = skills can declare hooks: and rules: in frontmatter). Yes / no? | yes to skill hooks/guardrails, but they're sandboxed to restrict-only — the model can't talk its way into more power, only into more caution. Risk stays in your control. | 是 |
| Q6 | LLM 密钥如何管理（凭据威胁模型）？ | keyring + 铁律（不进 git/日志） | 否 |
| Q7 | HITL 状态机是否缺少"执行中"状态？ | 补 executing 态 + tool_requested/tool_finished 转移 | 是 |

### 1.2 哪些追问让你修正了原设想

- 原设想：Sandbox使用virtual environment的方式实现 → 修正为：沙箱方案改为 local 子进程 + docker 桩（venv 只隔离 Python 依赖、不隔离命令，无法承担沙箱职责）；整体安全模型为护栏先拦、HITL 兜底、网络默认关。原因：用"护栏优先、沙箱留桩"，把安全验证重心放在最难也最有理论价值的策略层，而不是环境隔离层
- 原设想：skills register hooks/guardrail rules → 修正为：yes to skill hooks/guardrails, but they're sandboxed to restrict-only。原因：加强安全性策略，不允许skill越界执行
- 原设想：HITL状态机规则&状态不够完善 → 修正为：补 executing 态 + tool_requested/tool_finished 转移。原因：补足HITL状态机闭环漏洞
- 原设想：docker 后端留桩（本机未装 Docker）→ 修正为：本机安装 Docker Desktop 后，docker 后端升级为真实实现（`docker run --rm --network=none -v workspace:/workspace`），沙箱从"留桩"变为"可用"。原因：真沙箱需要 OS 级隔离，LocalSandbox 对文件系统/网络/凭据三面均无隔离；升级后"护栏先拦 + Docker 隔离"纵深防御成立。
---

## 2. 关键迭代（≥3 轮：对话节选 + 你的处理决策）

> 每轮按统一格式填写：**背景 → 对话节选（引用对话原文）→ 你的处理决策 → 结果/提交**。

### 迭代 1：添加钩子与护栏并明确具体实现

- 背景：harness方法已初步确定，正在设计具体功能
- 对话节选：
  > **assistant**: 
  > ## Section 2 : The agent loop & data flow
  >`agent.py` holds one class, `Agent`, with a visible while-loop:
  > 1. **Build request** — messages list (`system` prompt + conversation history) plus `tools=` schemas from the registry
  > 2. **Call DeepSeek** — `client.chat.completions.create(..., stream=True)`, relay streamed text to the terminal
  > 3. **Inspect the turn** — if the model produced no `tool_calls`, it's the final answer → return it, loop ends
  > 4. **Execute tools** — for each `tool_call`: validate args, run handler, collect result. Print a line like `→ bash: ls -la` as it happens
  > 5. **Feed back** — append assistant message + `role: "tool"` results, loop back to step 1
  > Guardrails:
  > - **Step cap** (default 50) — kills runaway loops with a clear message
  > - **Tool timeout** — bash commands get a timeout (e.g., 30s)
  > - **History kept in memory** — one `list[dict]` of messages, the only state
  > System prompt (in `config.py` or a constant): "You are a coding agent working in `<cwd>`. Use tools to inspect and modify files, run commands, and fetch info. Answer when done."
  > DeepSeek's `deepseek-chat` supports tool calling; the wrapper in `llm.py` is thin — it just sets base_url, api_key, model so the SDK points at DeepSeek.
  > Data flow in one sentence: *user task → messages → model → tool calls → handlers → results appended → model → ... → final answer.*
  > Does the loop design look right?

  > **user**: hooks(PreToolUse, PostToolUse, SessionEnd) & guardrails and subagents & skills are needed

  > **assistant**: Scope grows — still one coherent harness, these all hang off the core loop. Design additions:
  > ## Section 3: Hooks & guardrails
  > **Hooks** (`hooks.py`) — a tiny pub/sub event bus the loop fires; user registers Python callbacks in `hooks.py` (or a `hook` dict in config):
  > - `PreToolUse(name, args)` → may **modify args**, **deny** (block + reason), or allow. Runs before every tool call.
  > - `PostToolUse(name, args, result)` → observe/record (e.g., logging, stats).
  > - `SessionEnd(messages)` → runs after final answer (e.g., save transcript, summary).
  > Loop changes: in step 4 (execute tools), each call first passes through `PreToolUse`; if denied, the model gets the denial as the tool result. After the loop ends, `SessionEnd` fires.
  > **Guardrails** (`guardrails.py`) — a rules table evaluated *inside* `PreToolUse`: `tool-pattern → allow | ask | deny`. Rules are ordered, last match wins (like opencode). Defaults: deny `rm -rf *`-class dangerous bash, deny writes outside the workspace; `ask` prompts you in the REPL (y/n). Easy to override per-session.
  > ## Section 4: Subagents
  > One new tool, `run_subagent(task, system_prompt?)` — but its implementation is elegant: **it recursively uses the same Agent class** with a fresh context.
  > - Child = new `Agent` (own messages list, own step cap ~30, same tool registry, inherits guardrails/hooks)
  > - The child's final answer is returned to the parent as the tool result
  > - Parent keeps its own conversation untouched — isolation is free since each Agent holds its own messages
  > This means subagents cost ~zero new machinery; they're the loop calling itself.
  > ## Section 5: Skills
  > Directory convention, like superpowers: `skills/<name>/SKILL.md` (frontmatter: name, description).
  > Two tools: `list_skills` → shows descriptions; `load_skill(name)` → reads the file, injects it into context as a system message. The model decides when to load one. Loading = scan `skills/`, read SKILL.md, append to messages — the loop already handles the rest.
  > Does this match what you envisioned for hooks, guardrails, subagents, and skills?

  > **user**: No, Guardrails is before hooks. So do guardrail first to stop dangerous actions (turn to human-in-the-loop), then triggers PreToolUse

  > **assistant**: Got it — guardrails gate first, hooks are downstream observers:
  > ## Section 3 (revised): Guardrails → Hooks pipeline
  > Per tool call, the loop runs this pipeline:
  > ```
  > guardrail check → PreToolUse hook → execute tool → PostToolUse hook
  > ```
  > **Guardrails** (`guardrails.py`) — first gate, hard safety:
  > - Ordered rules table: `tool-pattern → allow | ask | deny`, last match wins
  > - Defaults: deny dangerous bash (`rm -rf`, `:(){ :|:& };:`, etc.), deny writes outside workspace
  > - **`ask` = human-in-the-loop**: REPL prompts y/n before the call proceeds; deny stops it cold
  > - Result of the gate (allow/ask-approved/denied) is passed forward
  > **Hooks** (`hooks.py`) — run *after* the guardrail passes, only for approved calls:
  > - `PreToolUse(name, args)` → observe or modify args (can't resurrect a denied call)
  > - `PostToolUse(name, args, result)` → observe/record
  > - `SessionEnd(messages)` → after final answer
  > So guardrails are the security boundary; hooks are your instrumentation on top. Does this ordering look right now?

  > **user**: yep

- 处理决策：我同意了大致的agent工作流，但是在此基础上添加了钩子和护栏的部分以此保障安全、扩展和协作的部分提升表现，并要求在每次工具调用之前先用guardrail检查策略，把危险动作先拦下来，转Human-In-The-Loop；然后在执行动作前触发hooks

- 结果：钩子和护栏功能初稿成型，harness工作流得到完善，深入治理维度的设计

### 迭代 2：Sandbox隔离选项

- 背景：深入讨论安全机制的设计，需要Sandbox隔离环境
- 对话节选：
  > **user**: that looks kind of way too simple. I want to go deeper in the aspect of Hook & Guardrial. So we need sandbox to isolate environment, Human-in-the-loop state machine and etc 

  > **assistant**: Right — let's go deeper on the safety/interaction layer. A couple of questions to shape it.
  > **Question 1: Sandbox.** How should the agent's environment be isolated?
  > - **A) Docker** — bash tool runs inside a container (image with your toolchain), workspace bind-mounted in; network either on or blocked; the host is untouched. On Windows this means Docker Desktop required.
  > - **B) Pluggable executors** — a `Sandbox` interface with two backends: `local` (direct subprocess, no isolation — for convenience) and `docker` (full isolation). Tool registry picks per-tool.
  > - **C) Native OS isolation** — separate user account / restricted token / job objects on Windows. Fragile on Windows, honestly.
  > - **D) Other** — WSL, remote host, something else?

  > **user**: my personal desktop runs Windows OS, and I don't have a docker desktop. So maybe B is the best choice? or I need to install a docker desktop rn

  > **assistant**: B is the right call — and no, you don't need to install Docker Desktop right now.
  > Windows reality check on sandboxing:
  > - **Docker Desktop** — the gold standard, but requires WSL2 + install
  > - **WSL2** — you get a Linux userspace with a different filesystem namespace; decent soft isolation for free if you have a distro installed
  > - **Windows Sandbox** — real VM isolation, but clunky to automate programmatically
  > - **Job objects/restricted tokens** — partial, fragile on Windows
  > So: **pluggable `Sandbox` interface (B)**, with `local` backend shipped now (direct subprocess on the host) and a `docker` backend built against the interface but clearly marked experimental/unavailable until Docker is installed — it fails fast with a clear message. When you install Docker Desktop later, it slots in without touching anything else.
  > **Question 2: Human-in-the-loop state machine.** Beyond y/n on tool calls — should the agent be able to *proactively pause* and ask you things mid-task (unclear requirements, dangerous-looking plan, "should I delete this file?"), or is human input limited to guardrail approvals only?
- 处理决策：沙箱 local 优先 + docker 桩，文件边界用路径包含性检查
- 结果：敲定Sandbox部署方案，提升安全性

### 迭代 3：HITL 状态机设计

- 背景：承接上文assistant提问如何设计HITL状态机
- 对话节选：
  > **user**: the agent be able to proactively pause and ask you things mid-task (unclear requirements, dangerous-looking plan, "should I delete this file?"), I want the HITL state machine to be flexible and adaptive

  > **assistant**: Excellent — that's the most interesting part of the whole harness. Here's the design:
  > ## Section 3 (revised): HITL state machine + adaptive policy
  > **Explicit state machine** (`state.py`) — table-driven, events fire transitions:
  > ```
  > States:  idle → running → awaiting_user → running → completed → idle
                        ↕ (interrupt)         ↕
                        paused ←→ running     terminated (abort)
  > Events:  task_submitted | tool_requested | approval_needed | user_answered | agent_question | interrupt | resume | abort | final_answer | error
  > ```
  > - Every event has a source: **guardrail** (approval_needed), **agent** (agent_question via an `ask_user` tool), **you** (interrupt/abort), **loop** (final_answer)
  > - Transition table is a plain dict — `(state, event) → next state` — easy to read, easy to extend
  > - The `ask_user` tool is just another tool in the pipeline: agent asks a question + options → state flips to `awaiting_user` → REPL renders a numbered menu → your answer returns as the tool result → state resumes `running`. Uniform with everything else.
  > **Adaptive policy** (`policy.py`) — the "flexible" half:
  > - Session policy object holds live rules; guardrail results **feed back into it**:
  > - You answer "always allow" on an ask → that rule downgrades to `allow` for the session
  > - You deny the same pattern twice → it auto-escalates to `deny` (with a session notice)
  > - Repeated approvals of a pattern → auto-downgrade to `allow`
  > - `/rules` shows live policy at any time; policy is session-scoped by default (persistence file can come later)
  > - `ask_user` answers also record a lightweight preference (e.g., "don't delete files" → future deletes bump to ask)
  > **Sandbox + HITL interplay:** sandbox policy (which executor a tool uses, network on/off) is itself guarded — switching network on or running a container command prompts you the same way.
  > Does the state machine + adaptive policy design look right?

  > **user**: yep

- 处理决策：完善HITL状态机，确定状态、事件及转移规则；接受assistant的建议
- 结果：完成HITL状态机设计，补齐治理与安全部分的最后一块拼图

---

## 3. 哪些建议是 AI 提出而你采纳 / 推翻 / 修正的

### 3.1 AI 提出、你采纳的

| 建议 | 采纳理由 |
|---|---|
| Do you want MCP support added to the spec, or was that just part of your mental model of the sequence? | 新一轮对话中提到的MCP未出现在前面讨论的架构中，因此assistant询问是否加入MCP |
| 技能声明的护栏规则仅可收紧（allow 声明丢弃） | skill无法越过护栏红线，保障安全 |
| 凭据用 keyring + 威胁模型铁律 | 避免凭据泄露，实现key安全存储 |
| 自适应策略：双重拒绝自动升级 deny、反复批准降级 allow | 自适应安全策略make sense |
| 沙箱 local 优先 + docker 桩，文件边界用路径包含性检查 | 本机未安装Docker Desktop, for convenience and feasibility |

### 3.2 你推翻或修正 AI 的建议

| 建议 | 你如何修正 | 为什么 |
|---|---|---|
| harness工作流程混乱，context engineering的部分作为提示后添加的功能，放在最后一环 | the sequence that agent works is kind of wrong. I think the true sequence is: context engineering (memory & RAG), tools, Guardrail & Hooks, skills & MCP & subagent, so at first we should read the memory and retrieve, and at the end of the conversation, consolidate memory. So you should change the sequence in the spec | 上下文工程需要放在LLM处理之前，先Retrieve & Memory, 加到context中；本轮循环结束时还需要read_memory主动记笔记；本次对话结束时consolidate落盘记忆 |
| Guardrails (guardrails.py) — a rules table evaluated inside PreToolUse: tool-pattern → allow or ask or deny.|  No, Guardrails is before hooks. So do guardrail first to stop dangerous actions (turn to human-in-the-loop), then triggers PreToolUse| Guardrail 先行拦截（deny 直接返回、ask 转 HITL）；Hooks 只在放行后观察/修改参数，且不能复活被拒调用 |

---

## 4. 反思：brainstorming 技能在你的项目里做得好的地方与不满

### 4.1 做得好的地方

- 问题驱动收敛，先问清定位再动手，避免做错方向
- 在为user提供选项的时候考虑较全面，如Sandbox部署中可供user根据需求选择Docker或local优先的方式，在user没有考虑到所有具体部署的情况下启发user思考方案可行性
- brainstorming阶段遇到user新添加的需求，会再向user确认一次是否添加功能，有一定严谨性，确保功能完全under user control

### 4.2 让你不满 / 需要人工补足的地方

-  严格依据user提出的功能，绝不多执行额外功能，因此在初次生成的spec中缺失上下文工程的功能（显然没有context engineering并不算完整harness），需要人工提示补足缺失功能
- 在和assistant讨论修正spec时，assistant进一步提出的问题完全围绕现有功能/框架，绝不出域；限制了功能/框架的扩展/探索
- 当我提出设计的harness需要覆盖全流程的时候，assistant对于此类模糊的要求难以达到用户预期结果；需要用户明确指出harness的6个step - 决策封装、动作/工具、上下文&记忆、治理护栏、反馈闭环、配置 - 才能真正实现用户预期结果
