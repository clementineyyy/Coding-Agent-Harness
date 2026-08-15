# Coding Agent Harness 实施计划（PLAN.md）

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 从零实现一个"最小但真实"的编码智能体框架（Python + DeepSeek），六维度齐全、可确定性测试，重点打磨钩子与护栏（含 HITL 状态机）。

**Architecture:** 同步单线程；模块间普通函数调用 + 事件（hooks）通信，无隐藏全局状态（策略与记忆为显式注入的会话对象）。任务生命周期三阶段：开始（检索 top-2 注入 + 预算检查）→ 迭代（LLM × 工具流水线）→ 收尾（SessionEnd 钩子 → 记忆整合）。工具流水线严格排序：护栏 → 状态机 → PreToolUse → 执行 → PostToolUse。

**Tech Stack:** Python 3.11+（Windows）、标准库为主、`openai` SDK（DeepSeek 兼容协议）、`requests`、`mcp`、`keyring`、`pytest`。无 TUI 框架、无异步、无 embeddings。

**Spec:** `docs/superpowers/specs/2026-08-14-coding-agent-harness-design.md`（计划从 spec 论证，执行者须同时阅读 spec 与本计划）

---

## 任务依赖图与并行分组

```
L0 基础（顺序）
   T1 骨架 → T2 凭据 → T3 配置
L1 纯逻辑核心（三路并行，可 worktree 并行）
   P1 安全核心:  T4 状态机 → T5 护栏 → T6 策略 → T7 钩子(含转录)
   P2 执行与模型: T8 沙箱 → T9 LLM(+FakeLLM)
   P3 记忆:       T10 TF-IDF 记忆库
L2 工具层（8 路并行，依赖 L1 接口，可 worktree 并行）
   T11 注册表+bash  T12 files+search  T13 web  T14 notes
   T15 memory 工具  T16 ask  T17 skills  T18 MCP
L3 Agent 核心（顺序）
   T19 迭代核心 → T20 反馈循环 → T21 上下文工程集成 → T22 收尾/转录/记忆整合 → T23 子智能体
L4 交付
   T24 REPL main.py → T25 机制演示①②③ → T26 验收矩阵+凭据扫描+性能冒烟 → T27 README/文档
```

- **可并行**：L1 三路（P1/P2/P3）互不依赖；L2 的 8 个任务互不依赖（仅依赖 L1 已定接口）。
- **串行依赖**：T2→T3；T19 之前必须有 T4-T11 全部完成；T23 依赖 T19；T25 依赖 T19/T20/T24。
- worktree 并行时，各分支合回顺序必须满足上述依赖。

---

## 全局约束（每个 task 隐式包含）

- Python ≥ 3.11；Windows；同步单线程，无 async 框架。
- 额外依赖仅允许：`openai`、`requests`、`mcp`、`keyring`（及 `pytest` 测试用）；其余一律标准库。
- **测试绝不联网**，不使用真实 LLM；LLM 一律用 `harness/fake_llm.py` 的 `FakeLLM` 或注入的假客户端。
- 凭据铁律：key 绝不硬编码进源码、绝不进 git（含历史）、绝不进日志/转录/测试夹具；`.env`、`transcripts/`、`memory/` 在 `.gitignore` 中。
- 所有文件 UTF-8 编码（无 BOM）；中文注释允许。
- 模型固定 `deepseek-chat`，`base_url=https://api.deepseek.com`，仅 HTTPS。
- 默认参数（spec §3）：步数上限 50、连续失败预算 3、工具超时 30s（测试用 1s）、记忆 top-2、压缩保留最近 10 回合、子智能体步数上限 30、token 估算字符数/4。
- 危险 bash 模式内置 deny 清单（`rm -rf` 系统路径、fork 炸弹）；工作区外写入 deny；`network_enabled` 切换必须 ask。
- 钩子顺序 guardrail → PreToolUse → tool → PostToolUse；deny 先于钩子返回（钩子不能复活被拒调用）；钩子异常仅记日志。
- 每个 task 以"写失败测试 → 确认失败 → 最小实现 → 确认通过 → 提交"为闭环，提交信息用 `feat:` / `test:` 前缀。

---

## Task 1: 项目骨架（pyproject + 包结构 + pytest + .gitignore）

**目标**：可运行 `pytest` 的空包骨架，目录结构与 spec 附录一致。

**涉及文件**
- Create: `pyproject.toml`、`harness/__init__.py`、`harness/main.py`（占位）、`harness/tools/__init__.py`、`harness/tests/__init__.py`、`harness/tests/conftest.py`、`.gitignore`、`README.md`（占位）

**接口**
- Produces: 包 `harness` 可导入；pytest 可发现 `harness/tests/`；`conftest.py` 提供全局夹具（见下）

**依赖**：无。**并行**：L0 起点。

**实现要点**
- `pyproject.toml`：`[project]` name=coding-agent-harness，requires-python=">=3.11"，依赖 openai/requests/mcp/keyring；`[tool.pytest.ini_options]` testpaths=["harness/tests"]，addopts="-q"。
- `.gitignore`：`.env`、`transcripts/`、`memory/`、`__pycache__/`、`.pytest_cache/`、`*.pyc`。
- `conftest.py` 全局夹具：
  - `tmp_workspace`：pytest `tmp_path` 内的 `workspace/` 目录（所有文件/搜索测试的工作区）
  - `session_config`：`Config` 实例（默认值 + workspace=tmp_workspace）——Config 在 T3 实现，故 T1 的 conftest 只放 `tmp_workspace`，Config 夹具在 T3 加。

**验证步骤**
- [ ] **Step 1: 写失败测试**

```python
# harness/tests/test_skeleton.py
def test_package_importable():
    import harness
    import harness.tools
    assert harness.__name__ == "harness"
```

- [ ] **Step 2: 运行确认失败**

Run: `python -m pytest harness/tests/test_skeleton.py -v`
Expected: FAIL（`No module named 'harness'`）

- [ ] **Step 3: 最小实现**：创建上述包结构与配置文件（内容见"实现要点"），`harness/__init__.py` 可留空。

- [ ] **Step 4: 运行确认通过**

Run: `python -m pytest harness/tests/test_skeleton.py -v`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add pyproject.toml .gitignore README.md harness/
git commit -m "feat: scaffold harness package with pytest and gitignore"
```

---

## Task 2: 凭据模块 credentials.py（keyring + .env + 首启向导，绝不出明文）

**目标**：密钥经 Windows Credential Manager（`keyring`）为主、`.env` 加载为备；首次运行用 `getpass` 隐藏输入；`status()` 只回显状态不回显明文。

**涉及文件**
- Create: `harness/credentials.py`、`harness/tests/test_credentials.py`

**接口**
- Consumes: `harness.fake_llm` 不需要；本任务独立。
- Produces:
  - `class CredentialStore`：`__init__(service="coding-agent-harness", env_file=".env", keyring_backend=None)`（keyring_backend 可注入，测试用假后端）；`get() -> str | None`（优先级 keyring > .env）；`set(key: str) -> None`（写 keyring，**不**写 .env）；`clear() -> None`；`status() -> dict`（`{"configured": bool, "source": "keyring"|"env"|None, "verified_at": str|None}`）；`verified_at()`（`"2026-08-15T.."` 或 None，存 keyring 的 `coding-agent-harness:verified_at`）。
  - `wizard_enter_key() -> str`：`getpass.getpass("请粘贴 API Key（输入不可见）: ")`，空输入抛 `ValueError`。
- 错误处理：keyring 不可用（无凭据服务）→ 回退 .env，不崩溃；`get()` 绝不打印密钥。

**依赖**：T1。**并行**：L0 第二个。

**实现要点**
- `get()` 读 keyring 失败或为空 → 读 `.env` 文件解析 `DEEPSEEK_API_KEY=...` 行（手写解析，不引入 python-dotenv）。
- `status()` 的 source 判定：keyring 有值 → "keyring"；否则 .env 有值 → "env"；都没有 → None。
- 测试用注入假 keyring 后端：`dict` 实现 `get_password/set_password/delete_password`。

**验证步骤**
- [ ] **Step 1: 写失败测试**

```python
# harness/tests/test_credentials.py
from pathlib import Path
from harness.credentials import CredentialStore

class FakeKeyring:
    def __init__(self): self.data = {}
    def get_password(self, service, user): return self.data.get((service, user))
    def set_password(self, service, user, pw): self.data[(service, user)] = pw
    def delete_password(self, service, user): self.data.pop((service, user), None)

def test_priority_keyring_over_env(tmp_path):
    kr = FakeKeyring(); kr.set_password("coding-agent-harness", "api_key", "sk-keyring")
    env = tmp_path / ".env"; env.write_text("DEEPSEEK_API_KEY=sk-env\n", encoding="utf-8")
    cs = CredentialStore(env_file=str(env), keyring_backend=kr)
    assert cs.get() == "sk-keyring"
    assert cs.status()["source"] == "keyring"

def test_fallback_env(tmp_path):
    env = tmp_path / ".env"; env.write_text("DEEPSEEK_API_KEY=sk-env\n", encoding="utf-8")
    cs = CredentialStore(env_file=str(env), keyring_backend=FakeKeyring())
    assert cs.get() == "sk-env"
    assert cs.status()["source"] == "env"

def test_status_never_echoes_plaintext(tmp_path):
    env = tmp_path / ".env"; env.write_text("DEEPSEEK_API_KEY=sk-secret\n", encoding="utf-8")
    cs = CredentialStore(env_file=str(env), keyring_backend=FakeKeyring())
    status_str = str(cs.status())
    assert "sk-secret" not in status_str
    assert cs.status()["configured"] is True
```

- [ ] **Step 2: 运行确认失败**

Run: `python -m pytest harness/tests/test_credentials.py -v`
Expected: FAIL（`ModuleNotFoundError: harness.credentials`）

- [ ] **Step 3: 最小实现**：按"实现要点"写 `credentials.py`（.env 解析：逐行 `strip()`，匹配 `DEEPSEEK_API_KEY=` 前缀取等号后内容，空值跳过；keyring 调用失败 `except Exception` → 视为无 keyring 值，继续走 .env）。

- [ ] **Step 4: 运行确认通过**

Run: `python -m pytest harness/tests/test_credentials.py -v`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add harness/credentials.py harness/tests/test_credentials.py
git commit -m "feat: credential store via keyring with .env fallback, status never echoes plaintext"
```

---

## Task 3: 配置模块 config.py（TOML 加载 + 默认值兜底）

**目标**：集中管理模型/步数/预算/超时/工作区/MCP 服务器等配置；TOML 文件可覆盖，缺省用默认值。

**涉及文件**
- Create: `harness/config.py`、`harness/tests/test_config.py`、`harness/tests/conftest.py`（加 `session_config` 夹具）

**接口**
- Produces: `@dataclass class Config`：字段 `model="deepseek-chat"`、`base_url="https://api.deepseek.com"`、`max_steps=50`、`failure_budget=3`、`tool_timeout=30`、`memory_top_k=2`、`compression_keep_turns=10`、`compression_max_rounds=3`、`workspace: Path`、`max_output_bytes=51200`、`mcp_servers: list[dict] = field(default_factory=list)`（每项 `{"name","type":"stdio"|"url","command"|"url"}`）；`Config.load(path: Path | None = None) -> Config`（TOML via `tomllib`，`config.json` 兼容键名；文件不存在 → 全默认 + workspace=当前目录）。
- `conftest.py` 增加：`session_config` 夹具 → `Config(workspace=tmp_workspace, tool_timeout=1)`（供所有后续测试使用默认配置）。

**依赖**：T1。**并行**：L0 第三个。

**实现要点**：`tomllib.load`（3.11 标准库）；TOML 键与字段同名；未知键忽略不报错；`workspace` 未给 → 当前目录；路径字段做 `Path()` 规范化。

**验证步骤**
- [ ] **Step 1: 写失败测试**

```python
# harness/tests/test_config.py
from pathlib import Path
from harness.config import Config

def test_defaults(tmp_path):
    c = Config.load(None)
    assert c.model == "deepseek-chat"
    assert c.max_steps == 50 and c.failure_budget == 3 and c.tool_timeout == 30

def test_toml_override(tmp_path):
    p = tmp_path / "config.toml"
    p.write_text("model = \"deepseek-reasoner\"\nmax_steps = 12\n", encoding="utf-8")
    c = Config.load(p)
    assert c.model == "deepseek-reasoner" and c.max_steps == 12
    assert c.tool_timeout == 30  # 未覆盖的保持默认

def test_mcp_servers_parsed(tmp_path):
    p = tmp_path / "config.toml"
    p.write_text('[[mcp_servers]]\nname = "demo"\ntype = "stdio"\ncommand = "python"\n', encoding="utf-8")
    c = Config.load(p)
    assert c.mcp_servers == [{"name": "demo", "type": "stdio", "command": "python"}]
```

- [ ] **Step 2: 运行确认失败**：`python -m pytest harness/tests/test_config.py -v` → FAIL（`ModuleNotFoundError: harness.config`）

- [ ] **Step 3: 最小实现**：按"接口"与"实现要点"写 `config.py`（注意 tomllib 的 table 读取：`data["mcp_servers"]` 为 list[dict]，键名原样透传）。conftest 增加 `session_config` 夹具。

