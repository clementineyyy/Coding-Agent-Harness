# Coding Agent Harness

一个真实的编码智能体框架（Python 3.11+，Windows/Linux）：以 REPL 交互为核心，
内置治理护栏（deny/ask 审批）、自适应策略、TF-IDF 记忆、上下文预算与压缩、
HITL 状态机与工具执行沙箱；全量测试离线、确定性可复现（FakeLLM +
MockTransport），已发布至 PyPI。

设计规格见 `docs/superpowers/specs/SPEC.md`（下文以 `§x.y` 引用章节号）。

## 组件图（SPEC §5.1）

![组件图](docs/superpowers/specs/assets/Gemini_Generated_Image_y9hi41y9hi41y9hi.jpg)

职责划分：Agent 只负责循环与状态；工具流水线只负责"一次调用"的判定-执行；
护栏/策略/钩子/沙箱各自单一职责；状态机是交互主轴。完整数据流见 SPEC §5.2。

## 目录结构

```
Coding-Agent-Harness/
├── harness/                    # 核心包（运行时）
│   ├── main.py                 # REPL 入口（console script `cah`）
│   ├── agent.py                # 任务循环：记忆检索 → 迭代 → 收尾整合
│   ├── llm.py                  # OpenAI 兼容客户端（流式 / tool_calls）
│   ├── credentials.py          # 凭据：keyring → .env → 向导
│   ├── config.py               # Config 配置（支持 TOML 加载）
│   ├── guardrails.py           # 护栏：内置 deny 清单 + 判定
│   ├── policy.py               # 自适应策略（ask 升降级、/rules）
│   ├── state.py                # 状态机（HITL 交互主轴）
│   ├── hooks.py / transcript.py# 钩子总线 / SessionEnd 转录
│   ├── memory.py               # TF-IDF 记忆存储与检索
│   ├── registry.py             # 工具注册表（内置 + MCP）
│   ├── sandbox.py              # LocalSandbox / DockerSandbox
│   ├── mcp.py                  # MCP 客户端（stdio / url）
│   ├── fake_llm.py             # 离线测试用 FakeLLM
│   └── tools/                  # 内置工具：bash / files / search / web /
│                               #   notes / memory / skills / subagent / ask
├── harness/tests/              # 全部测试（离线、确定性）
│   ├── test_*.py               # 组件单测 + 验收矩阵（§9）+ 安全扫描
│   ├── fixtures/               # 假 MCP 服务器、技能夹具
│   └── mechanism_demo/         # 机制演示脚本（demo ①②③，make demo）
├── scripts/                    # 辅助脚本（如 verify_live_llm.py 真实 LLM 验证）
├── docs/superpowers/specs/     # 设计规格：SPEC.md / PLAN.md / AGENT_LOG.md
├── .github/workflows/          # ci.yml（test+build）/ publish.yml（PyPI 发布）
├── Makefile                    # make test / demo / install
├── pyproject.toml              # 包定义（[project.scripts] cah）
└── README.md
```

运行时在工作区生成（已被 `.gitignore` 排除）：`memory/`（记忆）、
`skills/`（技能）、`transcripts/`（转录）、`.env`（可选凭据）。

## 快速开始

1. **安装**（PyPI 分发，任选其一）：

   ```bash
   pip install nju-coding-agent-harness        # PyPI 正式发布
   pip install -e ".[dev]"                     # 源码分发（项目根目录）
   ```

2. **配置 API Key**：首次运行时会自动进入配置向导（`getpass` 隐藏输入，
   保存到系统凭据库）；也可以在 REPL 内用 `/key set` 随时配置（见下文
   "凭据安全"）。

3. **运行**：

   ```bash
   cah                       # 等价 python -m harness.main
   ```

   提示符 `> ` 下直接输入任务（例如"修复 main.py 里的 bug"）；**首次输入
   （即使以 `/` 开头）一律视为任务**。REPL 顶部 `Ctrl+C` 干净退出并触发
   SessionEnd 钩子；任务运行中 `Ctrl+C` 弹出暂停菜单（resume / abort）。

## 安装与分发命令

- **PyPI 安装**（推荐，主分发形态）：

  ```bash
  pip install nju-coding-agent-harness
  ```

- **源码分发**（获取最新/参与开发）：

  ```bash
  git clone https://github.com/clementineyyy/Coding-Agent-Harness.git
  cd Coding-Agent-Harness
  pip install -e ".[dev]"
  ```

