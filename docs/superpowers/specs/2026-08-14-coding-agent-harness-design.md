# Coding Agent Harness — Design Spec

- Date: 2026-08-14
- Status: Draft
- Environment: Windows, Python 3.11+, model via DeepSeek API (OpenAI-compatible)

## 1. Overview

A minimal-but-real coding agent harness, built to learn how tools like opencode
and Claude Code work. It drives an LLM through an agentic loop — model turns,
tool calls, results fed back — wrapped in a security and interaction layer:

- **Guardrails** gate every tool call (allow / ask / deny)
- **Sandbox** isolates tool execution (pluggable executors)
- **Hooks** instrument the pipeline (PreToolUse / PostToolUse / SessionEnd)
- **HITL state machine** coordinates human-in-the-loop interaction, including
  agent-initiated questions
- **Adaptive policy** learns from user answers within a session
- **Subagents** recurse the same loop with fresh context
- **Skills** are loadable instruction files (SKILL.md convention) that may only
  tighten policy, never loosen it

Primary goal: readable, minimal code. The agentic loop stays front and center.

## 2. Non-goals (v1)

- No Docker backend (stub with fail-fast message until Docker is installed)
- No multi-user / auth / remote access
- No policy persistence across sessions (session-scoped only; persistence file
  is future work)
- No async framework — synchronous, single-threaded
- No TUI framework — plain terminal REPL

## 3. Architecture

```
harness/                          # project root == repo root
├── main.py          # REPL: prompt, menus, interrupt handling
├── agent.py         # Agent loop + tool pipeline
├── state.py         # HITL state machine (table-driven)
├── policy.py        # adaptive guardrail policy (session rules)
├── guardrails.py    # rule evaluation → allow | ask | deny
├── sandbox.py       # Sandbox interface: local (now), docker (stub)
├── hooks.py         # event bus: PreToolUse/PostToolUse/SessionEnd
├── llm.py           # DeepSeek client wrapper
├── config.py        # env, model, settings
├── skills/          # skill files (SKILL.md convention)
├── tools/
│   ├── __init__.py  # TOOL_REGISTRY
│   ├── bash.py      # run shell commands
│   ├── files.py     # read_file, write_file
│   ├── search.py    # glob, grep
│   ├── web.py       # fetch_url
│   ├── notes.py     # note_add, note_read
│   ├── subagent.py  # run_subagent
│   ├── ask.py       # ask_user
│   └── skills.py    # list_skills, load_skill
├── transcripts/     # session transcripts (written by SessionEnd)
└── tests/           # pytest + fake LLM client
```

Dependencies: `openai` (SDK, pointed at DeepSeek), `requests` (fetch_url).
Everything else is the Python standard library.

## 4. Components

### 4.1 Agent loop (agent.py)

One class, `Agent`. State: a `list[dict]` of messages (the only state).

Loop:
1. Build request: system prompt + history, `tools=` schemas from the registry
2. Call DeepSeek via `client.chat.completions.create(stream=True)`, relay
   streamed text to the terminal
3. No tool calls in the turn → final answer → return, loop ends
4. Otherwise, execute each tool call through the tool pipeline (section 5)
5. Append assistant message + `role: "tool"` results → back to step 1

Guardrails on the loop itself:
- Step cap (default 50), kills runaway loops with a clear message
- Tool timeout per call (default 30s)
- Conversation history held in memory only

### 4.2 HITL state machine (state.py)

Table-driven: a plain dict mapping `(state, event) → next state`.

```
States:
  idle, running, awaiting_user, paused, completed, terminated

Events:
  task_submitted, tool_requested, approval_needed, user_answered,
  agent_question, interrupt, resume, abort, final_answer, error
```

Canonical transitions:
- `idle + task_submitted → running`
- `running + approval_needed → awaiting_user` (guardrail ask)
- `running + agent_question → awaiting_user` (ask_user tool)
- `awaiting_user + user_answered → running`
- `awaiting_user + abort → terminated`
- `running + interrupt → paused`; `paused + resume → running`;
  `paused + abort → terminated`
- `running + final_answer → completed`; `completed + task_submitted → running`
- any + `error` → `running` (recoverable) unless session is unusable → `terminated`

Every event carries its source (guardrail, agent, user, loop) so the REPL can
render the right interaction.

### 4.3 Adaptive policy (policy.py)

Session-scoped `Policy` object holding live rules. Guardrail `ask` outcomes
feed back:

- User answers "always allow" → that rule downgrades to `allow` for the session
- Same pattern denied twice → auto-escalates to `deny` (session notice)
- Pattern approved repeatedly → auto-downgrades to `allow`
- `ask_user` answers record lightweight preferences (e.g., "don't delete
  files" → future deletes bump to ask)

`/rules` shows the live policy. Skill rules are tagged `skill:<name>` and can
be dropped with `/rules drop skill:<name>`. User-derived rules always win over
skill rules.

### 4.4 Guardrails (guardrails.py)

Ordered rules table: `tool-pattern → allow | ask | deny`, last match wins.
Rules come from three sources: built-in defaults, user answers (adaptive),
skill declarations (restrict-only, see 4.7).

Built-in defaults:
- Deny dangerous bash patterns (`rm -rf` on system paths, fork bombs, etc.)
- Deny writes outside the workspace
- Deny switching sandbox network mode without approval
- Everything else: allow

An `ask` verdict triggers the REPL menu (human-in-the-loop) and moves the
state machine to `awaiting_user`.

### 4.5 Sandbox (sandbox.py)

`Sandbox` interface — two backends, selected per tool via registry config:

- `local` — direct subprocess on the host (default; used by bash)
- `docker` — stub: raises a clear error stating Docker Desktop is required
  until the user installs it; the backend is fully wired to the interface so
  it slots in without touching other code

File tools operate on the workspace path only; path canonicalization
(`resolve()` + containment check) prevents `..` escapes and symlink escapes.

### 4.6 Hooks (hooks.py)

Small event bus. User registers Python callbacks in `hooks.py`. Hook points:

- `PreToolUse(name, args)` — observe or modify args; runs only after the
  guardrail approved the call; cannot resurrect a denied call
- `PostToolUse(name, args, result)` — observe/record
- `SessionEnd(messages)` — runs after final answer; default handler writes the
  transcript to `transcripts/<timestamp>.json`

Hook exceptions are logged, never fatal. Hook ordering: registration order.

### 4.7 Skills (skills/)

Directory convention: `skills/<name>/SKILL.md` with frontmatter
(`name`, `description`, optional `rules`, optional `hooks`).

Tools: `list_skills` (names + descriptions), `load_skill(name)` (reads file,
injects as a system message, registers any declared rules/hooks).

Security model (restrict-only, enforced at load time):
- Declared `rules` may only be `ask` or `deny` — `allow` declarations are
  rejected with a warning and dropped
- Declared `hooks` are observer-only: PostToolUse / SessionEnd; PreToolUse
  modification is rejected
- Violations fail loudly at `load_skill` time, and the offending parts are
  dropped while the skill's prompt still loads

### 4.8 Tools (tools/)

Registry: `TOOL_REGISTRY` maps `name → {description, parameters (JSON schema),
handler}`. The registry generates the API `tools=` payload.

| Tool | Handler | Notes |
|---|---|---|
| `bash` | bash.py | via Sandbox executor, timeout, captures stdout/stderr/exit code |
| `read_file` | files.py | workspace paths only |
| `write_file` | files.py | workspace paths only; guardrail-gated |
| `glob` | search.py | workspace paths only |
| `grep` | search.py | workspace paths only |
| `fetch_url` | web.py | `requests`, size cap on response |
| `note_add` / `note_read` | notes.py | model scratchpad (in-memory) |
| `run_subagent` | subagent.py | new Agent, fresh context, own step cap (~30), inherits guardrails/hooks/policy |
| `ask_user` | ask.py | renders numbered menu, answer returned as tool result |
| `list_skills` / `load_skill` | skills.py | skill loading + restrict-only registration |

Subagent isolation is free: each `Agent` holds its own messages list. The
parent receives the child's final answer as the tool result.

### 4.9 REPL (main.py)

- Prompt accepts a task; agent works with streamed output
- Inline tool activity: `→ bash: ls -la`, `⊘ denied: ...`, `? allow ...? (y/n)`
- `ask_user` renders a numbered menu; guardrail asks render y/n (with
  "always allow" / "never allow" options)
- Commands: `/exit`, `/reset` (clear context), `/skills`, `/rules`,
  `/rules drop skill:<name>`
- After each turn: token usage + step count

### 4.10 LLM wrapper (llm.py) + config (config.py)

- `config.py` reads `DEEPSEEK_API_KEY` from env; model `deepseek-chat`
- `llm.py`: thin wrapper — `openai.OpenAI(base_url="https://api.deepseek.com",
  api_key=...)`, exposes a single `complete(messages, tools) → stream`

## 5. Tool pipeline (per tool call)

```
tool requested
  → guardrail: allow | ask | deny            (policy.py, adaptive)
      ask → state=awaiting_user → menu → answer feeds back into policy
  → sandbox executor selected                (per-tool: local / docker-stub)
  → PreToolUse hook                          (observe/modify; cannot resurrect)
  → execute                                  (timeout)
  → PostToolUse hook                         (observe/record)
  → result appended as role:"tool" message
```

Guardrail is the security boundary; sandbox is the execution boundary; hooks
are instrumentation; the state machine is the interaction spine.

## 6. Error handling

- API errors (bad key, rate limit, network): clear message; session survives
- Tool exceptions: formatted error returned to the model as the tool result
  (model can self-correct); never a crash
- Guardrail deny / hook exceptions: deny wins; hook errors logged
- Ctrl+C: clean shutdown; fires `SessionEnd` (transcript saved)

## 7. Testing (pytest, no network)

- Fake LLM client stubs the SDK: scripted responses
  (turn 1 = tool call, turn 2 = final answer)
- Loop tests: message history, step cap, guardrail deny path, hook ordering
  (guardrail → PreToolUse → tool → PostToolUse), state machine transitions
- Tool tests: handlers against temp fixtures (bash capture, file read/write,
  glob/grep, mocked fetch_url, notes)
- Policy tests: escalation on double-deny, downgrade on always-allow,
  skill rule rejections (allow declared by skill is dropped)
- Subagent tests: parent + child scripted turns; context isolation asserted
- Path tests: `..` and symlink escapes rejected

## 8. Open decisions

None — all decisions resolved in brainstorming. Docker backend is stubbed,
not open.