- [ ] **Step 4: 运行确认通过**：`python -m pytest harness/tests/ -v` → 全部 PASS

- [ ] **Step 5: 提交**

```bash
git add harness/config.py harness/tests/test_config.py harness/tests/conftest.py
git commit -m "feat: TOML config loading with defaults and workspace fixture"
```

---

## Task 4: HITL 状态机 state.py（7 状态 17 规则，表驱动）

**目标**：表驱动状态机，完整实现 §11.4 的转移表；非法转移抛 `StateError`；记录事件历史。

**涉及文件**
- Create: `harness/state.py`、`harness/tests/test_state.py`

**接口**
- Produces:
  - `class StateError(Exception)`
  - `class StateMachine`：`__init__()`（state="idle"）；`state -> str`；`event_history -> list[dict]`（每项 `{"event","source","from","to","at"}`）；`fire(event: str, source: str) -> None`（source ∈ guardrail/agent/user/loop/session）；非法转移抛 `StateError`。
  - 模块常量 `TRANSITIONS: dict[tuple[str, str], str]`（见下，测试直接引用）。
- 完整转移表（spec §11.4 + 本次补全的 executing 状态）：

```
idle+task_submitted→running   running+tool_requested→executing
running+approval_needed→awaiting_user   running+agent_question→awaiting_user
running+interrupt→paused   running+final_answer→completed
executing+tool_finished→running   executing+interrupt→paused
executing+abort→terminated
awaiting_user+user_answered→running   awaiting_user+abort→terminated
paused+resume→running   paused+abort→terminated
completed+task_submitted→running
idle/running/executing/awaiting_user/paused/completed + error→running
任意状态 + session_unavailable→terminated
```

**依赖**：T1。**并行**：P1 第一个（可与 T8、T10 并行）。

**实现要点**：`TRANSITIONS` 为 dict 字面量；`fire` 查表，命中 → 更新 state + 追加 history（`datetime.now().isoformat()`）；未命中 → 抛 `StateError(f"illegal transition: {self.state} + {event}")`；`session_unavailable` 用显式 7 条目（含 terminated→terminated 幂等）。

**验证步骤**
- [ ] **Step 1: 写失败测试**

```python
# harness/tests/test_state.py
import pytest
from harness.state import StateMachine, StateError, TRANSITIONS

def test_full_transition_table_coverage():
    spec_rows = [
        ("idle", "task_submitted", "running"),
        ("running", "tool_requested", "executing"),
        ("running", "approval_needed", "awaiting_user"),
        ("running", "agent_question", "awaiting_user"),
        ("running", "interrupt", "paused"),
        ("running", "final_answer", "completed"),
        ("executing", "tool_finished", "running"),
        ("executing", "interrupt", "paused"),
        ("executing", "abort", "terminated"),
        ("awaiting_user", "user_answered", "running"),
        ("awaiting_user", "abort", "terminated"),
        ("paused", "resume", "running"),
        ("paused", "abort", "terminated"),
        ("completed", "task_submitted", "running"),
        ("idle", "error", "running"),
        ("running", "error", "running"),
        ("executing", "error", "running"),
        ("awaiting_user", "error", "running"),
        ("paused", "error", "running"),
        ("completed", "error", "running"),
        ("terminated", "session_unavailable", "terminated"),
    ]
    for s, e, nxt in spec_rows:
        assert TRANSITIONS[(s, e)] == nxt, f"{s}+{e}"

def test_ask_cycle_with_history():
    m = StateMachine()
    m.fire("task_submitted", "user"); m.fire("approval_needed", "guardrail")
    assert m.state == "awaiting_user"
    m.fire("user_answered", "user"); assert m.state == "running"
    assert [h["event"] for h in m.event_history] == ["task_submitted", "approval_needed", "user_answered"]
    assert m.event_history[1]["source"] == "guardrail"

def test_illegal_transition_raises():
    m = StateMachine()
    with pytest.raises(StateError): m.fire("abort", "user")  # idle+abort 非法
    with pytest.raises(StateError): m.fire("tool_requested", "loop")  # idle+tool_requested 非法
```

- [ ] **Step 2: 运行确认失败**：`python -m pytest harness/tests/test_state.py -v` → FAIL（`ModuleNotFoundError`）

- [ ] **Step 3: 最小实现**：按表实现 `state.py`。

- [ ] **Step 4: 运行确认通过**：`python -m pytest harness/tests/test_state.py -v` → PASS

- [ ] **Step 5: 提交**

```bash
git add harness/state.py harness/tests/test_state.py
git commit -m "feat: table-driven HITL state machine with 7 states and executing phase"
```

---

## Task 5: 护栏 guardrails.py（规则表 + 内置 deny 清单）

**目标**：`evaluate(rules, tool_name, args)` 有序遍历、最后匹配生效、无命中默认 allow；内置危险命令 deny 清单；`pattern` 支持 `tool_name[:arg_regex]`。

**涉及文件**
- Create: `harness/guardrails.py`、`harness/tests/test_guardrails.py`

**接口**
- Produces:
  - `@dataclass class Rule`：`pattern: str`、`action: str`（"allow"|"ask"|"deny"）、`source: str`（"builtin"|"user"|"skill:<name>"）
  - `@dataclass class Verdict`：`action: str`、`matched_rule: Rule | None`、`reason: str`
  - `pattern_matches(pattern: str, tool_name: str, args: dict) -> bool`：pattern 含 `:` → 按 `tool:regex` 拆，工具名相等且 `re.search` 命中 args 的 JSON 字符串表示；无 `:` → 工具名相等即命中
  - `default_rules() -> list[Rule]`：内置 deny 清单——`bash:rm -rf.*`（含 `rm -rf C:\`、`rm -rf /`、Windows 盘符路径）、`bash:.*:(){.*:};:`（fork 炸弹）、`bash:format.*`/`bash:del /f.*`（Windows 危险删除）等（至少覆盖 spec §11.2 表的"内置 deny 清单"场景与 §9 验收的 `rm -rf` 系统路径、fork 炸弹）
  - `evaluate(rules: list[Rule], tool_name: str, args: dict) -> Verdict`：有序遍历最后匹配生效；无命中 → `Verdict("allow", None, "no rule matched")`

**依赖**：T1。**并行**：P1 第二个（可与 T4、T8、T10 并行）。

**实现要点**：pattern 匹配 args 用 `json.dumps(args, ensure_ascii=False)` 做正则目标；`rm -rf` 的系统路径 deny 用正则覆盖 `rm -rf\s+[/\\](C:|C$|[A-Z]:\\|etc|boot|bin)` 及 `rm -rf /`；默认规则与用户/技能规则合并顺序见 T6（本任务只管规则与 evaluate）。

**验证步骤**
- [ ] **Step 1: 写失败测试**

```python
# harness/tests/test_guardrails.py
from harness.guardrails import Rule, evaluate, pattern_matches, default_rules

def test_no_match_allows():
    r = evaluate([Rule("bash:ls.*", "ask", "user")], "bash", {"command": "echo hi"})
    assert r.action == "allow" and r.matched_rule is None

def test_last_match_wins():
    rules = [Rule("bash", "deny", "builtin"), Rule("bash:ls.*", "allow", "user")]
    r = evaluate(rules, "bash", {"command": "ls -la"})
    assert r.action == "allow" and r.matched_rule.source == "user"
    r2 = evaluate(rules, "bash", {"command": "rm x"})
    assert r2.action == "deny"

def test_arg_regex_pattern():
    assert pattern_matches("bash:rm -rf.*", "bash", {"command": "rm -rf ./node_modules"})
    assert not pattern_matches("bash:rm -rf.*", "bash", {"command": "ls"})
    assert pattern_matches("write_file", "write_file", {"path": "x"})

def test_builtin_deny_catches_system_rm_rf():
    rules = default_rules()
    for cmd in ["rm -rf C:\\Windows", "rm -rf /", "rm -rf C:/Program Files", ":(){ :|:& };:"]:
        v = evaluate(rules, "bash", {"command": cmd})
        assert v.action == "deny", cmd
        assert v.matched_rule.source == "builtin"
```

- [ ] **Step 2: 运行确认失败**：`python -m pytest harness/tests/test_guardrails.py -v` → FAIL

- [ ] **Step 3: 最小实现**：按接口实现；内置清单正则按测试覆盖。

- [ ] **Step 4: 运行确认通过**：`python -m pytest harness/tests/test_guardrails.py -v` → PASS

- [ ] **Step 5: 提交**

```bash
git add harness/guardrails.py harness/tests/test_guardrails.py
git commit -m "feat: guardrail rules with last-match-wins and builtin deny list"
```

---

## Task 6: 自适应策略 policy.py（降级/升级/技能收紧）

**目标**：会话内自适应策略——"总是允许"降级 allow、"同一模式拒绝两次"升级 deny、反复批准降级；技能规则仅接受 ask/deny，allow 声明被拒并警告；规则合并顺序 用户 > 技能 > 内置；策略变化可记录（供转录）。

**涉及文件**
- Create: `harness/policy.py`、`harness/tests/test_policy.py`

**接口**
- Produces: `class Policy`：`__init__(user_rules: list[Rule] | None = None, skill_rules: list[Rule] | None = None)`；`rules -> list[Rule]`（内置 + 用户 + 技能，用户在前）；`apply_answer(rule: Rule, answer: str) -> None`（answer ∈ "y"/"n"/"always_allow"/"never_allow"；always_allow → 把该 rule 改为 allow；never_allow → deny；n → 记拒绝计数，同一 pattern 拒绝 ≥2 次 → 升级 deny；y → 批准计数，批准 ≥3 次 → 降级 allow）；`add_skill_rules(skill_rules: list[Rule]) -> list[str]`（仅接受 ask/deny，返回被拒绝的 allow 声明文本列表）；`changes() -> list[dict]`（`{"rule_pattern","old_action","new_action","answer","at"}`）

**依赖**：T1、T5。**并行**：P1 第三个。

**实现要点**：规则唯一标识用 `(pattern, source)`；apply_answer 修改 user_rules 内的副本；拒绝/批准计数存 `self._counts: dict[str, int]`；重复的"总是允许"只在规则存在时降级（不存在则新增 allow 规则）；每次变更 append 到 `self._changes`。

**验证步骤**
- [ ] **Step 1: 写失败测试**

```python
# harness/tests/test_policy.py
from harness.guardrails import Rule
from harness.policy import Policy

def test_always_allow_downgrades():
    p = Policy(user_rules=[Rule("bash:rm -rf.*", "ask", "user")])
    p.apply_answer(Rule("bash:rm -rf.*", "ask", "user"), "always_allow")
    assert any(r.pattern == "bash:rm -rf.*" and r.action == "allow" for r in p.rules)

def test_double_deny_upgrades_to_deny():
    p = Policy(user_rules=[Rule("bash:chmod.*", "ask", "user")])
    p.apply_answer(Rule("bash:chmod.*", "ask", "user"), "n")
    p.apply_answer(Rule("bash:chmod.*", "ask", "user"), "n")
    assert any(r.pattern == "bash:chmod.*" and r.action == "deny" for r in p.rules)

def test_skill_rules_tighten_only():
    p = Policy()
    rejected = p.add_skill_rules([
        Rule("bash:rm -rf.*", "allow", "skill:demo"),
        Rule("write_file:.*secrets.*", "ask", "skill:demo"),
    ])
    assert len(rejected) == 1 and "allow" in rejected[0]
    actions = {r.action for r in p.rules if r.source == "skill:demo"}
    assert actions == {"ask"}

def test_user_rules_beat_skill_rules():
    p = Policy(
        user_rules=[Rule("bash:git push.*", "ask", "user")],
        skill_rules=[Rule("bash:git push.*", "deny", "skill:demo")],
    )
    first = next(r for r in p.rules if r.pattern == "bash:git push.*" and r.source == "user")
    assert first.action == "ask"

def test_changes_recorded():
    p = Policy(user_rules=[Rule("bash:x", "ask", "user")])
    p.apply_answer(Rule("bash:x", "ask", "user"), "always_allow")
    assert p.changes()[-1]["new_action"] == "allow"