- **发布新版**（维护者，Trusted Publishing 免 token）：

  ```bash
  # 1) pyproject.toml 升版本号（与 tag 同步，否则 PyPI 拒绝重复上传）
  # 2) 打标签并推送，GitHub Actions publish.yml 自动构建并发布到 PyPI
  git tag vX.Y.Z
  git push origin vX.Y.Z
  ```

## 凭据安全

- **来源优先级**：keyring（Windows Credential Manager，服务名
  `coding-agent-harness`）→ 项目根目录 `.env` 文件（`DEEPSEEK_API_KEY=...`）
  → 首次运行向导。
- **首选 keyring**：操作系统加密存储，凭据不出本机。`/key set` 交互录入
  （隐藏输入）后可选"验证密钥"（调 `{base_url}/models` 轻量确认，通过后
  才写入 keyring 并记录验证时间；失败提示重输、不落盘）；`/key clear`
  删除 keyring 凭据（来源为 `.env` 时只提示手动删除）；`/key status` 只回显
  "是否已配置 / 来源 / 验证时间"，**绝不回显明文**。
- **`.env` 明文风险**：`.env` 文件是本地明文（`DEEPSEEK_API_KEY=...`），
  且其中的值会进入进程环境、对同一用户的其他进程可见；不要提交进 Git
  （仓库已通过 `.gitignore` 排除 `.env`，凭据扫描测试
  `harness/tests/test_security_scan.py` 会检查 key 不落入源码/历史/转录）。
  使用 `.env` 是备选方案，请确保文件权限收紧。
- **兜底安全**：key 永不写入日志、转录、记忆或策略文件。

## 代理配置（GitHub / DeepSeek，Windows）

- **DeepSeek API**：默认直连 `https://api.deepseek.com`（HTTPS）。需要
  代理时，为 `openai`/`httpx` 设置环境变量即可：

  ```powershell
  $env:HTTPS_PROXY = "http://127.0.0.1:7890"
  $env:HTTP_PROXY  = "http://127.0.0.1:7890"
  ```

  （PowerShell 中设置环境变量仅对当前会话有效，不会进入 shell history；
  请勿用 `export` 方式写入 key，那会进入 shell history。）
- **GitHub**（克隆仓库、拉取技能时）：给 git 配代理

  ```bash
  git config --global http.proxy http://127.0.0.1:7890
  git config --global https.proxy http://127.0.0.1:7890
  ```

- **Windows 注意**：命令执行基于系统 shell；若在工作区使用 PowerShell
  脚本或路径含空格/中文，注意引号与编码（项目文件统一 UTF-8）。

## 配置（harness/config.py）

`Config` dataclass 定义全部配置字段（`Config.load(path)` 支持 TOML
配置文件加载）：

| 字段 | 默认值 | 含义 |
|---|---|---|
| `model` | `deepseek-chat` | 模型名 |
| `base_url` | `https://api.deepseek.com` | OpenAI 兼容端点 |
| `max_steps` | `50` | 每任务步数上限 |
| `failure_budget` | `3` | 同类工具连续失败预算（§3.6） |
| `tool_timeout` | `30` | 工具执行超时（秒） |
| `memory_top_k` | `2` | 任务启动时检索注入的记忆块数（§3.3） |
| `max_budget_tokens` | `6000` | 上下文预算，超出先压缩（§3.3） |
| `compression_keep_turns` | `10` | 压缩保留的最近回合数 |
| `compression_max_rounds` | `3` | 单任务压缩轮数上限 |
| `max_output_bytes` | `51200` | 工具输出截断上限 |
| `workspace` | 当前目录 | 工作区（文件/记忆/技能/转录根） |
| `mcp_servers` | `[]` | MCP 服务器列表（§5.3） |

**配置优先级**：TOML 配置文件（`cah --config config.toml`）> 环境变量 /
`.env` 文件 > 默认值。

**适配任意 OpenAI 兼容平台**（无需改源码）：key 之外，只需覆盖
`base_url` 与 `model`。在项目根目录 `.env`（或环境变量）中配置：

| 平台 | `.env` 内容 |
|---|---|
| DeepSeek 官方 | `DEEPSEEK_API_KEY=sk-...`（默认 base_url/model 即可） |
| 硅基流动 | 再加 `DEEPSEEK_BASE_URL=https://api.siliconflow.cn/v1`、`DEEPSEEK_MODEL=deepseek-ai/DeepSeek-V3` |
| 其他 OpenAI 兼容平台 | 再加对应平台的 `base_url` / `model` |

或用 TOML 文件（环境变量同样支持）：

```toml
# config.toml
model = "deepseek-ai/DeepSeek-V3"
base_url = "https://api.siliconflow.cn/v1"
```

```bash
cah --config config.toml
```

## REPL 命令表

