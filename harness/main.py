"""Coding Agent Harness 交互入口：任务 REPL、斜杠命令、HITL 菜单与 Ctrl+C 处理。"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable

from harness.agent import Agent
from harness.config import Config
from harness.credentials import CredentialStore, wizard_enter_key
from harness.hooks import HookBus
from harness.llm import OpenAILLM
from harness.memory import MemoryStore
from harness.mcp import load_mcp_servers
from harness.policy import Policy
from harness.registry import Tool, make_registry
from harness.sandbox import LocalSandbox
from harness.state import StateError, StateMachine
from harness.tools.ask import spec as ask_spec
from harness.tools.bash import spec as bash_spec
from harness.tools.files import spec as files_spec
from harness.tools.memory import specs as memory_specs
from harness.tools.notes import spec as notes_spec
from harness.tools.search import spec as search_spec
from harness.tools.skills import specs as skills_specs
from harness.tools.subagent import spec as subagent_spec
from harness.tools.web import spec as web_spec

PROMPT = "> "


def make_agent(config: Config) -> Agent:
    """组装依赖图：CredentialStore → OpenAILLM → registry（内置工具 + MCP）→ Agent。"""
    store = CredentialStore()
    api_key = store.get()
    if not api_key:
        raise RuntimeError(
            "未配置 DeepSeek API Key：请用 /key set 或环境变量 DEEPSEEK_API_KEY 配置"
        )
    llm = OpenAILLM(api_key=api_key, base_url=config.base_url, model=config.model)
    sandbox = LocalSandbox(max_output_bytes=config.max_output_bytes)
    hooks = HookBus(transcript_dir=_transcript_dir(config))
    policy = Policy()
    state = StateMachine()
    memory = MemoryStore(_memory_dir(config), top_k=config.memory_top_k)
    memory.load()
    specs = [
        bash_spec(),
        web_spec(),
        ask_spec(),
        subagent_spec(),
        *files_spec(),
        *search_spec(),
        *notes_spec(),
        *memory_specs(memory),
        *skills_specs(_skills_root(config)),
    ]
    registry = make_registry([_to_tool(s) for s in specs])
    load_mcp_servers(config.mcp_servers, registry, sandbox, config)
    return Agent(
        llm,
        registry,
        sandbox,
        hooks,
        policy,
        state,
        memory,
        config,
        ask_callback=ask_menu,
        on_text=lambda text: print(text),
    )


def _to_tool(spec: Any) -> Tool:
    if isinstance(spec, Tool):
        return spec
    parameters = getattr(spec, "parameters", None)
    if parameters is None:
        parameters = getattr(
            spec, "schema", {"type": "object", "properties": {}, "required": []}
        )
    return Tool(
        name=spec.name,
        description=spec.description,
        parameters=parameters,
        requires_approval=getattr(spec, "requires_approval", False),
        needs_sandbox=getattr(spec, "needs_sandbox", False),
        uses_workspace=getattr(spec, "uses_workspace", False),
        handler=spec.handler,
    )


def ask_menu(question: str, options: list[str]) -> str:
    """编号菜单：打印问题与选项，非编号输入重试；EOF → 抛 KeyboardInterrupt。"""
    print(f"? {question}")
    for i, option in enumerate(options, start=1):
        print(f"{i}. {option}")
    while True:
        try:
            raw = input("请选择: ")
        except EOFError as exc:
            raise KeyboardInterrupt() from exc
        raw = raw.strip()
        if raw.isdigit() and 1 <= int(raw) <= len(options):
            return options[int(raw) - 1]
        print(f"无效选择，请输入 1-{len(options)}")


class _TokenCounter:
    def __init__(self, llm):
        self.llm = llm
        self.tokens = 0

    def complete(self, messages: list[dict], tools: list[dict]):
        result = self.llm.complete(messages, tools)
        usage = result.usage or {}
        self.tokens += usage.get("approx_tokens", 0)
        return result


def run_repl(config: Config) -> int:
    store = CredentialStore()
    if store.get() is None:
        _first_run_wizard(store)
    try:
        agent = make_agent(config)
    except Exception as exc:
        print(f"启动失败: {exc}")
        agent = None
    print("编码代理 REPL — 输入任务开始；/help 查看命令；顶层 Ctrl+C 退出")
    first = True
    while True:
        try:
            line = input(PROMPT)
        except EOFError:
            print()
            _end_session(agent)
            return 0
        except KeyboardInterrupt:
            print()
            _end_session(agent)
            return 0
        line = line.strip()
        if not line:
            continue
        if not first and line.startswith("/"):
            code, agent = _dispatch_command(agent, store, config, line)
            if code is not None:
                return code
            continue
        first = False
        _run_task(agent, line)


def _first_run_wizard(store) -> None:
    print("未检测到 DeepSeek API Key（keyring / .env 均无）。")
    try:
        answer = input("现在设置 API Key？[y/N] ")
    except (EOFError, KeyboardInterrupt):
        print()
        return
    if answer.strip().lower() in ("y", "yes"):
        try:
            key = wizard_enter_key()
            store.set(key)
            print("API Key 已保存")
        except (ValueError, RuntimeError) as exc:
            print(f"设置失败: {exc}")
    else:
        print("跳过设置；可在 REPL 中用 /key set 随时配置。")


def _end_session(agent) -> None:
    if agent is None:
        return
    try:
        messages = getattr(agent, "messages", None) or []
        agent.hooks.session_end(messages)
    except Exception:
        pass


def _dispatch_command(agent, store, config, line) -> tuple[int | None, Agent | None]:
    cmd, _, rest = line.partition(" ")
    if cmd == "/exit":
        return 0, agent
    if cmd == "/reset":
        try:
            print("会话已重置")
            return None, make_agent(config)
        except Exception as exc:
            print(f"重置失败: {exc}")
            return None, None
    if cmd == "/skills":
        _print_skills(config)
        return None, agent
    if cmd == "/rules":
        rest = rest.strip()
        if rest.startswith("drop skill:"):
            name = rest[len("drop skill:"):].strip()
            if agent is None:
                print("未配置 API Key，无法操作策略")
            else:
                removed = _drop_skill(agent, name)
                if removed:
                    print(f"已移除技能 {name} 的规则 {removed} 条")
                else:
                    print(f"未找到技能 {name} 的规则")
        elif agent is None:
            print("未配置 API Key，无法显示策略")
        else:
            for rule in agent.policy.rules:
                print(f"{rule.pattern} -> {rule.action} ({rule.source})")
        return None, agent
    if cmd == "/key":
        return _handle_key(agent, store, config, rest.strip())
    if cmd == "/memory":
        _print_memory(config)
        return None, agent
    if cmd == "/help":
        print("/exit /reset /skills /rules [/rules drop skill:<name>] "
              "/key set|status|clear /memory")
        return None, agent
    print(f"未知命令: {line}")
    return None, agent


def _handle_key(agent, store, config, sub: str) -> tuple[int | None, Agent | None]:
    if sub == "set":
        try:
            key = wizard_enter_key()
            store.set(key)
            print("API Key 已保存")
        except (ValueError, RuntimeError) as exc:
            print(f"设置失败: {exc}")
        if store.get() is not None:
            try:
                return None, make_agent(config)
            except Exception as exc:
                print(f"初始化失败: {exc}")
                return None, None
        return None, agent
    if sub == "status":
        status = store.status()
        print(
            f"配置: {'是' if status['configured'] else '否'}, "
            f"来源: {status['source'] or '无'}, "
            f"验证时间: {status['verified_at'] or '无'}"
        )
        return None, agent
    if sub == "clear":
        try:
            store.clear()
            print("API Key 已清除")
        except RuntimeError as exc:
            print(f"清除失败: {exc}")
        return None, agent
    print("用法: /key set|status|clear")
    return None, agent


def _run_task(agent, task: str, allow_resume: bool = True) -> None:
    if agent is None:
        print("未配置 API Key，无法执行任务。请使用 /key set 设置。")
        return
    if agent.on_text is None:
        agent.on_text = lambda text: print(text)
    print(f"任务: {task}")
    counter = _TokenCounter(agent.llm)
    agent.llm = counter
    interrupted = False
    try:
        result = agent.run(task)
    except KeyboardInterrupt:
        interrupted = True
        print()
    finally:
        agent.llm = counter.llm
    if interrupted:
        _handle_interrupt(agent, task, allow_resume)
        return
    for call, tres in zip(agent._tool_calls, result.tool_results):
        args = json.dumps(call["arguments"], ensure_ascii=False)
        if tres.status == "success" and not tres.error:
            print(f"→ {call['name']}: {args}")
        else:
            print(f"⊘ {call['name']}: {tres.error or tres.output}")
    print(f"[step {result.steps_used}/{agent.config.max_steps} | ~{counter.tokens} tok]")


def _handle_interrupt(agent, task: str, allow_resume: bool) -> None:
    try:
        agent.state.fire("interrupt", "user")
    except StateError:
        pass
    try:
        choice = ask_menu("任务已暂停，选择操作", ["resume", "abort"])
    except KeyboardInterrupt:
        choice = "abort"
    if choice == "abort":
        try:
            agent.state.fire("abort", "user")
        except StateError:
            pass
        print("任务已中止")
        return
    try:
        agent.state.fire("resume", "user")
    except StateError:
        pass
    if not allow_resume:
        print("任务已中止（不允许再次恢复）")
        return
    if agent.state.state == "awaiting_user":
        try:
            agent.state.fire("user_answered", "user")
        except StateError:
            pass
    if agent.state.state == "running":
        try:
            agent.state.fire("final_answer", "loop")
        except StateError:
            pass
    try:
        _run_task(agent, task, allow_resume=False)
    except StateError:
        print(f"状态机无法恢复（当前状态: {agent.state.state}），任务已中止")


def _drop_skill(agent, name: str) -> int:
    rules = agent.policy._skill_rules
    kept = [r for r in rules if r.source != f"skill:{name}"]
    removed = len(rules) - len(kept)
    agent.policy._skill_rules = kept
    return removed


def _print_skills(config) -> None:
    root = _skills_root(config)
    names = []
    if root.is_dir():
        for entry in sorted(root.iterdir()):
            if entry.is_dir() and (entry / "SKILL.md").is_file():
                names.append(entry.name)
    print("\n".join(names) if names else "（无技能）")


def _print_memory(config) -> None:
    root = _memory_dir(config)
    files = sorted(root.glob("*.md")) if root.is_dir() else []
    if not files:
        print("（无记忆）")
        return
    for path in files:
        print(path.stem)


def _skills_root(config) -> Path:
    return Path(config.workspace) / "skills"


def _memory_dir(config) -> Path:
    return Path(config.workspace) / "memory"


def _transcript_dir(config) -> Path:
    path = Path(config.workspace) / "transcripts"
    path.mkdir(parents=True, exist_ok=True)
    return path


def main() -> int:
    return run_repl(Config())


if __name__ == "__main__":
    import sys

    sys.exit(main())