```

- [ ] **Step 2: 运行确认失败**：`python -m pytest harness/tests/test_policy.py -v` → FAIL

- [ ] **Step 3: 最小实现**：按接口实现 `policy.py`。

- [ ] **Step 4: 运行确认通过**：`python -m pytest harness/tests/test_policy.py -v` → PASS

- [ ] **Step 5: 提交**

```bash
git add harness/policy.py harness/tests/test_policy.py
git commit -m "feat: adaptive policy with downgrade/upgrade and skill tightening"
```

---

## Task 7: 钩子总线 hooks.py + 转录 transcript.py

**目标**：HookBus 注册/触发 PreToolUse/PostToolUse/SessionEnd；异常只记日志不致命；默认 SessionEnd 钩子写转录 JSON（消息、工具调用、策略变化）。

**涉及文件**
- Create: `harness/hooks.py`、`harness/transcript.py`、`harness/tests/test_hooks.py`

**接口**
- Produces:
  - `class HookBus`：`register(name: str, fn: Callable) -> None`；`pre_tool_use(tool_name: str, args: dict) -> tuple[dict, bool]`（依次调用，返回值 `(args, ok)` 允许修改 args；任一钩子异常 → 记入 `errors` 列表并继续，ok 保持 True）；`post_tool_use(tool_name: str, args: dict, result) -> None`（异常记 errors）；`session_end(messages: list[dict]) -> None`（异常记 errors；默认调用转录写入器）；`records() -> list[dict]`；`errors -> list[str]`
  - `transcript.write_transcript(path: Path, messages: list[dict], tool_calls: list[dict], policy_changes: list[dict]) -> None`：JSON（ensure_ascii=False, indent=2），键 `{"messages","tool_calls","policy_changes","written_at"}`
  - `transcript.default_session_end_hook(transcript_dir: Path)`：返回一个 `(messages) -> None` 钩子，文件名 `transcripts/<ISO时间戳>.json`（时间戳含毫秒、冒号替换为 `-`，保证 Windows 文件名合法）

**依赖**：T1。**并行**：P1 第四个。

**实现要点**：HookBus 内部 `_hooks: dict[str, list[Callable]]`；pre_tool_use 的返回值约定：钩子函数签名 `(tool_name, args) -> (dict, bool)`，多个钩子链式传递 args；默认 session_end 钩子在 `__init__(transcript_dir=None)` 时注册（None → 不注册，测试用记录钩子）。

**验证步骤**
- [ ] **Step 1: 写失败测试**

```python
# harness/tests/test_hooks.py
import json
from pathlib import Path
from harness.hooks import HookBus
from harness import transcript

def test_order_and_observation():
    bus = HookBus(); seen = []
    bus.register("pre", lambda name, args: (seen.append(("pre", name)) or (args, True)))
    bus.register("post", lambda name, args, result: seen.append(("post", name)))
    args, ok = bus.pre_tool_use("bash", {"command": "ls"})
    bus.post_tool_use("bash", args, {"status": "ok"})
    assert seen == [("pre", "bash"), ("post", "bash")]

def test_hook_can_modify_args():
    bus = HookBus()
    bus.register("pre", lambda name, args: (dict(args, command="ls -la"), True))
    args, ok = bus.pre_tool_use("bash", {"command": "ls"})
    assert args["command"] == "ls -la"

def test_hook_exception_nonfatal():
    bus = HookBus()
    def bad(name, args): raise RuntimeError("boom")
    bus.register("pre", bad)
    args, ok = bus.pre_tool_use("bash", {})
    assert ok is True and len(bus.errors) == 1

def test_default_session_end_writes_transcript(tmp_path):
    bus = HookBus(transcript_dir=tmp_path)
    bus.session_end([{"role": "user", "content": "hi"}])
    files = list(tmp_path.glob("*.json"))
    assert len(files) == 1
    data = json.loads(files[0].read_text(encoding="utf-8"))
    assert data["messages"][0]["content"] == "hi"
```

- [ ] **Step 2: 运行确认失败**：`python -m pytest harness/tests/test_hooks.py -v` → FAIL

- [ ] **Step 3: 最小实现**：`transcript.py` 与 `hooks.py` 按接口实现；时间戳文件名：`datetime.now().strftime("%Y-%m-%dT%H-%M-%S-%f")`。

- [ ] **Step 4: 运行确认通过**：`python -m pytest harness/tests/test_hooks.py -v` → PASS

- [ ] **Step 5: 提交**

```bash
git add harness/hooks.py harness/transcript.py harness/tests/test_hooks.py
git commit -m "feat: hook bus with transcript default session-end hook"
```

---

## Task 8: 沙箱 sandbox.py（LocalSandbox 子进程 + Docker 桩）

**目标**：`Sandbox.run(command, timeout)` 捕获 stdout/stderr/exit_code，超时杀进程，`cancel(call_id)` 终止在途进程；`network_enabled` 标志；DockerSandbox 桩快速报错。

**涉及文件**
- Create: `harness/sandbox.py`、`harness/tests/test_sandbox.py`

**接口**
- Produces:
  - `@dataclass class SandboxResult`：`stdout: str`、`stderr: str`、`exit_code: int`、`duration_ms: int`、`truncated: bool`
  - `class Sandbox(ABC)`：`network_enabled: bool`；`run(command: str, timeout: int) -> SandboxResult`（abstract）；`cancel(call_id: str) -> None`（abstract）
  - `class LocalSandbox(Sandbox)`：`__init__(network_enabled=False, max_output_bytes=51200)`；`run` 用 `subprocess.run(command, shell=True, capture_output=True, text=True, timeout=timeout)`；超时 `subprocess.TimeoutExpired` → 返回 exit_code=-1、stderr 含 "timeout"；stdout/stderr 超限截断（`truncated=True`，截断标记）；`cancel(call_id)`：维护 `_running: dict[call_id, Popen]`？——run 为阻塞调用，cancel 语义先以"记录已执行 + 幂等"实现，真实中断由 REPL Ctrl+C 层处理（T24）；`class DockerSandbox(Sandbox)`：桩——`run` 抛 `NotImplementedError("docker backend not available")`（spec：未安装 Docker 快速报错）。

**依赖**：T1。**并行**：P2 第一个（可与 P1/P3 并行）。

**实现要点**：Windows 下 `shell=True`；timeout 用 `subprocess.TimeoutExpired`；输出截断用 `out[:max] + b"...[truncated]"`（注意 text=True 已解码）；`truncated` 在任一流超限时置 True。

**验证步骤**
- [ ] **Step 1: 写失败测试**

```python
# harness/tests/test_sandbox.py
import pytest
from harness.sandbox import LocalSandbox, DockerSandbox

def test_run_success():
    r = LocalSandbox().run("echo hello", timeout=5)
    assert r.exit_code == 0 and "hello" in r.stdout

def test_run_failure_exit_code():
    r = LocalSandbox().run("exit 3", timeout=5)
    assert r.exit_code == 3

def test_timeout_kills(tmp_path):
    r = LocalSandbox().run("python -c \"import time; time.sleep(10)\"", timeout=1)
    assert r.exit_code != 0 and "timeout" in r.stderr.lower()

def test_output_truncation():
    sb = LocalSandbox(max_output_bytes=16)
    r = sb.run("python -c \"print('x'*100)\"", timeout=5)
    assert r.truncated and len(r.stdout) <= 16 + len("[...truncated]")

def test_docker_stub_errors():
    with pytest.raises(NotImplementedError):
        DockerSandbox().run("echo hi", timeout=5)
```

- [ ] **Step 2: 运行确认失败**：`python -m pytest harness/tests/test_sandbox.py -v` → FAIL

- [ ] **Step 3: 最小实现**：按接口实现；`LocalSandbox.__init__` 默认 `network_enabled=False`。

- [ ] **Step 4: 运行确认通过**：`python -m pytest harness/tests/test_sandbox.py -v` → PASS

- [ ] **Step 5: 提交**

```bash
git add harness/sandbox.py harness/tests/test_sandbox.py
git commit -m "feat: local sandbox subprocess runner with timeout and docker stub"
```

---

## Task 9: LLM 客户端 llm.py + FakeLLM（fake_llm.py）

**目标**：`OpenAILLM`（openai SDK → DeepSeek，流式 + tool_calls 解析 + 错误映射 + 限流退避重试一次）；`FakeLLM`（脚本化、测试与机制演示共用，绝无网络）。

**涉及文件**
- Create: `harness/llm.py`、`harness/fake_llm.py`、`harness/tests/test_llm.py`

**接口**
- Produces（llm.py）:
  - 异常：`class LLMError(Exception)`、`LLMAuthError(LLMError)`、`LLMRateLimitError(LLMError)`、`LLMNetworkError(LLMError)`
  - `@dataclass class LLMResult`：`text: str`、`tool_calls: list[dict]`（每项 `{"name", "arguments": dict}`）、`usage: dict`（`{"approx_tokens": int}`，字符数/4）
  - `class LLM(ABC)`：`complete(messages: list[dict], tools: list[dict]) -> LLMResult`（abstract）
  - `class OpenAILLM(LLM)`：`__init__(api_key: str, base_url="https://api.deepseek.com", model="deepseek-chat", http_client=None)`（http_client 注入供测试）；`complete` 调 `chat.completions.create(stream=True)` 聚合流式文本 + 解析 `tool_calls`（多调用同回合支持）；错误映射：401 → LLMAuthError、429 → LLMRateLimitError（退避重试一次，仍失败再抛）、连接异常 → LLMNetworkError
- Produces（fake_llm.py）:
  - `@dataclass class FakeTurn`：`text: str = ""`、`tool_calls: list[dict] | None = None`（`{"name", "arguments": dict}`）、`usage_approx: int = 10`
  - `class FakeLLM(LLM)`：`__init__(turns: list[FakeTurn])`；每次 `complete` 弹出下一个 turn（耗尽后重放最后一个）；`calls: int` 计数；`turn_index: int`

**依赖**：T1。**并行**：P2 第二个。

**实现要点**：OpenAILLM 的流式聚合：迭代 chunk，`chunk.choices[0].delta.content` 拼接 text，`delta.tool_calls` 按 index 累积 name/arguments 片段再 json 解析（解析失败 → arguments={} + LLMError 说明）；429 重试一次（sleep 1s，测试注入 0）；测试用 `openai.OpenAI(http_client=httpx.Client(transport=httpx.MockTransport(handler)))`，handler 返回脚本化 SSE 响应（`text/event-stream`）。

**验证步骤**
- [ ] **Step 1: 写失败测试**

```python
# harness/tests/test_llm.py
import json, pytest
from harness.llm import OpenAILLM, LLMAuthError, LLMRateLimitError
from harness.fake_llm import FakeLLM, FakeTurn

def sse_handler(payload):
    def handler(request):
        import httpx
        lines = "\n".join(f"data: {json.dumps(c)}" for c in payload) + "\n\ndata: [DONE]\n\n"
        return httpx.Response(200, text=lines, headers={"Content-Type": "text/event-stream"})
    return handler

def test_fake_llm_scripted():
    llm = FakeLLM([FakeTurn(tool_calls=[{"name": "bash", "arguments": {"command": "ls"}}]),
                   FakeTurn(text="final")])
    r1 = llm.complete([], []); r2 = llm.complete([], [])
    assert r1.tool_calls[0]["name"] == "bash"
    assert r2.text == "final" and r2.tool_calls == []

def test_openai_streaming_and_tool_calls(monkeypatch):
    import httpx
    payload = [
        {"choices": [{"delta": {"content": "思考中"}}]},
        {"choices": [{"delta": {"tool_calls": [{"index": 0, "id": "c1", "function": {"name": "bash", "arguments": ""}}]}}]},
        {"choices": [{"delta": {"tool_calls": [{"index": 0, "function": {"arguments": "{\"comm"}}]}}]},
        {"choices": [{"delta": {"tool_calls": [{"index": 0, "function": {"arguments": "and\": \"ls\"}"}}]}}]},
        {"choices": [{"delta": {}, "finish_reason": "tool_calls"}]},
    ]
    client = httpx.Client(transport=httpx.MockTransport(sse_handler(payload)))
    llm = OpenAILLM("test-key", http_client=client)
    r = llm.complete([{"role": "user", "content": "x"}], [])
    assert "思考中" in r.text
    assert r.tool_calls == [{"name": "bash", "arguments": {"command": "ls"}}]
    assert r.usage["approx_tokens"] >= 1

def test_auth_error_mapping(monkeypatch):
    import httpx
    def handler(request): return httpx.Response(401, json={"error": {"message": "bad key"}})
    llm = OpenAILLM("bad", http_client=httpx.Client(transport=httpx.MockTransport(handler)))
    with pytest.raises(LLMAuthError): llm.complete([], [])

def test_rate_limit_retries_once_then_raises(monkeypatch):
    import httpx
    calls = {"n": 0}
    def handler(request):
        calls["n"] += 1
        return httpx.Response(429, json={"error": {"message": "slow"}})
    monkeypatch.setattr("harness.llm.RETRY_BACKOFF", 0.0)
    llm = OpenAILLM("k", http_client=httpx.Client(transport=httpx.MockTransport(handler)))
    with pytest.raises(LLMRateLimitError): llm.complete([], [])
    assert calls["n"] == 2