实现于 `harness/main.py`（`/help` 输出与之对应）：

| 命令 | 行为 |
|---|---|
| `/exit` | 退出 REPL（返回 0） |
| `/reset` | 重置会话（重建 Agent，清空上下文与状态）；失败打印"重置失败" |
| `/skills` | 列出工作区 `skills/` 下含 `SKILL.md` 的技能 |
| `/rules` | 显示策略规则表：`pattern -> action (source)` |
| `/rules drop skill:<name>` | 移除指定技能注入的规则 |
| `/key set` | 交互录入 API Key 并保存到 keyring，随后重新初始化会话 |
| `/key status` | 显示配置状态（是否已配置 / 来源 / 验证时间） |
| `/key clear` | 清除 keyring 中的 API Key |
| `/memory` | 列出工作区 `memory/` 下的记忆文件 |
| `/help` | 命令摘要 |

交互行为（与实现一致）：

- **首次输入即任务**：第一个非空输入（包括以 `/` 开头的字符串）作为任务执行。
- **任务中 Ctrl+C**：状态机 `interrupt → paused`，弹出编号菜单
  `1. resume / 2. abort`；EOF 视为 abort。选择 abort → `terminated`；
  选择 resume → 从暂停处继续（仅允许恢复一次）。
- **REPL 顶层 Ctrl+C / EOF**：打印换行、触发 SessionEnd 钩子（写转录）后退出。
- **护栏 ask**：打印 `? 问题` + 编号选项，输入非编号数字重试。
- **任务收尾**：逐条回显工具调用 `→ name: args`（失败为 `⊘ name: error`），
  最后打印 `[step N/max | ~T tok]` 步数与近似 token 统计。
- **流式输出**：模型文本通过 `on_text` 实时打印，无整轮缓冲（§3.1）。
- **API 失败**（密钥错误 / 限流 / 网络）：打印明确提示，**会话保持存活**，
  可继续输入任务或 `/key set`。

## 六维度组件（§3）

| 维度 | 组件 | 验证要点 |
|---|---|---|
| 治理护栏 | `guardrails.py` / `policy.py` / `state.py`（§3.4 §11.2 §11.4） | 护栏先行、ask 无超时放行、自适应升降级 |
| 安全沙箱 | `sandbox.py`（§11.3） | 超时/截断、docker 隔离；**local 非隔离（见下）** |
| 记忆 | `memory.py`（§3.3） | 纯标准库 TF-IDF、top-k 注入、收尾整合 |
| 上下文工程 | `agent.py`（预算/压缩）+ `llm.py`（§3.1 §3.3） | 超预算先压缩、保留最近 N 回合、轮数上限 |
| 人机协同 HITL | `main.py` / `state.py` / `tools/ask.py`（§11.4） | interrupt→paused、awaiting_user 双来源 |
| 反馈闭环 | `agent.py`（失败预算）（§3.6） | 连续失败 3 次停止、错误回灌可修正 |

配套能力：工具注册表 `registry.py`、内置工具 `tools/`（bash/files/search/web/
notes/memory/skills/subagent/ask）、MCP 客户端 `mcp.py`、钩子 `hooks.py`、
转录 `transcript.py`、凭据 `credentials.py`、LLM 客户端 `llm.py`。

## 沙箱非隔离性声明（重要，§11.3）

**`LocalSandbox`（默认后端）不是安全边界**——它在宿主上直接以子进程执行
shell 命令，隔离由**护栏**（危险模式 deny / ask）与**路径包含性检查**
（工作区外路径 deny）承担第一道防线。若需要真正的进程/文件系统隔离，
请配置 **DockerSandbox** 后端。

## Docker 后端（可选，默认 local）

- 通过配置切换沙箱后端；docker 后端用 `docker run --rm` 执行 bash，默认
  `--network=none`（无网络），以 `-v <workspace>:/workspace` 挂载工作区，
  容器内无法破坏宿主文件系统、读不到宿主凭据。
- 镜像默认 `python:3.11-slim`，需预装工具链（python/git 等）。
- 未安装 Docker 或 daemon 未运行时快速报错，可回退 local。
- Windows：需 Docker Desktop 并保持运行；挂载路径请使用绝对路径。

## 安全边界说明

安全由**多层边界叠加**，请勿依赖任何单层：

