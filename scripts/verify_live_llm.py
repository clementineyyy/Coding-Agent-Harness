"""真实 LLM 链路端到端验证脚本（不在 pytest 套件内运行，CI 不会执行）。

用法:
    python scripts/verify_live_llm.py [--model deepseek-chat] [--base-url https://api.deepseek.com]

Key 来源优先级: keyring > .env（DEEPSEEK_API_KEY=...）> 环境变量 DEEPSEEK_API_KEY。
绝不打印 key 本身。
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from harness.credentials import CredentialStore
from harness.llm import LLMError, OpenAILLM
from harness.registry import make_registry
from harness.tools.bash import spec as bash_spec


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", default="deepseek-chat")
    parser.add_argument("--base-url", default="https://api.deepseek.com")
    parser.add_argument("--key", default=None, help="直接传 key（仅调试用；通常走 .env/keyring）")
    args = parser.parse_args()

    store = CredentialStore()
    key = args.key or store.get()
    if not key:
        print("FAIL: 未找到 API Key。请在仓库根目录 .env 写入: DEEPSEEK_API_KEY=sk-...（.env 已在 gitignore 中）")
        return 1

    mask = key[:6] + "…" + key[-4:] if len(key) > 12 else "sk-…"
    print(f"[1/3] 连接 {args.base_url} model={args.model} key={mask}")
    llm = OpenAILLM(api_key=key, base_url=args.base_url, model=args.model)

    # 场景 A: 纯文本回合（验证 SSE 流式解析 + usage 统计）
    try:
        t0 = time.time()
        res = llm.complete(
            messages=[{"role": "user", "content": "只回复两个字：收到"}],
            tools=[],
        )
        dt = time.time() - t0
        print(f"[2/3] 纯文本回合 OK ({dt:.2f}s)")
        print(f"      text: {res.text!r}")
        print(f"      tool_calls: {res.tool_calls}")
        print(f"      usage: {res.usage}")
        if not res.text or "收到" not in res.text:
            print("FAIL: 文本回合输出异常")
            return 1
    except LLMError as e:
        print(f"FAIL: 文本回合 LLMError: {type(e).__name__}: {e}")
        return 1

    # 场景 B: 工具调用回合（验证真实 tool_calls 字段映射）
    reg = make_registry([bash_spec()])
    tools = [
        {
            "type": "function",
            "function": {
                "name": t.name,
                "description": t.description,
                "parameters": t.parameters,
            },
        }
        for t in reg.values()
    ]
    try:
        t0 = time.time()
        res = llm.complete(
            messages=[
                {"role": "system", "content": "你是终端助手。需要执行命令时调用 bash 工具。"},
                {"role": "user", "content": "用 bash 工具执行命令 echo hello-from-live，然后告诉我它输出了什么。"},
            ],
            tools=tools,
        )
        dt = time.time() - t0
        print(f"[3/3] 工具调用回合 OK ({dt:.2f}s)")
        print(f"      tool_calls: {json.dumps(res.tool_calls, ensure_ascii=False, indent=2)}")
        if not res.tool_calls:
            print("FAIL: 模型未返回 tool_calls（可能未走工具调用路径）")
            return 1
        assert res.tool_calls[0]["function"]["name"] == "bash"
        assert "echo hello-from-live" in res.tool_calls[0]["function"]["arguments"]
        print("      工具名与参数解析正确")
    except LLMError as e:
        print(f"FAIL: 工具回合 LLMError: {type(e).__name__}: {e}")
        return 1

    print("\nLIVE VERIFY OK: 真实 LLM 链路（SSE 解析 + tool_calls 映射）验证通过")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