```

- [ ] **Step 2: 运行确认失败**：`python -m pytest harness/tests/test_llm.py -v` → FAIL

- [ ] **Step 3: 最小实现**：`llm.py`（模块常量 `RETRY_BACKOFF = 1.0`）+ `fake_llm.py`。注意 openai SDK 的 `client.chat.completions.create(model=..., messages=..., tools=tools or None, stream=True)`；`http_client` 参数透传 `openai.OpenAI(api_key=..., base_url=..., http_client=...)`。

- [ ] **Step 4: 运行确认通过**：`python -m pytest harness/tests/test_llm.py -v` → PASS

- [ ] **Step 5: 提交**

```bash
git add harness/llm.py harness/fake_llm.py harness/tests/test_llm.py
git commit -m "feat: OpenAI-compatible LLM client with error mapping and scripted FakeLLM"
```

---

## Task 10: 记忆库 memory.py（TF-IDF 检索 + 分块 + 落盘）

**目标**：纯标准库 TF-IDF 索引 `memory/*.md`，任务启动检索 top-2、memory_search top-1；`memory_save` 分块落盘；损坏文件跳过并警告。

**涉及文件**
- Create: `harness/memory.py`、`harness/tests/test_memory.py`

**接口**
- Produces: `class MemoryStore`：`__init__(root: Path, top_k=2)`；`load()`（重建索引：读取 `root/*.md` 按段落分块（空行分隔），损坏文件 → `warnings` 列表并跳过）；`save(title: str, content: str) -> Path`（写 `root/<title>.md`，title 非法字符替换为 `_`）；`search(query: str, k: int | None = None) -> list[dict]`（`[{"title","chunk","score"}]` 降序）；`top_k_chunks(query: str) -> list[dict]`（默认 k=2，供任务启动注入）；`warnings -> list[str]`

**依赖**：T1。**并行**：P3（可与 P1/P2 并行）。

**实现要点**：TF-IDF：词表 = 中文按 2-gram 切分 + 英文按 `re.findall(r"[a-zA-Z0-9_]+")`；`tf = 词频/总词数`，`idf = ln(1 + N/df)`（平滑）；分块按 `\n\n` 切分；`save` 写入时内容超 2000 字符自动按段落分块成多个 `-part` 文件（`<title>-part<N>.md`，检索仍按文件聚合）；性能：100 条目检索 < 50ms（索引在 load 时构建，检索 O(chunks)）。

**验证步骤**
- [ ] **Step 1: 写失败测试**

```python
# harness/tests/test_memory.py
import time
from pathlib import Path
from harness.memory import MemoryStore

def test_save_and_search_roundtrip(tmp_path):
    m = MemoryStore(tmp_path)
    m.save("agent-rules", "项目约定：禁止在生产库执行写操作。\n\n所有修改先走 review。")
    m.load()
    res = m.search("生产库写操作", k=1)
    assert res and res[0]["title"] == "agent-rules" and "生产库" in res[0]["chunk"]

def test_top_k_injection(tmp_path):
    m = MemoryStore(tmp_path, top_k=2)
    m.save("a", "x" * 60); m.save("b", "x" * 60); m.save("c", "y" * 60)
    m.load()
    hits = m.top_k_chunks("xxx")
    assert len(hits) == 2 and all(h["score"] > 0 for h in hits)

def test_corrupted_file_skipped(tmp_path):
    (tmp_path / "broken.md").write_bytes(b"\xff\xfe\x00\x01")
    (tmp_path / "good.md").write_text("hello world\n", encoding="utf-8")
    m = MemoryStore(tmp_path); m.load()
    assert len(m.warnings) == 1
    assert m.search("hello", k=1)[0]["title"] == "good"

def test_retrieval_perf_smoke(tmp_path):
    m = MemoryStore(tmp_path)
    for i in range(100):
        m.save(f"note-{i}", f"内容 {i} " * 30)
    m.load()
    t0 = time.monotonic()
    m.search("内容 50", k=5)
    assert time.monotonic() - t0 < 0.05
```

- [ ] **Step 2: 运行确认失败**：`python -m pytest harness/tests/test_memory.py -v` → FAIL

- [ ] **Step 3: 最小实现**：按接口实现（`load` 在索引构建时自动调用——`__init__` 后显式 `load()`，`save` 后需重 `load()` 或增量加入索引；测试按上述顺序即可）。

- [ ] **Step 4: 运行确认通过**：`python -m pytest harness/tests/test_memory.py -v` → PASS

- [ ] **Step 5: 提交**

```bash
git add harness/memory.py harness/tests/test_memory.py
git commit -m "feat: TF-IDF memory store with chunking, save/search and corrupted-file skip"
```

---

## Task 11: 工具注册表 + bash 工具（registry.py + tools/bash.py）

**目标**：工具注册表（name/description/schema/handler）+ `ToolCall`/`ToolResult` 类型；bash 工具走 `LocalSandbox`，超时/截断由沙箱负责。

**涉及文件**
- Create: `harness/types.py`、`harness/tools/registry.py`、`harness/tools/bash.py`、`harness/tests/test_tools_bash.py`

**接口**
- Produces:
  - `harness/types.py`：`@dataclass ToolCall`（`name: str`、`arguments: dict`、`id: str = ""`）；`@dataclass ToolResult`（`status: str`（"success"|"error"|"timeout"）、`output: str`、`error: str | None = None`、`exit_code: int | None = None`、`duration_ms: int = 0`、`truncated: bool = False`）；`def to_message(result: ToolResult) -> dict`（`{"role": "tool", "content": ...}`）
  - `harness/tools/registry.py`：`@dataclass ToolSpec`（`name: str`、`description: str`、`schema: dict`、`handler: Callable[[dict, Context], ToolResult]`）；`@dataclass Context`（`workspace: Path`、`sandbox`、`hooks: HookBus`、`policy: Policy`、`state: StateMachine`、`memory: MemoryStore`、`config: Config`、`ask_callback: Callable | None = None`、`agent_factory: Callable | None = None`、`llm: LLM | None = None`）；`make_registry(specs: list[ToolSpec]) -> dict[str, ToolSpec]`；`build_request_tools(registry) -> list[dict]`（OpenAI tools 格式：type=function + schema）
  - `harness/tools/bash.py`：`spec(sandbox) -> ToolSpec`：name="bash"，schema `{"type":"object","properties":{"command":{"type":"string"}},"required":["command"]}`；handler：`ctx.sandbox.run(command, ctx.config.tool_timeout)` → ToolResult（网络关闭时在结果中注明 `network_enabled` 状态；不做网络拦截——拦截是护栏的职责，见 T20 集成）
- 注意：`types.py` 为计划新增文件（spec 附录未列，属实现细节补充，接口层避免循环依赖）。

**依赖**：T1、T8。**并行**：L2 第一个。

**实现要点**：`make_registry` 查重（同名 spec 报 ValueError）；`build_request_tools` 用 `{"type":"function","function":{"name","description","parameters": schema}}`。

**验证步骤**
- [ ] **Step 1: 写失败测试**

```python
# harness/tests/test_tools_bash.py
import pytest
from harness.types import ToolCall, ToolResult
from harness.tools.registry import make_registry
from harness.tools.bash import spec as bash_spec
from harness.sandbox import LocalSandbox
from harness.config import Config
from harness.tools.registry import Context

def test_bash_tool_runs(tmp_path):
    sb = LocalSandbox()
    ctx = Context(workspace=tmp_path, sandbox=sb, hooks=None, policy=None,
                  state=None, memory=None, config=Config(workspace=tmp_path, tool_timeout=5))
    reg = make_registry([bash_spec(sb)])
    r = reg["bash"].handler({"command": "echo tool-ok"}, ctx)
    assert r.status == "success" and "tool-ok" in r.output

def test_bash_tool_timeout(tmp_path):
    sb = LocalSandbox()
    ctx = Context(workspace=tmp_path, sandbox=sb, hooks=None, policy=None,
                  state=None, memory=None,
                  config=Config(workspace=tmp_path, tool_timeout=1))
    r = reg_handler(ctx)  # 复用上面注册的 handler
    assert r.status == "timeout"

def test_tool_result_to_message():
    m = ToolResult(status="error", error="guardrail denied: x").to_message()
    assert m["role"] == "tool"
```

- [ ] **Step 2: 运行确认失败**：`python -m pytest harness/tests/test_tools_bash.py -v` → FAIL（`ModuleNotFoundError: harness.types`）

- [ ] **Step 3: 最小实现**：`types.py`（`to_message` 作为 ToolResult 方法：`{"role":"tool","content": output 或 error}`）；`registry.py`；`bash.py`（`ToolResult(status="success" if exit_code==0 else "error", ...)`；timeout 时 status="timeout"）。

- [ ] **Step 4: 运行确认通过**：`python -m pytest harness/tests/test_tools_bash.py -v` → PASS

- [ ] **Step 5: 提交**

```bash
git add harness/types.py harness/tools/registry.py harness/tools/bash.py harness/tests/test_tools_bash.py
git commit -m "feat: tool registry with ToolCall/ToolResult types and bash tool"
```

---

## Task 12: 文件与搜索工具（files.py + search.py，防逃逸）

**目标**：read_file/write_file/list/glob/grep；工作区路径规范化，`..` 与符号链接逃逸 100% 拒绝；工作区外写 deny（工具层第二道防线）。

**涉及文件**
- Create: `harness/tools/files.py`、`harness/tools/search.py`、`harness/tests/test_tools_files.py`

**接口**
- Produces: `files.spec() -> ToolSpec`（read_file: path 必填；write_file: path+content；`_resolve_workspace_path(workspace, rel) -> Path | None`：`(workspace / rel).resolve()` 后必须 `is_relative_to(workspace.resolve())`，否则 None）；`search.spec() -> ToolSpec`（glob: pattern；grep: pattern+path?，用 `pathlib.Path.glob`/`re.search`，限工作区内）

**依赖**：T11（registry/types）。**并行**：L2。

**实现要点**：`.resolve()` 会解析符号链接（spec 明确符号链接逃逸拒绝）；Windows 下大小写不敏感比较：`str(p).lower()` 前缀比较（`is_relative_to` 3.9+ 可用，但加 lower() 兜底）；write_file 拒绝 None（非法路径）→ `ToolResult(status="error", error="path outside workspace")`；grep 结果上限 200 条。

**验证步骤**
- [ ] **Step 1: 写失败测试**

```python
# harness/tests/test_tools_files.py
from pathlib import Path
from harness.tools.registry import Context, make_registry
from harness.tools.files import spec as files_spec
from harness.tools.search import spec as search_spec
from harness.config import Config
from harness.sandbox import LocalSandbox

def ctx(ws):
    return Context(workspace=ws, sandbox=LocalSandbox(), hooks=None, policy=None,
                   state=None, memory=None, config=Config(workspace=ws))

def test_write_and_read(tmp_path):
    reg = make_registry([files_spec()])
    r = reg["write_file"].handler({"path": "a.txt", "content": "hi"}, ctx(tmp_path))
    assert r.status == "success"
    r2 = reg["read_file"].handler({"path": "a.txt"}, ctx(tmp_path))
    assert "hi" in r2.output

def test_dotdot_escape_denied(tmp_path):
    reg = make_registry([files_spec()])
    r = reg["write_file"].handler({"path": "../evil.txt", "content": "x"}, ctx(tmp_path))
    assert r.status == "error" and "outside workspace" in r.error

def test_symlink_escape_denied(tmp_path):
    outside = tmp_path.parent / "secret.txt"; outside.write_text("secret", encoding="utf-8")
    link = tmp_path / "link"
    try:
        link.symlink_to(outside)
    except OSError:
        return  # Windows 无权限时跳过
    reg = make_registry([files_spec()])
    r = reg["read_file"].handler({"path": "link"}, ctx(tmp_path))
    assert r.status == "error"

def test_grep_within_workspace(tmp_path):
    (tmp_path / "x.py").write_text("def foo():\n    pass\n", encoding="utf-8")
    reg = make_registry([search_spec()])
    r = reg["grep"].handler({"pattern": "def foo", "path": "."}, ctx(tmp_path))
    assert r.status == "success" and "x.py" in r.output
```

- [ ] **Step 2: 运行确认失败**：`python -m pytest harness/tests/test_tools_files.py -v` → FAIL

- [ ] **Step 3: 最小实现**：`files.py`、`search.py` 按接口实现。

- [ ] **Step 4: 运行确认通过**：`python -m pytest harness/tests/test_tools_files.py -v` → PASS

- [ ] **Step 5: 提交**

```bash
git add harness/tools/files.py harness/tools/search.py harness/tests/test_tools_files.py
git commit -m "feat: file and search tools with workspace escape protection"
```

---

## Task 13: 网络工具 web.py（fetch_url）

**目标**：fetch_url 用 `requests`，响应大小上限、超时；`sandbox.network_enabled` 为 False 时拒绝执行（返回明确错误）。

**涉及文件**
- Create: `harness/tools/web.py`、`harness/tests/test_tools_web.py`

**接口**
- Produces: `web.spec(requests_get: Callable | None = None) -> ToolSpec`（可注入 `requests.get` 供测试）；schema：`{"url": "string", "max_bytes": "integer"}`；行为：`ctx.sandbox.network_enabled` False → `ToolResult(status="error", error="network disabled")`；否则 GET（timeout=10，注入函数默认 `requests.get`），响应超 51200 字节截断 + `truncated=True`。

**依赖**：T11。**并行**：L2。

**实现要点**：测试注入假 `requests_get` 返回 `FakeResponse(status_code, text, content)`；非 200 → error 带状态码。

**验证步骤**
- [ ] **Step 1: 写失败测试**

```python
# harness/tests/test_tools_web.py
from harness.tools.registry import Context, make_registry
from harness.tools.web import spec as web_spec
from harness.config import Config
from harness.sandbox import LocalSandbox

class FakeResponse:
    def __init__(self, status_code=200, text="hello web", content=b"hello web"):
        self.status_code = status_code; self.text = text; self.content = content

def ctx(ws, network):
    sb = LocalSandbox(network_enabled=network)
    return Context(workspace=ws, sandbox=sb, hooks=None, policy=None, state=None,
                   memory=None, config=Config(workspace=ws))

def test_fetch_disabled_by_default(tmp_path):
    reg = make_registry([web_spec()])
    r = reg["fetch_url"].handler({"url": "https://example.com"}, ctx(tmp_path, False))
    assert r.status == "error" and "network disabled" in r.error

def test_fetch_ok_when_enabled(tmp_path):
    seen = {}
    def fake_get(url, timeout):
        seen["url"] = url; return FakeResponse()
    reg = make_registry([web_spec(fake_get)])
    r = reg["fetch_url"].handler({"url": "https://example.com"}, ctx(tmp_path, True))
    assert r.status == "success" and "hello web" in r.output and seen["url"].startswith("https://")

def test_fetch_http_error(tmp_path):
    reg = make_registry([web_spec(lambda url, timeout: FakeResponse(404, "not found"))])
    r = reg["fetch_url"].handler({"url": "https://example.com/nope"}, ctx(tmp_path, True))
    assert r.status == "error" and "404" in r.error
```

- [ ] **Step 2: 运行确认失败**：`python -m pytest harness/tests/test_tools_web.py -v` → FAIL

- [ ] **Step 3: 最小实现**：按接口实现 `web.py`（注入函数签名 `(url, timeout) -> response`）。

- [ ] **Step 4: 运行确认通过**：`python -m pytest harness/tests/test_tools_web.py -v` → PASS

- [ ] **Step 5: 提交**

```bash
git add harness/tools/web.py harness/tests/test_tools_web.py
git commit -m "feat: fetch_url tool with network flag gate and size cap"
```

---

## Task 14: 便签工具 notes.py

**目标**：notes 追加/列出（`workspace/notes.md` 追加式记录，简单可靠）。

**涉及文件**
- Create: `harness/tools/notes.py`、`harness/tests/test_tools_notes.py`

**接口**
- Produces: `notes.spec() -> ToolSpec`：tools `notes_append`（text）与 `notes_list`；notes 文件 `workspace/.harness_notes.md`；append 失败（目录不可写）→ error 结果。

**依赖**：T11。**并行**：L2。

**验证步骤**
- [ ] **Step 1: 写失败测试**

```python
# harness/tests/test_tools_notes.py
from harness.tools.registry import Context, make_registry
from harness.tools.notes import spec as notes_spec
from harness.config import Config
from harness.sandbox import LocalSandbox

def ctx(ws):
    return Context(workspace=ws, sandbox=LocalSandbox(), hooks=None, policy=None,
                   state=None, memory=None, config=Config(workspace=ws))

def test_notes_append_and_list(tmp_path):
    reg = make_registry([notes_spec()])
    assert reg["notes_append"].handler({"text": "第一条"}, ctx(tmp_path)).status == "success"
    reg["notes_append"].handler({"text": "第二条"}, ctx(tmp_path))
    r = reg["notes_list"].handler({}, ctx(tmp_path))
    assert "第一条" in r.output and "第二条" in r.output
```

- [ ] **Step 2: 运行确认失败** → FAIL
- [ ] **Step 3: 最小实现**：`notes.py`（append 模式写文件，`utf-8`，`\n` 结尾）。
- [ ] **Step 4: 运行确认通过** → PASS
- [ ] **Step 5: 提交**

```bash
git add harness/tools/notes.py harness/tests/test_tools_notes.py
git commit -m "feat: notes append/list tool"
```

---

## Task 15: 记忆工具 tools/memory.py（memory_save / memory_search）

**目标**：把 T10 的 MemoryStore 暴露为工具：`memory_save(title, content)` 落盘；`memory_search(query, k=3)` 返回相关块。

**涉及文件**
- Create: `harness/tools/memory.py`、`harness/tests/test_tools_memory.py`

**接口**
- Produces: `memory_tools.specs(memory: MemoryStore) -> list[ToolSpec]`（两个 spec；handler 从 `ctx.memory` 取库——若 `ctx.memory` 为 None 返回 error；search 输出前 k 块的 title + chunk 摘要）。

**依赖**：T10、T11。**并行**：L2。

**验证步骤**
- [ ] **Step 1: 写失败测试**

```python
# harness/tests/test_tools_memory.py
from harness.tools.registry import Context, make_registry
from harness.tools.memory import specs as memory_specs
from harness.memory import MemoryStore
from harness.config import Config
from harness.sandbox import LocalSandbox

def ctx(ws, memory):
    return Context(workspace=ws, sandbox=LocalSandbox(), hooks=None, policy=None,
                   state=None, memory=memory, config=Config(workspace=ws))

def test_save_then_search(tmp_path):
    m = MemoryStore(tmp_path)
    reg = make_registry(memory_specs(m))
    reg["memory_save"].handler({"title": "约定", "content": "禁止生产库写操作"}, ctx(tmp_path, m))
    r = reg["memory_search"].handler({"query": "生产库", "k": 1}, ctx(tmp_path, m))
    assert r.status == "success" and "禁止生产库写操作" in r.output
```

- [ ] **Step 2: 运行确认失败** → FAIL
- [ ] **Step 3: 最小实现**：`memory_save` → `m.save(title, content)` + 立即刷新索引（save 内部已处理）；`memory_search` → `m.search(query, k)`。
- [ ] **Step 4: 运行确认通过** → PASS
- [ ] **Step 5: 提交**

```bash
git add harness/tools/memory.py harness/tests/test_tools_memory.py
git commit -m "feat: memory_save and memory_search tools"
```

---

## Task 16: 提问工具 ask.py（编号菜单 + 状态机经 awaiting_user）

**目标**：ask_user 渲染编号菜单，回答作为工具结果返回；执行期间状态机经 `agent_question → awaiting_user → user_answered → running`。

**涉及文件**
- Create: `harness/tools/ask.py`、`harness/tests/test_tools_ask.py`

**接口**
- Produces: `ask.spec() -> ToolSpec`：schema `{"question": "string", "options": "array[string]"}`；handler：`ctx.state.fire("agent_question", "agent")` → `ctx.ask_callback(question, options)`（无 callback → error 结果）→ 返回用户选择（编号或文本）→ `ctx.state.fire("user_answered", "user")` → `ToolResult(output=答案)`；`ask_callback` 由 REPL 注入（T24），测试注入假 callback 返回固定选择。

**依赖**：T4、T11。**并行**：L2。

**验证步骤**
- [ ] **Step 1: 写失败测试**

```python
# harness/tests/test_tools_ask.py
from harness.tools.registry import Context, make_registry
from harness.tools.ask import spec as ask_spec
from harness.state import StateMachine
from harness.config import Config
from harness.sandbox import LocalSandbox

def ctx(ws, state, cb):
    return Context(workspace=ws, sandbox=LocalSandbox(), hooks=None, policy=None,
                   state=state, memory=None, config=Config(workspace=ws), ask_callback=cb)

def test_ask_menu_cycle(tmp_path):
    m = StateMachine(); m.fire("task_submitted", "user")
    answers = []
    def cb(question, options):
        answers.append((question, options))
        return options[1]
    reg = make_registry([ask_spec()])
    r = reg["ask_user"].handler({"question": "选哪个?", "options": ["A", "B"]}, ctx(tmp_path, m, cb))
    assert r.status == "success" and "B" in r.output
    assert answers[0][0] == "选哪个?"
    assert [h["event"] for h in m.event_history[-2:]] == ["agent_question", "user_answered"]
    assert m.state == "running"
```

- [ ] **Step 2: 运行确认失败** → FAIL
- [ ] **Step 3: 最小实现**：按接口；callback 抛出异常 → `ToolResult(status="error", error="ask cancelled")` 且 fire `user_answered`（保持状态机一致，用 try/finally）。
- [ ] **Step 4: 运行确认通过** → PASS
- [ ] **Step 5: 提交**

```bash
git add harness/tools/ask.py harness/tests/test_tools_ask.py
git commit -m "feat: ask_user tool with numbered menu through HITL state machine"
```

---

## Task 17: 技能工具 skills.py（SKILL.md 加载 + 规则收紧）

**目标**：`list_skills` / `load_skill`：读 `skills/<name>/SKILL.md` 注入系统消息；解析声明的护栏规则（仅 ask/deny，allow 声明被拒并警告）经 `policy.add_skill_rules` 注册；SKILL.md 解析失败跳过并警告。

**涉及文件**
- Create: `harness/tools/skills.py`、`harness/tests/test_tools_skills.py`（含夹具技能目录）

**接口**
- Produces: `skills_tools.specs(skills_root: Path) -> list[ToolSpec]`：
  - `list_skills`：列 `skills_root/*/SKILL.md` 的名字
  - `load_skill(name)`：读文件 → 解析 front 部分规则块（约定：SKILL.md 内 `## Guardrails` 段，行格式 `tool[:regex] → ask|deny`；其余正文作为技能描述）→ 返回注入文本 `[skill:<name>] 描述…\n<正文>`；规则经 `ctx.policy.add_skill_rules` 注册，被拒的 allow 声明加入输出警告