| 边界 | 说明 |
|---|---|
| 护栏（第一道防线） | 内置 deny 清单拦截**无正当用途的破坏操作**（`rm -rf` 系统根目录、`format`、强删等）；敏感但可能正当的操作走 **ask 审批**（HITL 菜单），批准/拒绝沉淀为策略规则（§11.2） |
| 路径包含性检查 | 文件类工具对工作区外路径直接 deny（§11.2） |
| 沙箱（local 默认） | **不是安全边界**：在宿主直接以子进程执行，仅做超时与输出截断（§11.3） |
| 沙箱（docker 可选） | 真隔离：默认 `--network=none`、仅挂载工作区、容器内读不到宿主凭据与文件系统 |
| 网络闸门 | 默认关网（`network_enabled=false`）；开启后网络类工具/命令走 ask 审批（§11.3） |
| 凭据边界 | keyring 加密存储优先，`.env` 明文备选；key **永不写入**日志/转录/记忆/策略；`/key status` 绝不回显明文 |
| 数据边界 | 转录写工作区 `transcripts/`、记忆写 `memory/`（均被 `.gitignore` 排除）；上下文超预算自动压缩，防溢出 |

**威胁模型假设**：本地用户自身可信；护栏防的是 **agent 失控 / 误操作**，
不是防恶意本地进程——若需对抗不可信输入，请务必启用 Docker 沙箱后端。

## 测试

[![CI](https://github.com/clementineyyy/Coding-Agent-Harness/actions/workflows/ci.yml/badge.svg)](https://github.com/clementineyyy/Coding-Agent-Harness/actions/workflows/ci.yml)

**一键运行**（GitHub Actions CI 与本地使用同一命令）：

```bash
make test
```

- `make test` 自动完成：`.venv` 不存在则创建 → `pip install -e ".[dev]"`
  → `pytest harness/tests -q`（Windows 用 `.venv\Scripts\python.exe`，
  POSIX 用 `.venv/bin/python`，Makefile 内通过 `$(OS)` 自动判断）。
- **GitLab 镜像仓库 CI**：仓库根目录 `.gitlab-ci.yml` 提供名为 `unit-test`
  的 job（与本地同一命令，push 时触发）。
- **Windows 无 make** 时的等价命令：

  ```powershell
  python -m venv .venv
  .venv\Scripts\python.exe -m pip install -e ".[dev]"
  .venv\Scripts\python.exe -m pytest harness/tests -q
  ```

- 只安装不跑测试：`make install`。

### 机制演示（§A.4-D 对齐）

`make demo` 顺序运行三个机制演示脚本（全部退出码 0 即通过）：

1. **demo_1_guardrail_deny** — 护栏拦截危险动作：FakeLLM 请求
   `rm -rf` 系统根目录等**不可逆破坏操作**时，护栏在**执行前**拒绝（deny），
   绝不让危险命令进入沙箱执行；敏感但可能正当的动作（如网络访问）
   走 **ask 审批**（HITL 菜单）而非 deny，任务不会被"一刀切"卡死；
2. **demo_2_feedback_change** — 反馈闭环：工具失败的错误信息回灌
   上下文后，模型的**下一步动作发生改变**（重试 → 换用替代命令）；
3. **demo_3_hitl_trace** — HITL 状态机全轨迹确定性复现：
   `ask → awaiting_user → 执行 → completed` 完整状态迁移。

其中 **demo ③（HITL 状态机全轨迹确定性复现）对应 §A.4-D"主要贡献"
清单中的重点维度**：以确定性方式复现人机协同的关键状态序列，作为
该贡献的可运行证据（配合 `test_mechanism_demo.py` 的自动化包装）。

### 离线确定性测试

- 全部测试**无网络依赖、不访问真实 LLM**：由 FakeLLM 客户端与
  `httpx.MockTransport` 驱动，可离线、确定性复现；MCP 测试使用手写的
  假 stdio 服务器子进程，不联网。
- 主要测试文件：
  `test_agent_core.py` / `test_agent_feedback.py` / `test_agent_context.py` /
  `test_agent_end.py`（六维度组件单测）、`test_repl.py`（REPL 行为）、
  `test_acceptance_matrix.py`（验收矩阵，逐条对应 §9）、
  `test_mechanism_demo.py`（机制演示包装，对应上文 demo ①②③）、
  `test_llm.py`（LLM 客户端，httpx MockTransport）。
- 其余覆盖：护栏/状态机/策略/记忆/沙箱/钩子/MCP/凭据扫描
  （`test_security_scan.py`）/性能冒烟（`test_perf_smoke.py`）/文档一致性
  （`test_docs.py`）。


## 已知限制

- 平台：Windows 10+ / Linux，Python 3.11+；需 DeepSeek 账号与网络连通。
- `mcp_servers` 的 stdio/url 服务器需用户自备；连接失败自动停用，不影响其余。
- Docker 沙箱后端需 Docker Desktop（可选）。