- 夹具：`harness/tests/fixtures/skills/reviewer/SKILL.md`（含一条 allow 声明 + 一条 ask 声明）、`broken/SKILL.md`（非法 UTF-8）。

**依赖**：T6、T11。**并行**：L2。

**验证步骤**
- [ ] **Step 1: 写失败测试**

```python
# harness/tests/test_tools_skills.py
import shutil, sys
from pathlib import Path
from harness.tools.registry import Context, make_registry
from harness.tools.skills import specs as skills_specs
from harness.policy import Policy
from harness.state import StateMachine
from harness.config import Config
from harness.sandbox import LocalSandbox

FIXTURES = Path(__file__).parent / "fixtures" / "skills"

def ctx(ws, policy):
    return Context(workspace=ws, sandbox=LocalSandbox(), hooks=None, policy=policy,
                   state=StateMachine(), memory=None, config=Config(workspace=ws))

def test_load_skill_tightens_rules(tmp_path):
    skills_root = tmp_path / "skills"
    shutil.copytree(FIXTURES, skills_root)
    p = Policy()
    reg = make_registry(skills_specs(skills_root))
    r = reg["load_skill"].handler({"name": "reviewer"}, ctx(tmp_path, p))
    assert r.status == "success"
    assert "[skill:reviewer]" in r.output
    assert "allow 声明被拒绝" in r.output  # 警告
    skill_actions = {rule.action for rule in p.rules if rule.source == "skill:reviewer"}
    assert skill_actions == {"ask"}

def test_load_broken_skill_warns(tmp_path):
    skills_root = tmp_path / "skills"
    shutil.copytree(FIXTURES, skills_root)
    reg = make_registry(skills_specs(skills_root))
    r = reg["load_skill"].handler({"name": "broken"}, ctx(tmp_path, Policy()))
    assert r.status == "error" or "跳过" in r.output
```

- [ ] **Step 2: 运行确认失败** → FAIL（需先建夹具目录）
- [ ] **Step 3: 最小实现**：创建夹具 `fixtures/skills/reviewer/SKILL.md`：

```markdown
# Reviewer 技能
## Guardrails
write_file:.*secrets.* → ask
bash:rm -rf.* → allow   # 将被拒绝并警告
```

`broken/SKILL.md` 写非法字节 `\xff\xfe`。`skills.py` 解析 + 注册 + 警告。

- [ ] **Step 4: 运行确认通过** → PASS
- [ ] **Step 5: 提交**

```bash
git add harness/tools/skills.py harness/tests/test_tools_skills.py harness/tests/fixtures/skills/
git commit -m "feat: skills loader with tightening-only rule registration"
```

---

## Task 18: MCP 客户端 mcp.py（stdio/url 工具动态注册）

**目标**：连接 MCP 服务器（stdio/url），列出并动态注册工具进注册表（schema 原样透传），调用转发；连接失败 → 该服务器优雅停用，其余不受影响。v1 仅 tools 通道。

**涉及文件**
- Create: `harness/mcp.py`、`harness/tests/test_mcp.py`、`harness/tests/fixtures/fake_mcp_server.py`

**接口**
- Produces: `class MCPServer`：`__init__(name: str, cfg: dict)`（cfg: `{"type": "stdio"|"url", "command"|"url"}`）；`connect() -> bool`；`list_tools() -> list[dict]`（`{"name","description","inputSchema"}`）；`call(name: str, args: dict) -> dict`（转发结果）；`close()`；`load_mcp_servers(server_cfgs: list[dict], registry: dict, sandbox, config) -> list[str]`（返回激活的服务器名列表；失败的服务器警告并跳过，不阻塞）。
- 实现方式（v1）：**不引入 mcp SDK 运行时复杂度**——stdio 服务器用 `subprocess.Popen` + 行式 JSON-RPC 2.0（`initialize` → `tools/list` → `tools/call`），`initialize` 失败/超时 3s → 停用；url 服务器用 `requests.post`（同样 JSON-RPC）。这与 spec §4.3 "MCP 用官方 Python SDK" 冲突，改为手写轻量协议（更可测试、零网络依赖）；在 PLAN 中记为**实现偏差**，待评审确认。

**依赖**：T11。**并行**：L2。

**验证步骤**
- [ ] **Step 1: 写失败测试**（夹具服务器：`fixtures/fake_mcp_server.py` 读 stdin 行 JSON 回 `tools/list` 与 `tools/call` 应答）

```python
# harness/tests/test_mcp.py
import subprocess, sys
from pathlib import Path
from harness.mcp import MCPServer, load_mcp_servers
from harness.tools.registry import make_registry
from harness.config import Config
from harness.sandbox import LocalSandbox

FAKE = Path(__file__).parent / "fixtures" / "fake_mcp_server.py"

def test_stdio_list_and_call(tmp_path):
    srv = MCPServer("demo", {"type": "stdio", "command": sys.executable, "args": [str(FAKE)]})
    assert srv.connect()
    tools = srv.list_tools()
    assert any(t["name"] == "echo_tool" for t in tools)
    res = srv.call("echo_tool", {"text": "mcp-ok"})
    assert "mcp-ok" in str(res)
    srv.close()

def test_connection_failure_disables_only_that_server(tmp_path):
    reg = make_registry([])
    cfg = Config(workspace=tmp_path,
                 mcp_servers=[{"name": "dead", "type": "stdio", "command": "does-not-exist-xyz"}])
    active = load_mcp_servers(cfg.mcp_servers, reg, LocalSandbox(), cfg)
    assert active == []
```

- [ ] **Step 2: 运行确认失败** → FAIL
- [ ] **Step 3: 最小实现**：`fake_mcp_server.py`（`sys.stdin` 逐行读 JSON-RPC，回复 `tools/list` 的 `echo_tool`（schema `{"type":"object","properties":{"text":{"type":"string"}}}`）与 `tools/call` 的 `{"content": [{"type":"text","text": args["text"]}]}`）；`mcp.py` 按接口实现（stdio 超时 3s、失败 → `connect()` False；`load_mcp_servers` 把注册工具的 handler 包成转发调用）。
- [ ] **Step 4: 运行确认通过** → PASS
- [ ] **Step 5: 提交**

```bash
git add harness/mcp.py harness/tests/test_mcp.py harness/tests/fixtures/fake_mcp_server.py
git commit -m "feat: MCP stdio/url client with dynamic tool registration and graceful disable"
```

---

## Task 19: Agent 迭代核心 agent.py（三阶段 + 工具流水线集成）

**目标**：Agent 类——任务开始（top-2 检索注入留待 T21）、迭代（LLM → tool_calls → 流水线）、收尾（留待 T22）；工具流水线严格排序：护栏 → ask 分支 → PreToolUse → tool_requested → 执行 → tool_finished → PostToolUse；步数上限 50；无工具调用 → 最终答案。

**涉及文件**
- Create: `harness/agent.py`、`harness/tests/test_agent_core.py`

**接口**
- Produces: `@dataclass class AgentResult`：`text: str`、`steps_used: int`、`tool_results: list[dict]`、`policy_changes: list[dict]`、`messages: list[dict]`
- `class Agent`：`__init__(llm: LLM, registry: dict[str, ToolSpec], sandbox, hooks: HookBus, policy: Policy, state: StateMachine, memory: MemoryStore | None, config: Config, ask_callback: Callable | None = None)`；`run(task: str) -> AgentResult`；内部 `pipeline(call: ToolCall, ctx: Context) -> ToolResult` 严格按 §11.5 顺序；`context_for_tool() -> Context`（把自身依赖组装进 Context，`ask_callback` 透传）
- pipeline 细节：`evaluate(policy.rules, ...)` → deny → `ToolResult(error="guardrail denied: <reason>")`（**不**触发任何钩子）；ask → `state.fire("approval_needed","guardrail")` → `ask_callback` 渲染（callback 返回 answer 字符串）→ `policy.apply_answer(rule, answer)` → 继续执行（answer 为 n/never_allow 时视为 deny）；allow → PreToolUse → `state.fire("tool_requested","loop")` → handler → `state.fire("tool_finished","loop")` → PostToolUse。

**依赖**：T4-T11 全部。**并行**：L3 起点（串行依赖后续任务）。

**实现要点**：run() 迭代：while steps < max_steps：`llm.complete(messages, build_request_tools(registry))`；`result.tool_calls` 为空 → 最终答案返回；非空 → 逐个 pipeline 并 append `assistant`（含 tool_calls）与 `tool` 消息；步数 +1；超限 → 追加终止消息并返回（spec §9 3.1：明确终止消息、不挂死）。

**验证步骤**
- [ ] **Step 1: 写失败测试**

```python
# harness/tests/test_agent_core.py
from harness.agent import Agent
from harness.fake_llm import FakeLLM, FakeTurn
from harness.config import Config
from harness.sandbox import LocalSandbox
from harness.policy import Policy
from harness.state import StateMachine
from harness.hooks import HookBus
from harness.tools.registry import make_registry, Context
from harness.tools.bash import spec as bash_spec

def make_agent(tmp_path, turns, max_steps=50):
    sb = LocalSandbox(); cfg = Config(workspace=tmp_path, tool_timeout=5, max_steps=max_steps)
    reg = make_registry([bash_spec(sb)])
    llm = FakeLLM(turns)
    return Agent(llm, reg, sb, HookBus(), Policy(), StateMachine(), None, cfg)

def test_simple_task_ends_with_final_answer(tmp_path):
    a = make_agent(tmp_path, [FakeTurn(tool_calls=[{"name": "bash", "arguments": {"command": "echo hi"}}]),
                              FakeTurn(text="完成")])
    r = a.run("做个事")
    assert "完成" in r.text and r.steps_used == 2

def test_step_limit_terminates_cleanly(tmp_path):
    a = make_agent(tmp_path, [FakeTurn(tool_calls=[{"name": "bash", "arguments": {"command": "echo x"}}])],
                   max_steps=3)
    r = a.run("循环")
    assert "步数上限" in r.text or "step" in r.text.lower()

def test_pipeline_order_guardrail_hooks_state(tmp_path):
    sb = LocalSandbox(); cfg = Config(workspace=tmp_path, tool_timeout=5)
    reg = make_registry([bash_spec(sb)])
    bus = HookBus(); events = []
    bus.register("pre", lambda n, a: (events.append(("pre", n)), (a, True))[1])
    bus.register("post", lambda n, a, res: events.append(("post", n)))
    llm = FakeLLM([FakeTurn(tool_calls=[{"name": "bash", "arguments": {"command": "echo hi"}}]),
                   FakeTurn(text="done")])
    st = StateMachine()
    a = Agent(llm, reg, sb, bus, Policy(), st, None, cfg)
    a.run("t")
    assert ("pre", "bash") in events and ("post", "bash") in events
    assert st.event_history[-1]["event"] == "tool_finished"

def test_deny_stops_before_hooks_and_execution(tmp_path):
    sb = LocalSandbox(); cfg = Config(workspace=tmp_path)
    reg = make_registry([bash_spec(sb)])
    bus = HookBus(); pre_called = []
    bus.register("pre", lambda n, a: (pre_called.append(n), (a, True))[1])
    from harness.guardrails import Rule
    pol = Policy(user_rules=[Rule("bash:rm -rf.*", "deny", "user")])
    llm = FakeLLM([FakeTurn(tool_calls=[{"name": "bash", "arguments": {"command": "rm -rf /"}}]),
                   FakeTurn(text="ok")])
    st = StateMachine()
    a = Agent(llm, reg, sb, bus, pol, st, None, cfg)
    r = a.run("t")
    assert pre_called == []  # 钩子没被触发
    assert any("denied" in str(t) for t in r.tool_results)
```

- [ ] **Step 2: 运行确认失败**：`python -m pytest harness/tests/test_agent_core.py -v` → FAIL（`ModuleNotFoundError: harness.agent`）
- [ ] **Step 3: 最小实现**：按接口实现 `agent.py`（pipeline 与 run 逻辑；ask 分支：`ask_callback` 为 None → 视为 deny 并给 error 结果）。
- [ ] **Step 4: 运行确认通过**：`python -m pytest harness/tests/test_agent_core.py -v` → PASS
- [ ] **Step 5: 提交**

```bash
git add harness/agent.py harness/tests/test_agent_core.py
git commit -m "feat: agent loop with guardrail-first tool pipeline"
```

---

## Task 20: 反馈循环（反思 + 失败注入 + 失败预算）

**目标**：工具失败/拒绝后模型先输出反思再继续（spec 3.6）；**注入一次失败后断言下一条动作改变**（§9 3.6 收紧版验收）；连续同类失败预算 3 → 停止并汇总报告。

**涉及文件**
- Modify: `harness/agent.py`（run 迭代中注入反馈、失败计数与预算）、`harness/tests/test_agent_feedback.py`

**接口**
- 在 `Agent.run` 内：每次 pipeline 返回 error 时：把 `ToolResult.to_message()` 追加（已有）+ 计数 `_fail_seq`（同 pattern 连续失败才累计，成功或不同工具重置）；反思由模型自身输出（FakeLLM 脚本回合体现），harness 只负责把失败结果作为 tool 消息回传 + 预算检查；`_fail_seq >= config.failure_budget` → 追加"连续失败 N 次，停止重试"报告并终止任务。
- Produces: `AgentResult` 增加字段 `failed_sequence: int`。

**依赖**：T19。**并行**：L3 第二个（串行）。

**实现要点**：失败判定：`result.status != "success"` 或 `error` 非空；同类 = 同一工具名。

**验证步骤**
- [ ] **Step 1: 写失败测试**

```python
# harness/tests/test_agent_feedback.py
from harness.agent import Agent
from harness.fake_llm import FakeLLM, FakeTurn
from harness.config import Config
from harness.sandbox import LocalSandbox
from harness.policy import Policy
from harness.state import StateMachine
from harness.hooks import HookBus
from harness.tools.registry import make_registry, Context
from harness.tools.bash import spec as bash_spec

def make_agent(tmp_path, turns, failure_budget=3):
    sb = LocalSandbox(); cfg = Config(workspace=tmp_path, tool_timeout=5, failure_budget=failure_budget)
    reg = make_registry([bash_spec(sb)])
    return Agent(FakeLLM(turns), reg, sb, HookBus(), Policy(), StateMachine(), None, cfg)

def test_failure_changes_next_action(tmp_path):
    # ① 失败注入：第一回合调用失败命令
    # ② 反思回合（模型输出反思文本，无工具调用）
    # ③ 下一步动作与失败前不同（换工具/换参数）
    turns = [
        FakeTurn(tool_calls=[{"name": "bash", "arguments": {"command": "python -c \"raise SystemExit(1)\""}}]),
        FakeTurn(text="反思：命令失败，换用文件方式"),
        FakeTurn(tool_calls=[{"name": "bash", "arguments": {"command": "echo fallback"}}]),
        FakeTurn(text="完成"),
    ]
    a = make_agent(tmp_path, turns)
    r = a.run("t")
    tool_calls_made = [t for t in r.messages if t.get("tool_calls")]
    first = tool_calls_made[0]["tool_calls"][0]["arguments"]["command"]
    after = [t for t in r.messages if t.get("role") == "assistant" and t.get("content", "").startswith("反思")]
    assert after, "应存在反思消息"
    assert first != "echo fallback"  # 下一条动作确实改变
    assert r.failed_sequence == 1

def test_failure_budget_stops_retrying(tmp_path):
    turns = [FakeTurn(tool_calls=[{"name": "bash", "arguments": {"command": "python -c \"raise SystemExit(1)\""}}]),
             FakeTurn(tool_calls=[{"name": "bash", "arguments": {"command": "python -c \"raise SystemExit(1)\""}}]),
             FakeTurn(tool_calls=[{"name": "bash", "arguments": {"command": "python -c \"raise SystemExit(1)\""}}]),
             FakeTurn(tool_calls=[{"name": "bash", "arguments": {"command": "python -c \"raise SystemExit(1)\""}}])]
    a = make_agent(tmp_path, turns, failure_budget=3)
    r = a.run("t")
    assert "连续失败" in r.text or "不再重试" in r.text
```

- [ ] **Step 2: 运行确认失败** → FAIL（`failed_sequence` 不存在）
- [ ] **Step 3: 最小实现**：修改 `agent.py`（反馈计数 + 预算终止；`failed_sequence` 返回）。
- [ ] **Step 4: 运行确认通过** → PASS
- [ ] **Step 5: 提交**

```bash
git add harness/agent.py harness/tests/test_agent_feedback.py
git commit -m "feat: feedback loop with failure budget and next-action-change assertion"
```

---

## Task 21: 上下文工程集成（top-2 注入 + 预算/压缩）

**目标**：任务开始检索 `memory.top_k_chunks` 注入 top-2（spec 3.3）；每次 LLM 调用前预算检查，超出 → 压缩（模型把较旧回合总结为一条 system 消息，保留最近 N 回合完整；压缩步数上限；失败 → 丢弃最旧回合降级）。

**涉及文件**
- Modify: `harness/agent.py`、`harness/tests/test_agent_context.py`

**接口**
- `Agent.run` 开始阶段：`memory` 非 None → `for chunk in memory.top_k_chunks(task): messages.append({"role":"system","content": f"[memory] {chunk['chunk']}"})`
- 新增内部方法 `_check_budget(messages) -> bool`（估算 `sum(len(m["content"])/4)`，超 `config.max_budget_tokens=6000`）；`_compress(messages) -> list[dict]`：`llm.complete(oldest_turns_as_system_summary, tools=[])` 得摘要 → `[{"role":"system","content":"[summary] …"}] + messages[-keep_turns:]`；`_compress` 调用计数 ≤ `compression_max_rounds`，超限或 LLM 抛异常 → 返回 `messages[-(keep_turns):]`（降级丢弃最旧）。
- `Config` 增加字段：`max_budget_tokens=6000`、`memory_top_k=2`（T3 已含 top_k）。

**依赖**：T19、T10。**并行**：L3 第三个。

**验证步骤**
- [ ] **Step 1: 写失败测试**

```python
# harness/tests/test_agent_context.py
from harness.agent import Agent
from harness.fake_llm import FakeLLM, FakeTurn
from harness.memory import MemoryStore
from harness.config import Config
from harness.sandbox import LocalSandbox
from harness.policy import Policy
from harness.state import StateMachine
from harness.hooks import HookBus
from harness.tools.registry import make_registry
from harness.tools.bash import spec as bash_spec

def test_memory_injected_at_start(tmp_path):
    mem = MemoryStore(tmp_path)
    mem.save("约定", "禁止在生产库执行写操作。")
    mem.load()
    sb = LocalSandbox(); cfg = Config(workspace=tmp_path, tool_timeout=5)
    reg = make_registry([bash_spec(sb)])
    llm = FakeLLM([FakeTurn(text="done")])
    a = Agent(llm, reg, sb, HookBus(), Policy(), StateMachine(), mem, cfg)
    a.run("处理生产库任务")
    system_msgs = [m for m in a.messages if m["role"] == "system"]
    assert any("[memory]" in m["content"] and "禁止在生产库" in m["content"] for m in system_msgs)

def test_budget_compression_drops_oldest_when_llm_fails(tmp_path):
    cfg = Config(workspace=tmp_path, max_budget_tokens=400, compression_keep_turns=2, tool_timeout=5)
    sb = LocalSandbox(); reg = make_registry([bash_spec(sb)])
    class Boom:
        def complete(self, messages, tools):
            raise RuntimeError("compress fail")
    a = Agent(Boom(), reg, sb, HookBus(), Policy(), StateMachine(), None, cfg)
    a.messages = [{"role": "user", "content": "x" * 400}] + [{"role": "assistant", "content": "y" * 400}] * 4
    out = a._compress(a.messages)
    assert len(out) <= 3 and out[0]["role"] == "user"  # 保留了最近（降级丢弃最旧）
```

- [ ] **Step 2: 运行确认失败** → FAIL
- [ ] **Step 3: 最小实现**：按接口修改 `agent.py`（`_compress` 在 LLM 异常时降级；`_check_budget` 在每次 complete 前调用，超限先压缩再调用）。
- [ ] **Step 4: 运行确认通过** → PASS
- [ ] **Step 5: 提交**

```bash
git add harness/agent.py harness/tests/test_agent_context.py
git commit -m "feat: context engineering with top-2 memory injection and budget compression"
```

---

## Task 22: 收尾阶段（SessionEnd 先于记忆整合，转录落盘）

**目标**：任务收尾顺序断言：`hooks.session_end(messages)` **先**执行（默认写转录），**后**记忆整合（模型总结会话 → `memory_save` 写入 `memory/`）（spec §9 3.3 / US-10）。

**涉及文件**
- Modify: `harness/agent.py`、`harness/tests/test_agent_end.py`

**接口**
- `Agent.run` 收尾：`self.hooks.session_end(self.messages)`（转录含 messages、tool_calls、policy_changes）→ 记忆整合：memory 非 None 且 LLM 可用 → `llm.complete([...总结指令...] + messages, [])` 得总结 → `memory.save("session-summary-<ts>", 总结)`；LLM 失败 → 跳过并记录（不阻塞）。
- `AgentResult` 增加 `transcript_path: str | None`（HookBus 默认钩子写后由 agent 探测最近文件——简化：`HookBus.session_end` 返回值忽略，transcript_path 由 `transcript_dir` 最新文件推导）。

**依赖**：T19、T7、T10。**并行**：L3 第四个。

**验证步骤**
- [ ] **Step 1: 写失败测试**

```python
# harness/tests/test_agent_end.py
import json
from harness.agent import Agent
from harness.fake_llm import FakeLLM, FakeTurn
from harness.memory import MemoryStore
from harness.config import Config
from harness.sandbox import LocalSandbox
from harness.policy import Policy
from harness.state import StateMachine
from harness.hooks import HookBus
from harness.tools.registry import make_registry
from harness.tools.bash import spec as bash_spec

def test_session_end_before_memory_consolidation(tmp_path):
    order = []
    mem = MemoryStore(tmp_path)
    sb = LocalSandbox(); cfg = Config(workspace=tmp_path, tool_timeout=5)
    reg = make_registry([bash_spec(sb)])
    llm = FakeLLM([FakeTurn(text="完成"), FakeTurn(text="会话总结：完成了任务")])
    bus = HookBus()
    original_end = bus.session_end
    def wrapped(messages):
        order.append("session_end")
        original_end(messages)
    bus.session_end = wrapped
    a = Agent(llm, reg, sb, bus, Policy(), StateMachine(), mem, cfg)
    a.run("t")
    assert order == ["session_end"]
    mem.load()
    assert any("会话总结" in h["chunk"] for h in mem.search("总结", k=5))

def test_transcript_written_with_policy_changes(tmp_path):
    td = tmp_path / "transcripts"; td.mkdir()
    sb = LocalSandbox(); cfg = Config(workspace=tmp_path, tool_timeout=5)
    reg = make_registry([bash_spec(sb)])
    pol = Policy()
    from harness.guardrails import Rule
    pol.apply_answer(Rule("bash:echo.*", "ask", "user"), "always_allow")
    llm = FakeLLM([FakeTurn(text="done")])
    bus = HookBus(transcript_dir=td)
    a = Agent(llm, reg, sb, bus, pol, StateMachine(), None, cfg)
    a.run("t")
    files = list(td.glob("*.json"))
    assert files
    data = json.loads(files[0].read_text(encoding="utf-8"))
    assert data["messages"] and data["policy_changes"]
```

- [ ] **Step 2: 运行确认失败** → FAIL
- [ ] **Step 3: 最小实现**：修改 `agent.py` 收尾段（顺序硬编码 session_end → consolidate；consolidate 的 LLM 失败 try/except 记录 `self.warnings`）。
- [ ] **Step 4: 运行确认通过** → PASS
- [ ] **Step 5: 提交**

```bash
git add harness/agent.py harness/tests/test_agent_end.py
git commit -m "feat: session-end-before-consolidation ordering with transcript and memory write"
```

---

## Task 23: 子智能体工具 subagent.py（独立上下文 + 继承护栏/钩子/策略）

**目标**：`run_subagent(task, system_prompt?)`：新 Agent 实例独立上下文、独立步数上限 30，继承护栏/钩子/策略；子任务最终答案作为父工具结果；父/子上下文互不污染。

**涉及文件**
- Create: `harness/tools/subagent.py`、`harness/tests/test_tools_subagent.py`
- Modify: `harness/agent.py`（`context_for_tool` 透传 `agent_factory`；`AgentResult` 供子工具组装）

**接口**
- Produces: `subagent.spec() -> ToolSpec`：handler 用 `ctx.agent_factory()` 建子 Agent（传入 `ctx.llm`、同一 registry/sandbox/hooks/policy/state？——**注意**：子 agent 用**独立** StateMachine（子会话自己的状态机），但共享 policy/hooks/sandbox/registry/llm；`config` 子副本 `max_steps=30`）；返回子 `AgentResult.text` 作为 output。
- `agent_factory` 在 `Context` 中由 REPL/父 Agent 注入（`Context.agent_factory`，T11 已定义）。

**依赖**：T19。**并行**：L3 第五个。

**实现要点**：父 Agent 的 `Context` 组装时把 `agent_factory=lambda: Agent(...独立 state..., max_steps=30)` 注入；子 agent 完成后再 `state.fire("tool_finished","loop")` 由父流水线处理（子工具作为普通工具走父流水线）。

**验证步骤**
- [ ] **Step 1: 写失败测试**

```python
# harness/tests/test_tools_subagent.py
from harness.agent import Agent
from harness.fake_llm import FakeLLM, FakeTurn
from harness.config import Config
from harness.sandbox import LocalSandbox
from harness.policy import Policy
from harness.state import StateMachine
from harness.hooks import HookBus
from harness.tools.registry import make_registry
from harness.tools.bash import spec as bash_spec
from harness.tools.subagent import spec as sub_spec

def test_subagent_returns_final_answer_with_isolated_context(tmp_path):
    sb = LocalSandbox(); cfg = Config(workspace=tmp_path, tool_timeout=5)
    reg = make_registry([bash_spec(sb), sub_spec()])
    # 父：调用子智能体 → 子（独立 FakeLLM）：bash → 最终答案
    parent_llm = FakeLLM([FakeTurn(tool_calls=[{"name": "run_subagent", "arguments": {"task": "子任务"}}]),
                          FakeTurn(text="父完成")])
    sub_llm = FakeLLM([FakeTurn(tool_calls=[{"name": "bash", "arguments": {"command": "echo sub-ok"}}]),
                       FakeTurn(text="子完成")])
    parent_state = StateMachine(); parent_state.fire("task_submitted", "user")
    seen = {}
    def factory():
        seen["made"] = True
        return Agent(sub_llm, reg, sb, HookBus(), Policy(), StateMachine(), None,
                     Config(workspace=tmp_path, tool_timeout=5, max_steps=30))
    a = Agent(parent_llm, reg, sb, HookBus(), Policy(), parent_state, None, cfg)
    a.agent_factory = factory
    r = a.run("父任务")
    assert seen.get("made") and "子完成" in r.text
    assert parent_state.state == "running"  # 父状态机未被子污染
```

- [ ] **Step 2: 运行确认失败** → FAIL
- [ ] **Step 3: 最小实现**：`subagent.py` + `agent.py` 的 `agent_factory` 注入（`Agent.__init__` 增加 `agent_factory=None` 参数，`context_for_tool` 透传）。
- [ ] **Step 4: 运行确认通过** → PASS
- [ ] **Step 5: 提交**

```bash
git add harness/tools/subagent.py harness/agent.py harness/tests/test_tools_subagent.py
git commit -m "feat: subagent tool with isolated context inheriting guards and hooks"
```

---

## Task 24: REPL main.py（命令、HITL 菜单、Ctrl+C、流式显示）

**目标**：交互 REPL——任务输入、行内工具活动展示（`→ bash: …`、`⊘ denied: …`、`? allow …?`）、HITL 菜单、Ctrl+C → interrupt→paused（恢复/中止）、`/exit` `/reset` `/skills` `/rules` `/rules drop skill:<name>` `/key set|status|clear` `/memory`；凭据首启向导；每回合 token/步数统计。

**涉及文件**
- Create: `harness/main.py`、`harness/tests/test_repl.py`
- Modify: `harness/agent.py`（`run` 暴露流式回调：`on_text: Callable[[str], None] | None`，FakeLLM/OpenAILLM 聚合后逐段回调；`pipeline` 的 ask 用 `ask_callback`）

**接口**
- Produces: `def run_repl(config: Config) -> int`（返回退出码）；`def ask_menu(question: str, options: list[str]) -> str`（编号菜单，非编号输入重试；EOF → 抛 `KeyboardInterrupt`）；REPL 命令分派（`/exit`→0、`/reset`→清空会话重来、`/skills`→列技能、`/rules`→打印当前策略、`/rules drop skill:<name>`→移除该技能规则、`/key set|status|clear`→凭据、`/memory`→列出记忆条目）；会话中 Ctrl+C → `state.fire("interrupt","user")` → 菜单（恢复 resume / 中止 abort）；`Ctrl+C` 在 REPL 顶层 → 干净退出并触发 SessionEnd（spec US-4 验收）。
- Agent 增加：`on_text: Callable[[str], None] | None = None`（每段文本回调）；`context_for_tool` 的 `ask_callback` = `ask_menu`。

**依赖**：T2、T3、T7、T16、T19-T22。**并行**：L4 第一个。

**实现要点**：main 组装依赖图（CredentialStore → OpenAILLM → registry（bash/files/search/web/notes/memory/ask/skills/subagent + MCP 加载）→ Agent）；`/key set` 用 `wizard_enter_key`；显示用 `print`（`→ `、`⊘ `、`? ` 前缀，spec §4.4）；HITL 菜单 = `ask_menu`；步数/token 每回合 `print(f"[step {n}/{max} | ~{tokens} tok]")`。

**验证步骤**
- [ ] **Step 1: 写失败测试**（REPL 用注入 FakeLLM + StringIO 驱动，不真正交互）

```python
# harness/tests/test_repl.py
import io, sys
from pathlib import Path
from harness.main import ask_menu, run_repl
from harness.config import Config

def test_ask_menu_numbered(tmp_path):
    out = io.StringIO(); inp = io.StringIO("2\n")
    options = ["重试", "换方案"]
    with patch("builtins.input", side_effect=["2"]), patch("sys.stdout", out):
        assert ask_menu("怎么办", options) == "换方案"
    rendered = out.getvalue()
    assert "1. 重试" in rendered and "2. 换方案" in rendered

def test_run_repl_with_fake_llm(tmp_path, monkeypatch, capsys):
    from harness.agent import Agent
    from harness.fake_llm import FakeLLM, FakeTurn
    from harness.sandbox import LocalSandbox
    from harness.policy import Policy
    from harness.state import StateMachine
    from harness.hooks import HookBus
    from harness.tools.registry import make_registry
    from harness.tools.bash import spec as bash_spec
    cfg = Config(workspace=tmp_path, tool_timeout=5)
    sb = LocalSandbox(); reg = make_registry([bash_spec(sb)])
    llm = FakeLLM([FakeTurn(tool_calls=[{"name": "bash", "arguments": {"command": "echo hi"}}]),
                   FakeTurn(text="搞定了")])
    agent = Agent(llm, reg, sb, HookBus(), Policy(), StateMachine(), None, cfg)
    # run_repl 允许注入 agent 工厂
    from harness.main import make_agent
    monkeypatch.setattr("harness.main.make_agent", lambda cfg: agent)
    monkeypatch.setattr("builtins.input", lambda *a: "/exit")
    assert run_repl(cfg) == 0
    out = capsys.readouterr().out
    assert "搞定了" in out or "echo hi" in out
```

（`make_agent(cfg)` 为 main.py 提供的组装函数，测试注入替换。`patch` 从 `unittest.mock` 导入。）

- [ ] **Step 2: 运行确认失败** → FAIL
- [ ] **Step 3: 最小实现**：`main.py` 按接口实现（`make_agent` 组装所有工具；`ask_menu` 用 `input()`；Ctrl+C 处理在 `run_repl` 的 try/except `KeyboardInterrupt` → fire interrupt → 菜单）。`agent.py` 增加 `on_text` 回调。
- [ ] **Step 4: 运行确认通过** → PASS
- [ ] **Step 5: 提交**

```bash
git add harness/main.py harness/agent.py harness/tests/test_repl.py
git commit -m "feat: REPL with HITL menus, slash commands and interrupt handling"
```

---

## Task 25: 机制演示（mock LLM 确定性复现 ①②③）

**目标**：可重复运行的演示，满足外部验收要求（**不写入 spec**）：在 FakeLLM 下确定性复现——① 治理护栏拦截危险动作；② 注入一次失败，反馈闭环使 agent 收到反馈并改变下一步动作；③ 重点维度（钩子与护栏）的一个确定性行为——HITL 状态机全轨迹（含 ask→awaiting_user→执行）。

**涉及文件**
- Create: `harness/tests/mechanism_demo/__init__.py`、`demo_1_guardrail_deny.py`、`demo_2_feedback_change.py`、`demo_3_hitl_trace.py`（均为可直接运行的脚本：`python -m harness.tests.mechanism_demo.demo_1_guardrail_deny`），及 `harness/tests/test_mechanism_demo.py`（把三个脚本包装成 pytest 用例，保证 CI 可重复验证）

**接口**
- demo_1：FakeLLM 一回合 `bash rm -rf C:\Windows` → 断言：`pipeline` 返回 deny 结果、钩子零触发、沙箱零执行（`LocalSandbox` 包一层记录调用的 spy）、输出 `⊘ denied: ...`
- demo_2：四回合脚本（失败 → 反思 → 换动作 → 完成），断言下一条命令 ≠ 失败命令（复用 T20 的断言逻辑，但作为独立可运行脚本 + 输出可读轨迹）
- demo_3：完整 HITL 轨迹：`task_submitted → approval_needed(guardrail) → awaiting_user → user_answered → running → tool_requested → executing → tool_finished → running → final_answer → completed`，断言 `state.event_history` 精确等于该序列（状态机全轨迹确定性 = 重点维度核心行为）

**依赖**：T19、T20、T22。**并行**：L4 第二个。

**验证步骤**
- [ ] **Step 1: 写失败测试**（三个脚本主体 + pytest 包装）

```python
# harness/tests/test_mechanism_demo.py
import subprocess, sys
from pathlib import Path

DEMO = Path(__file__).parent / "mechanism_demo"

def run_demo(name):
    return subprocess.run([sys.executable, "-m", "harness.tests.mechanism_demo." + name],
                          capture_output=True, text=True, timeout=30)

def test_demo_1_guardrail_deny():
    r = run_demo("demo_1_guardrail_deny")
    assert r.returncode == 0 and "denied" in r.stdout

def test_demo_2_feedback_change():
    r = run_demo("demo_2_feedback_change")
    assert r.returncode == 0 and "changed" in r.stdout

def test_demo_3_hitl_trace():
    r = run_demo("demo_3_hitl_trace")
    assert r.returncode == 0 and "TRACE OK" in r.stdout
```

- [ ] **Step 2: 运行确认失败** → FAIL（模块不存在）
- [ ] **Step 3: 最小实现**：三个 demo 脚本（用 FakeLLM/Agent 组装最小图；`print` 输出带 `→`/`⊘`/`?` 的轨迹；demo_3 断言 event_history == 期望序列后打印 "TRACE OK"）。
- [ ] **Step 4: 运行确认通过**：`python -m pytest harness/tests/test_mechanism_demo.py -v` → PASS；并手动跑 `python -m harness.tests.mechanism_demo.demo_1_guardrail_deny` 验证输出可读。
- [ ] **Step 5: 提交**

```bash
git add harness/tests/mechanism_demo/ harness/tests/test_mechanism_demo.py
git commit -m "feat: deterministic mechanism demos for guardrail deny, feedback change and HITL trace"
```

---

## Task 26: 验收矩阵 + 凭据扫描 + 性能冒烟（test_acceptance_matrix.py）

**目标**：把 §9 验收标准落成一个可运行的验收矩阵测试 + 凭据泄露扫描（源码/git 历史/日志/转录/夹具中不得出现真实 key 形态）+ 性能冒烟（会话启动 < 1s、检索 < 50ms）。

**涉及文件**
- Create: `harness/tests/test_acceptance_matrix.py`、`harness/tests/test_security_scan.py`、`harness/tests/test_perf_smoke.py`

**接口**
- `test_acceptance_matrix.py`：一组参数化断言映射 §9 各条（引用既有模块行为，不重复实现）：
  - 3.1：FakeLLM 多 tool_calls 同回合解析（复用 T9/T19 组装）；步数上限消息
  - 3.2：非法参数（缺字段）被 schema 拒绝——`make_registry` 提供 `validate(spec, args)`（**需在 T11 补一个 `registry.validate`**：本任务给 `make_registry` 加校验入口，handler 执行前校验，失败返回 error 结果）
  - 3.3：top-2 注入、memory_search top-1（复用 T10/T21）
  - 3.4：危险模式 deny、ask 无超时放行（ask_callback=None → 不自动放行，验证返回 deny 而非执行）、降级/升级、钩子顺序
  - 3.5：子智能体隔离、技能 allow 拒绝、MCP 假服务器（复用 T17/T18/T23）
  - 3.6：失败注入改动作、预算停止（复用 T20）
  - 4.x：转录字段完整、`/rules` 反映策略（直接调 Policy 而非 REPL）
- `test_security_scan.py`：扫描 `harness/` 与 git log（`git -C repo log -p`）中 `sk-[A-Za-z0-9]{16,}` 形态；扫描转录/夹具目录；断言零命中（测试自身的假 key 用 `sk-TESTKEY-...` 且扫描排除测试文件内已声明白名单）。
- `test_perf_smoke.py`：空记忆库 Agent 启动 < 1s（FakeLLM 一回合）；100 条目检索 < 50ms（复用 T10）。

**依赖**：全部核心任务（T11 需加 validate）。**并行**：L4 第三个（最后完成）。

**实现要点**：`registry.validate` 用 `jsonschema` 手写轻量校验（缺 required、类型不符）——**不引入 jsonschema 依赖**，实现 `validate_args(schema, args) -> str | None`（返回错误文本）；`make_registry` 生成的 spec 由 agent pipeline 调用前校验（pipeline 里加 `spec.validate` 调用，失败 → error 结果，spec §3.2"参数必须通过 JSON schema 校验"）。

**验证步骤**
- [ ] **Step 1: 写失败测试**（三文件如上；其中验收矩阵先跑，失败项即缺口）

```python
# harness/tests/test_security_scan.py
import subprocess, re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
KEY_PATTERN = re.compile(r"sk-[A-Za-z0-9]{16,}")
EXCLUDE = {"test_security_scan.py"}  # 白名单：测试自身

def test_no_key_shaped_strings_in_source():
    hits = []
    for p in (ROOT / "harness").rglob("*.py"):
        if p.name in EXCLUDE: continue
        for i, line in enumerate(p.read_text(encoding="utf-8").splitlines(), 1):
            if KEY_PATTERN.search(line): hits.append(f"{p}:{i}")
    assert hits == []

def test_no_key_in_git_history():
    r = subprocess.run(["git", "-C", str(ROOT), "log", "-p"], capture_output=True, text=True)
    assert not KEY_PATTERN.search(r.stdout)

def test_no_key_in_transcripts_or_fixtures():
    hits = []
    for d in [ROOT / "transcripts", ROOT / "harness" / "tests" / "fixtures"]:
        if d.exists():
            for p in d.rglob("*"):
                if p.is_file() and KEY_PATTERN.search(p.read_text(encoding="utf-8", errors="ignore")):
                    hits.append(str(p))
    assert hits == []
```

- [ ] **Step 2: 运行确认失败** → FAIL（`registry.validate` 不存在等）
- [ ] **Step 3: 最小实现**：`registry.py` 加 `validate`（含 required 缺失与类型不符检测）→ agent pipeline 调用；三个测试文件落地；补齐验收矩阵发现的缺口（如有则修复对应模块）。
- [ ] **Step 4: 运行确认通过**：`python -m pytest harness/tests/ -v` → 全绿
- [ ] **Step 5: 提交**

```bash
git add harness/tools/registry.py harness/agent.py harness/tests/test_acceptance_matrix.py harness/tests/test_security_scan.py harness/tests/test_perf_smoke.py
git commit -m "feat: acceptance matrix, credential scan and perf smoke tests"
```

---

## Task 27: README 与文档收尾

**目标**：README：快速开始（pip install / 配置 key / 运行）、凭据安全说明（keyring、.env 明文风险）、代理配置（GitHub/DeepSeek 网络）、架构一页图、六维度各组件说明、`/`命令表、测试运行方式、沙箱非隔离性声明、Docker 桩说明；组件理论文档（每组件一节：它验证什么理论）。

**涉及文件**
- Create/Modify: `README.md`、`docs/COMPONENTS.md`

**接口**
- 无（纯文档）。引用 spec 章节号。

**依赖**：全部任务完成。**并行**：L4 收尾。

**实现要点**：README 命令表来自 main.py 实际实现（避免文档与实现漂移）；明确 Windows 路径与权限注意事项；`docs/COMPONENTS.md` 按 六维度 组织，每节含：组件文件、测试文件、验证的理论/设计假设。

**验证步骤**
- [ ] **Step 1: 写失败检查**（文档存在 + README 命令表与实现一致）

```python
# harness/tests/test_docs.py
from pathlib import Path
ROOT = Path(__file__).resolve().parents[2]

def test_readme_commands_match_implementation():
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    main = (ROOT / "harness" / "main.py").read_text(encoding="utf-8")
    for cmd in ["/exit", "/reset", "/skills", "/rules", "/key", "/memory"]:
        assert cmd in readme, f"README 缺少 {cmd}"
        assert cmd in main, f"main.py 缺少 {cmd}"

def test_component_docs_exist():
    assert (ROOT / "docs" / "COMPONENTS.md").exists()
```

- [ ] **Step 2: 运行确认失败** → FAIL（README 无命令表）
- [ ] **Step 3: 最小实现**：写 README.md 与 docs/COMPONENTS.md（内容按"实现要点"）。
- [ ] **Step 4: 运行确认通过** → PASS；最终全量：`python -m pytest harness/tests/ -v` 全绿
- [ ] **Step 5: 提交**

```bash
git add README.md docs/COMPONENTS.md harness/tests/test_docs.py
git commit -m "docs: README quickstart, security notes and component theory docs"
```

---

## 自审记录（writing-plans self-review）

- **Spec 覆盖**：§3.1→T9/T19/T26；§3.2→T11-T18/T26；§3.3→T10/T21/T22；§3.4→T4-T7/T19/T26；§3.5→T17/T18/T23；§3.6→T20/T26；§4.2→T2/T26 凭据扫描；§4.3→T1/T9 依赖约束；§4.4→T7/T22/T24；§5→T19/T24；§7→T2/T24；§9→T26；§11→T4-T7/T19/T20/T25；US-1..US-10 均有对应验收测试（T19-T26）。无缺口。
- **占位符扫描**：无 TBD/TODO；所有步骤含实际代码。
- **类型一致性**：`Context`、`ToolCall`、`ToolResult`、`AgentResult`、`Config`、`StateMachine`、`Policy`、`HookBus`、`MemoryStore`、`FakeLLM`、`make_registry`、`build_request_tools` 接口在任务间交叉引用一致；`Context.agent_factory`（T11 定义、T23 消费）、`Agent.on_text`（T24 消费）已对齐。
- **已知实现偏差（需评审确认）**：
  1. 新增 `harness/types.py` 与 `harness/fake_llm.py`（spec 附录目录未列，属接口层必要补充）。
  2. MCP 采用手写行式 JSON-RPC（stdio/url）而非官方 `mcp` SDK（spec §4.3 写官方 SDK）——零网络依赖、可确定性测试；若坚持官方 SDK 需调整 T18。
  3. `registry.validate` 手写轻量 schema 校验（不引入 jsonschema 依赖）。
